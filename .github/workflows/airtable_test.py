# airtable_test.py — push 3 dummy rows into Airtable "Leads" to verify connectivity

import os, time, json, datetime, requests

API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE   = os.getenv("AIRTABLE_TABLE_NAME", "Leads")

if not API_KEY or not BASE_ID or not TABLE:
    raise SystemExit("Missing env vars: AIRTABLE_API_KEY / AIRTABLE_BASE_ID / AIRTABLE_TABLE_NAME")

URL = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE}"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

today = datetime.date.today().isoformat()

records = [
    {
        "fields": {
            "Date Found": today,
            "Source": "test",
            "Title": "Test Lead A — Fixer in SE Portland",
            "URL": "https://example.com/test-a",
            "Price": "$275,000",
            "Neighborhood": "SE Portland",
            "Address": "123 Test St, Portland, OR",
            "Description": "Dummy record to verify Airtable connection.",
            "Score": 7,
            "Flags": "as-is/fixer",
        }
    },
    {
        "fields": {
            "Date Found": today,
            "Source": "test",
            "Title": "Test Lead B — Tenant issues",
            "URL": "https://example.com/test-b",
            "Price": "$315,000",
            "Neighborhood": "NE Portland",
            "Address": "456 Sample Ave, Portland, OR",
            "Description": "Dummy record to verify Airtable connection.",
            "Score": 6,
            "Flags": "eviction/tenant-wont-pay",
        }
    },
    {
        "fields": {
            "Date Found": today,
            "Source": "test",
            "Title": "Test Lead C — Vacant & needs work",
            "URL": "https://example.com/test-c",
            "Price": "$199,000",
            "Neighborhood": "Gresham",
            "Address": "789 Demo Blvd, Gresham, OR",
            "Description": "Dummy record to verify Airtable connection.",
            "Score": 8,
            "Flags": "vacant/needs-work",
        }
    },
]

payload = {"records": records, "typecast": True}
resp = requests.post(URL, headers=HEADERS, data=json.dumps(payload), timeout=30)

print("Status:", resp.status_code)
try:
    print("Response:", resp.json())
except Exception:
    print("Response text:", resp.text)

if resp.status_code >= 300:
    raise SystemExit("Airtable insert failed")
