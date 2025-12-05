import time
import requests
import pdfplumber
import yfinance as yf
from bs4 import BeautifulSoup
import re
import json
import os

# -------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

TRACKED_POLITICIANS = [
    {"name": "Nancy Pelosi", "last": "Pelosi", "first": "Nancy"},
    {"name": "Dan Crenshaw", "last": "Crenshaw", "first": "Daniel"},
    {"name": "Tommy Tuberville", "last": "Tuberville", "first": "Tommy"},
]

CHECK_INTERVAL = 60  # seconds
SEEN_FILE = "seen.json"

MIN_SPIKE = 150000
CHEAP_PRICE = 20
VOL_RANGE = 0.60

BASE_URL = "https://disclosures-clerk.house.gov"


def notify(msg):
    requests.post(DISCORD_WEBHOOK, json={"content": msg})


def fetch_ptrs(last, first):
    url = f"{BASE_URL}/PublicDisclosure/FinancialDisclosure?LastName={last}&FirstName={first}"
    r = requests.get(url, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    pdfs = []
    for a in soup.find_all("a", href=True):
        if "ptr-pdfs" in a["href"]:
            pdfs.append(BASE_URL + a["href"])
    return pdfs


def extract_transactions(pdf_url):
    try:
        r = requests.get(pdf_url, timeout=10)
        open("tmp.pdf", "wb").write(r.content)
        text = ""

        with pdfplumber.open("tmp.pdf") as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""

        txns = []

        pattern = re.compile(r"\$(\d[\d,]*)\s*-\s*\$(\d[\d,]*)")

        for line in text.split("\n"):
            m = pattern.search(line)
            if m:
                low = int(m.group(1).replace(",", ""))
                high = int(m.group(2).replace(",", ""))
                mid = (low + high) / 2

                t = re.findall(r"\b[A-Z]{1,5}\b", line)
                ticker = t[-1] if t else None

                if ticker:
                    txns.append({"ticker": ticker, "mid": mid})

        return txns

    except:
        return []


def analyze_spike(ticker, mid):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")

        if hist.empty:
            return False, None

        price = hist["Close"].iloc[-1]
        high = max(hist["High"])
        low = min(hist["Low"])
        vol_range = (high - low) / price

        reasons = []

        if mid >= MIN_SPIKE:
            reasons.append("LARGE CASH MOVE")

        if price <= CHEAP_PRICE:
            reasons.append("CHEAP STOCK")

        if vol_range >= VOL_RANGE:
            reasons.append("HIGH VOLATILITY")

        return (len(reasons) > 0, reasons)

    except:
        return False, None


def main():

    if not os.path.exists(SEEN_FILE):
        json.dump([], open(SEEN_FILE, "w"))

    seen = set(json.load(open(SEEN_FILE)))

    all_pdfs = []

    for pol in TRACKED_POLITICIANS:
        pdfs = fetch_ptrs(pol["last"], pol["first"])

        for pdf in pdfs:
            if pdf in seen:
                continue

            seen.add(pdf)
            all_pdfs.append((pol, pdf))

    json.dump(list(seen), open(SEEN_FILE, "w"))

    for pol, pdf in all_pdfs:
        txns = extract_transactions(pdf)

        for tx in txns:
            ticker = tx["ticker"]
            mid = tx["mid"]

            is_spike, reasons = analyze_spike(ticker, mid)

            if is_spike:
                notify(
                    f"📈 **Spiky Move Detected**\n"
                    f"Politician: {pol['name']}\n"
                    f"Ticker: {ticker}\n"
                    f"Midpoint: ${mid:,.0f}\n"
                    f"Reasons: {', '.join(reasons)}\n"
                    f"Source: {pdf}"
                )


if __name__ == "__main__":
    main()
