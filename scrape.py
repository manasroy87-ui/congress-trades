import csv
import datetime
import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
import pdfplumber
import requests

YEAR = datetime.datetime.now().year  # 2026
ZIP_URL = f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{YEAR}FD.ZIP"
CSV_FILE = "trades.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 1. Load already processed DocIDs from existing trades.csv to save execution time
processed_doc_ids = set()
existing_rows = []

if os.path.exists(CSV_FILE):
  try:
    with open(CSV_FILE, mode="r", encoding="utf-8") as f:
      reader = csv.DictReader(f)
      for row in reader:
        existing_rows.append(row)
        if row.get("DocID"):
          processed_doc_ids.add(row["DocID"])
  except Exception as e:
    print(f"Could not load existing CSV: {e}")

print(f"Already processed DocIDs on file: {len(processed_doc_ids)}")

# 2. Fetch the official Master XML Index from the House Clerk
print(f"Downloading master disclosure ZIP: {ZIP_URL}")
resp = requests.get(ZIP_URL, headers=HEADERS, timeout=30)
if resp.status_code != 200:
  print(f"Failed to fetch {ZIP_URL} (Status code: {resp.status_code})")
  exit(1)

with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
  xml_filename = f"{YEAR}FD.xml"
  with z.open(xml_filename) as xml_file:
    tree = ET.parse(xml_file)
    root = tree.getroot()

# 3. Filter for PTR (FilingType == 'P') records
ptr_filings = []
for member in root.findall("Member"):
  if member.findtext("FilingType", "").strip() == "P":
    ptr_filings.append({
        "first": member.findtext("First", "").strip(),
        "last": member.findtext("Last", "").strip(),
        "district": member.findtext("StateDst", "").strip(),
        "filing_date": member.findtext("FilingDate", "").strip(),
        "doc_id": member.findtext("DocID", "").strip(),
    })

print(f"Total 2026 PTR filings found in XML: {len(ptr_filings)}")

# 4. Identify new filings that need to be parsed
new_filings = [f for f in ptr_filings if f["doc_id"] not in processed_doc_ids]
print(f"New filings to parse: {len(new_filings)}")

# If starting fresh, limit the initial batch to the most recent 25 filings to prevent runner timeout
if not processed_doc_ids and len(new_filings) > 25:
  new_filings = new_filings[-25:]

new_trade_rows = []


def parse_ptr_pdf(pdf_url, member_info):
  """Downloads a PTR PDF and extracts transaction table rows."""
  parsed_trades = []
  try:
    r = requests.get(pdf_url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
      return parsed_trades

    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
      for page in pdf.pages:
        table = page.extract_table()
        if not table:
          continue

        for row in table:
          # Clean cells
          cells = [
              c.replace("\n", " ").strip() if c else ""
              for c in row
              if c is not None
          ]
          row_text = " ".join(cells)

          # Skip header or empty rows
          if not cells or "Transaction" in row_text or "Asset" in row_text:
            continue

          # Typical PTR table layout has 6 to 8 columns:
          # [Asset Name & Ticker, Type (P/S), Tx Date, Notification Date, Amount, ...]
          # Search for dollar range amount
          amount_match = re.search(
              r"(\$[\d,]+\s*-\s*\$[\d,]+|\$1,000,001\s*-\s*\$5,000,000|Over"
              r" \$50,000,000)",
              row_text,
          )
          amount = amount_match.group(0) if amount_match else ""

          # Search for Date (MM/DD/YYYY)
          dates = re.findall(r"\b\d{1,2}/\d{1,2}/\d{4}\b", row_text)
          tx_date = dates[0] if dates else ""

          # Search for Ticker inside parentheses: (AAPL), (MSFT), etc.
          ticker_match = re.search(r"\(([A-Z]{1,5})\)", row_text)
          ticker = ticker_match.group(1) if ticker_match else "--"

          # Determine trade type
          tx_type = "Trade"
          if "purchase" in row_text.lower() or " p " in f" {row_text.lower()} ":
            tx_type = "Purchase"
          elif "sale" in row_text.lower() or " s " in f" {row_text.lower()} ":
            tx_type = "Sale"

          # Extract asset description
          asset_desc = cells[1] if len(cells) > 1 else cells[0]
          asset_desc = re.sub(r"\s+", " ", asset_desc)[:60]

          if amount or tx_date:
            parsed_trades.append({
                "Chamber": "House",
                "Filing Date": member_info["filing_date"],
                "Transaction Date": tx_date,
                "Politician": (
                    f"{member_info['first']} {member_info['last']}".strip()
                ),
                "District": member_info["district"],
                "Ticker": ticker,
                "Asset Description": asset_desc,
                "Type": tx_type,
                "Amount": amount,
                "DocID": member_info["doc_id"],
                "Filing Link": pdf_url,
            })
  except Exception as err:
    print(f"Error parsing PDF {pdf_url}: {err}")

  return parsed_trades


for filing in new_filings:
  pdf_url = f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{YEAR}/{filing['doc_id']}.pdf"
  trades_found = parse_ptr_pdf(pdf_url, filing)

  # If PDF table had no standard rows (e.g. scanned), add index-level entry
  if not trades_found:
    new_trade_rows.append({
        "Chamber": "House",
        "Filing Date": filing["filing_date"],
        "Transaction Date": filing["filing_date"],
        "Politician": f"{filing['first']} {filing['last']}".strip(),
        "District": filing["district"],
        "Ticker": "--",
        "Asset Description": "See PDF Report",
        "Type": "PTR Filing",
        "Amount": "Disclosed in PDF",
        "DocID": filing["doc_id"],
        "Filing Link": pdf_url,
    })
  else:
    new_trade_rows.extend(trades_found)

# 5. Combine new and existing rows, sort, and write to CSV
all_trades = new_trade_rows + existing_rows

# Deduplicate by (DocID, Ticker, Transaction Date, Amount)
deduped_trades = []
seen_keys = set()
for t in all_trades:
  key = (
      t.get("DocID"),
      t.get("Ticker"),
      t.get("Transaction Date"),
      t.get("Amount"),
  )
  if key not in seen_keys:
    seen_keys.add(key)
    deduped_trades.append(t)

# Sort descending by filing date
deduped_trades.sort(key=lambda x: x.get("Filing Date", ""), reverse=True)

fieldnames = [
    "Chamber",
    "Filing Date",
    "Transaction Date",
    "Politician",
    "District",
    "Ticker",
    "Asset Description",
    "Type",
    "Amount",
    "DocID",
    "Filing Link",
]

with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
  writer = csv.DictWriter(f, fieldnames=fieldnames)
  writer.writeheader()
  writer.writerows(deduped_trades)

print(f"Successfully wrote {len(deduped_trades)} trades to {CSV_FILE}.")
