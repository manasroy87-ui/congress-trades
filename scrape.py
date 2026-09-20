import csv
import json
import urllib.request

HOUSE_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"
CSV_FILE = "trades.csv"

trades = []

# 1. Fetch U.S. House Disclosures
try:
  req = urllib.request.Request(HOUSE_URL, headers={"User-Agent": "Mozilla/5.0"})
  with urllib.request.urlopen(req, timeout=30) as response:
    house_data = json.loads(response.read().decode("utf-8"))
    for t in house_data[-200:]:  # Last 200 disclosures
      trades.append({
          "Chamber": "House",
          "Filing Date": t.get("disclosure_date", ""),
          "Transaction Date": t.get("transaction_date", ""),
          "Politician": t.get("representative", ""),
          "Ticker": t.get("ticker", "--"),
          "Asset Description": (t.get("asset_description") or "").replace(
              "\n", " "
          ),
          "Type": t.get("type", ""),
          "Amount": t.get("amount", ""),
          "Owner": t.get("owner", "Self"),
      })
except Exception as e:
  print(f"Error loading House data: {e}")

# 2. Fetch U.S. Senate Disclosures
try:
  req = urllib.request.Request(
      SENATE_URL, headers={"User-Agent": "Mozilla/5.0"}
  )
  with urllib.request.urlopen(req, timeout=30) as response:
    senate_data = json.loads(response.read().decode("utf-8"))
    for t in senate_data[-200:]:  # Last 200 disclosures
      trades.append({
          "Chamber": "Senate",
          "Filing Date": t.get("date_recieved", ""),
          "Transaction Date": t.get("transaction_date", ""),
          "Politician": t.get("senator", ""),
          "Ticker": t.get("ticker", "--"),
          "Asset Description": (t.get("asset_description") or "").replace(
              "\n", " "
          ),
          "Type": t.get("type", ""),
          "Amount": t.get("amount", ""),
          "Owner": t.get("owner", "Self"),
      })
except Exception as e:
  print(f"Error loading Senate data: {e}")

# 3. Sort chronologically by transaction date descending
trades.sort(key=lambda x: x["Transaction Date"], reverse=True)

# 4. Write to CSV
fieldnames = [
    "Chamber",
    "Filing Date",
    "Transaction Date",
    "Politician",
    "Ticker",
    "Asset Description",
    "Type",
    "Amount",
    "Owner",
]

with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
  writer = csv.DictWriter(f, fieldnames=fieldnames)
  writer.writeheader()
  writer.writerows(trades)

print(f"Successfully generated {CSV_FILE} with {len(trades)} records.")
