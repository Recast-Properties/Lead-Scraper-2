# scraper.py — one-file Craigslist scraper + optional Airtable push

import os, csv, datetime, re, time
import feedparser
import requests
from bs4 import BeautifulSoup

BASE = "https://portland.craigslist.org"
RSS = f"{BASE}/search/rea?purveyor=owner&format=rss&search_distance=50&postal=97201&sort=date"
UA = {"User-Agent": "Mozilla/5.0 (compatible; LeadScraper/1.0)"}

KEYWORDS = [
    (r"\b(as[\s-]?is|cash only|handyman|fixer|needs work|major repairs|foundation|mold|fire|red ?tag|code violation|tear ?down)\b", 2),
    (r"\b(motivated seller|must sell|need to sell|make offer|bring all offers)\b", 2),
    (r"\b(pre[-\s]?foreclosure|foreclosure|auction)\b", 2),
    (r"\b(eviction|squatter|squatters|bad tenant|non[-\s]?paying|tenant won.?t pay)\b", 2),
    (r"\b(vacant|out of state|absentee owner|estate|probate)\b", 1),
    (r"\b(asap|quick close|fast close|sell fast)\b", 1),
    (r"\b(asbestos|roof leak|water damage|sewer line|knob and tube)\b", 1),
]

def score(text: str):
    if not text:
        return 0, []
    t = text.lower()
    s, flags = 0, []
    for pat, w in KEYWORDS:
        if re.search(pat, t):
            s += w
            flags.append(pat)
    return min(s, 10), flags

def fetch_detail(url: str):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        body = ""
        sec = soup.select_one("#postingbody") or soup.select_one(".userbody")
        if sec:
            body = sec.get_text(" ", strip=True)
        price = soup.select_one(".price").get_text(strip=True) if soup.select_one(".price") else ""
        hood_el = soup.select_one(".postingtitletext small")
        hood = hood_el.get_text(strip=True).strip("()") if hood_el else ""
        addr = soup.select_one("#mapaddress")
        address = addr.get_text(strip=True) if addr else ""
        return body, price, hood, address
    except Exception:
        return "", "", "", ""

def run():
    print("[*] Fetching RSS…")
    feed = feedparser.parse(RSS)
    items = []
    for e in feed.entries[:120]:
        url = e.link
        title = getattr(e, "title", "")
        summary = getattr(e, "summary", "")
        body, price, hood, address = fetch_detail(url)
        blob = f"{title}\n{summary}\n{body}"
        s, flags = score(blob)
        items.append({
            "date_found": datetime.date.today().isoformat(),
            "source": "craigslist",
            "title": title.strip(),
            "url": url,
            "price": price,
            "hood": hood,
            "address": address,
            "description": (body or summary).strip(),
            "score": s,
            "flags": ",".join(flags)
        })
        time.sleep(0.5)  # be polite

    os.makedirs("output", exist_ok=True)
    today = datetime.date.today().isoformat()
    all_path = f"output/leads_{today}.csv"
    hot_path = f"output/hot_leads_{today}.csv"

    fields = ["date_found","source","title","url","price","hood","address","description","score","flags"]

    with open(all_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(items)

    hot = [x for x in items if x["score"] >= 6]
    with open(hot_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(hot)

    print(f"[✓] Wrote {len(items)} leads → {all_path}")
    print(f"[✓] Hot leads: {len(hot)} → {hot_path}")

    # Optional Airtable push for hot leads
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    table = os.getenv("AIRTABLE_TABLE_NAME", "Leads")
    if api_key and base_id and hot:
        push_airtable(api_key, base_id, table, hot)
    else:
        print("[i] Airtable not configured or no hot leads. Skipping push.")

def push_airtable(api_key, base_id, table, rows):
    url = f"https://api.airtable.com/v0/{base_id}/{table}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    # Airtable rate limit is 5 req/sec. Batch records.
    batch = []
    count = 0
    import json, math
    chunk = 10
    for i in range(0, len(rows), chunk):
        recs = [{"fields": {
            "Date Found": r["date_found"],
            "Source": r["source"],
            "Title": r["title"],
            "URL": r["url"],
            "Price": r["price"],
            "Neighborhood": r["hood"],
            "Address": r["address"],
            "Description": r["description"],
            "Score": r["score"],
            "Flags": r["flags"],
        }} for r in rows[i:i+chunk]]
        resp = requests.post(url, headers=headers, data=json.dumps({"records": recs, "typecast": True}), timeout=30)
        if resp.status_code >= 300:
            print("[!] Airtable error:", resp.status_code, resp.text)
            break
        count += len(recs)
        time.sleep(0.25)
    print(f"[*] Airtable: pushed {count} hot leads")

if __name__ == "__main__":
    run()
