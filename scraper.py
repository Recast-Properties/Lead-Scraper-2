# scraper.py — Craigslist FSBO scraper for Portland + optional Airtable push
# Works in GitHub Actions or locally.

import os
import re
import csv
import time
import json
import datetime
from typing import List, Dict, Tuple

import requests
import feedparser
from bs4 import BeautifulSoup

BASE = "https://portland.craigslist.org"
RSS = (
    f"{BASE}/search/rea"
    "?purveyor=owner&format=rss&search_distance=50&postal=97201&sort=date"
)

UA = {"User-Agent": "Mozilla/5.0 (compatible; LeadScraper/1.0)"}

# Keyword signals for motivation scoring
KEYWORDS: List[Tuple[str, int]] = [
    # Strong signals
    (r"\b(as[\s-]?is|cash only|handyman|fixer|needs work|major repairs|foundation|mold|fire|red ?tag|code violation|tear ?down)\b", 2),
    (r"\b(motivated seller|must sell|need to sell|make offer|bring all offers)\b", 2),
    (r"\b(pre[-\s]?foreclosure|foreclosure|auction)\b", 2),
    (r"\b(eviction|squatter|squatters|bad tenant|non[-\s]?paying|tenant won.?t pay)\b", 2),
    # Medium signals
    (r"\b(vacant|out of state|absentee owner|estate|probate)\b", 1),
    (r"\b(asap|quick close|fast close|sell fast)\b", 1),
    (r"\b(asbestos|roof leak|water damage|sewer line|knob and tube)\b", 1),
]

FIELDS = [
    "date_found",
    "source",
    "title",
    "url",
    "price",
    "hood",
    "address",
    "description",
    "score",
    "flags",
]


def score(text: str) -> Tuple[int, List[str]]:
    if not text:
        return 0, []
    t = text.lower()
    s, flags = 0, []
    for pat, weight in KEYWORDS:
        if re.search(pat, t):
            s += weight
            flags.append(pat)
    return min(s, 10), flags


def fetch_detail(url: str) -> Tuple[str, str, str, str]:
    """Fetch a Craigslist detail page and extract description, price, neighborhood, address."""
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        section = soup.select_one("#postingbody") or soup.select_one(".userbody")
        body = section.get_text(" ", strip=True) if section else ""

        price_el = soup.select_one(".price")
        price = price_el.get_text(strip=True) if price_el else ""

        hood_el = soup.select_one(".postingtitletext small")
        hood = hood_el.get_text(strip=True).strip("()") if hood_el else ""

        mapaddr = soup.select_one("#mapaddress")
        address = mapaddr.get_text(strip=True) if mapaddr else ""

        return body, price, hood, address
    except Exception:
        return "", "", "", ""


def fetch_items(limit: int = 120) -> List[Dict]:
    """Fetch recent FSBO posts via RSS and hydrate each with detail data."""
    print("[*] Fetching RSS…")
    feed = feedparser.parse(RSS)
    items = []

    for e in feed.entries[:limit]:
        url = getattr(e, "link", "")
        title = getattr(e, "title", "").strip()
        summary = getattr(e, "summary", "")
        if not url:
            continue

        body, price, hood, address = fetch_detail(url)
        blob = f"{title}\n{summary}\n{body}"
        s, flags = score(blob)

        items.append(
            {
                "date_found": datetime.date.today().isoformat(),
                "source": "craigslist",
                "title": title,
                "url": url,
                "price": price,
                "hood": hood,
                "address": address,
                "description": (body or summary).strip(),
                "score": s,
                "flags": ",".join(flags),
            }
        )
        time.sleep(0.4)  # be polite to the site

    print(f"[✓] Collected {len(items)} items from RSS")
    return items


def write_csv(items: List[Dict]) -> Tuple[str, str]:
    os.makedirs("output", exist_ok=True)
    today = datetime.date.today().isoformat()
    all_path = f"output/leads_{today}.csv"
    hot_path = f"output/hot_leads_{today}.csv"

    with open(all_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for row in items:
            w.writerow({k: row.get(k, "") for k in FIELDS})

    hot = [x for x in items if x["score"] >= int(os.getenv("MIN_SCORE", "6"))]
    with open(hot_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for row in hot:
            w.writerow({k: row.get(k, "") for k in FIELDS})

    print(f"[✓] Wrote CSV → {all_path}")
    print(f"[✓] Wrote CSV → {hot_path} (hot)")
    return all_path, hot_path


def push_airtable(api_key: str, base_id: str, table: str, rows: List[Dict]) -> int:
    """Push rows to Airtable using the REST API in small batches."""
    url = f"https://api.airtable.com/v0/{base_id}/{table}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    total = 0
    chunk = 10
    for i in range(0, len(rows), chunk):
        payload = {
            "records": [
                {
                    "fields": {
                        "Date Found": r.get("date_found"),
                        "Source": r.get("source"),
                        "Title": r.get("title"),
                        "URL": r.get("url"),
                        "Price": r.get("price"),
                        "Neighborhood": r.get("hood"),
                        "Address": r.get("address"),
                        "Description": r.get("description"),
                        "Score": r.get("score"),
                        "Flags": r.get("flags"),
                    }
                }
                for r in rows[i : i + chunk]
            ],
            "typecast": True,
        }

        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        if resp.status_code >= 300:
            print("[!] Airtable error:", resp.status_code, resp.text)
            break
        total += len(payload["records"])
        time.sleep(0.25)  # respect Airtable rate limits

    return total


def run():
    # Env toggles
    min_score = int(os.getenv("MIN_SCORE", "6"))   # change in workflow env for testing
    push_all = os.getenv("PUSH_ALL", "0") == "1"   # set to "1" to push all leads
    airtable_key = os.getenv("AIRTABLE_API_KEY")
    airtable_base = os.getenv("AIRTABLE_BASE_ID")
    airtable_table = os.getenv("AIRTABLE_TABLE_NAME", "Leads")

    print(f"[i] MIN_SCORE={min_score}, PUSH_ALL={push_all}")

    items = fetch_items(limit=120)
    all_path, hot_path = write_csv(items)

    # Decide which set to push
    hot = [x for x in items if x["score"] >= min_score]
    to_push = items if push_all else hot
    label = "all leads" if push_all else f"hot leads ≥ {min_score}"

    if airtable_key and airtable_base and to_push:
        print(f"[*] Airtable: pushing {len(to_push)} {label}")
        count = push_airtable(airtable_key, airtable_base, airtable_table, to_push)
        print(f"[✓] Airtable: pushed {count} records")
    else:
        reason = []
        if not airtable_key:
            reason.append("no AIRTABLE_API_KEY")
        if not airtable_base:
            reason.append("no AIRTABLE_BASE_ID")
        if not to_push:
            reason.append(f"no {label} to push")
        print(f"[i] Skipping Airtable push ({', '.join(reason)})")

    # Print directory info for GitHub Actions artifact step
    print("--- OUTPUT DIR TREE ---")
    try:
        print("\n".join(os.listdir(".")))
    except Exception:
        pass
    print("--- OUTPUT SUBDIR ---")
    try:
        print("\n".join(os.listdir("output")))
    except Exception:
        print("(no output directory found)")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        import traceback
        print("[!] Unhandled error:", e)
        traceback.print_exc()
        raise
