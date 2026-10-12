"""Pull a readable merchant/recipient out of a raw bank description, and suggest categories from keywords."""
from __future__ import annotations

import re

NOISE = {
    "upi", "dr", "cr", "imps", "neft", "rtgs", "payment", "paid", "to", "from", "via", "ref", "txn",
    "transaction", "ybl", "okaxis", "okhdfcbank", "oksbi", "okicici", "paytm", "ibl", "axl", "apl",
    "bank", "ltd", "pvt", "private", "limited", "india", "pay", "mob", "mobile", "banking", "nach", "ecs",
    "pos", "atm", "wdl", "cash", "chq", "cheque", "by", "transfer", "trf", "the", "and", "of", "ac", "p2a",
    "p2m", "p2p", "collect", "req", "request", "sent", "received", "money", "self", "upiintent", "utib",
    "hdfc", "icic", "sbin", "ifsc", "debit", "credit", "card", "ecom", "pur", "purchase", "online",
}

_LEAD = re.compile(r"(?i)^(?:paid to|received from|sent to|money sent to|payment to|self transfer to|transfer to|transfer from)\s+")
_IFSC = re.compile(r"^[A-Za-z]{4}0[A-Za-z0-9]{6}$")


def _clean_name(s: str) -> str:
    s = _LEAD.sub("", s.strip())
    s = s.split("@")[0]
    s = re.sub(r"[^A-Za-z0-9&.' ]+", " ", s)
    s = re.sub(r"\b\d{6,}\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if not s:
        return ""
    return s.title() if s.isupper() or s.islower() else s


def extract_merchant(description: str) -> str:
    d = (description or "").strip()
    if not d:
        return ""
    if m := re.match(r"(?i)^(paid to|received from|sent to|money sent to|payment to|self transfer to)\s+(.+?)(?:\s*\|.*)?$", d):
        return _clean_name(m.group(2))

    if re.match(r"(?i)^(atm|nfs)\b.*\b(wdl|wd|cash|withdrawal)\b", d) or re.match(r"(?i)^cash\s+(wdl|withdrawal)", d):
        return "ATM withdrawal"
    if re.match(r"(?i)^(int\.?\s?pd|int\.?\s?cr|interest)\b", d):
        return "Bank interest"

    if re.search(r"(?i)\bupi\b", d):
        for part in re.split(r"[/|\-]", d):
            p = part.strip()
            pl = p.lower()
            if not p or pl in NOISE or re.fullmatch(r"[\d\s]+", p) or _IFSC.match(p):
                continue
            p = _LEAD.sub("", p).split("@")[0].strip()
            if len(re.sub(r"[^A-Za-z]", "", p)) >= 3 and p.lower() not in NOISE:
                name = _clean_name(p)
                if name:
                    return name

    if m := re.search(r"(?i)(?:neft|imps|rtgs)[\w\s]*?[-/]\s*(?:[A-Z]{4}\d{7,}[-/])?\s*([A-Za-z][A-Za-z .&]{2,})", d):
        name = _clean_name(m.group(1))
        if name:
            return name

    if m := re.match(r"(?i)^(?:pos|ecom|pur|atm)\W+(?:\d+[Xx*]*\d*\W+)?([A-Za-z].+)$", d):
        name = _clean_name(m.group(1))
        if name:
            return " ".join(name.split()[:3])

    words = [w for w in re.findall(r"[A-Za-z][A-Za-z&.']+", d) if w.lower() not in NOISE]
    return _clean_name(" ".join(words[:3])) if words else _clean_name(d[:40])


def merchant_key(name: str) -> str:
    tokens = [t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if t not in NOISE and not t.isdigit()]
    return " ".join(tokens[:3])


# Category name -> keywords (whole-word match). Order matters: first match wins.
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Transfers", ("self transfer", "own account", "to self", "from self", "wallet load", "add money")),
    ("Savings", ("mutual fund", "sip", "zerodha", "groww", "upstox", "ppf", "nps", "recurring deposit",
                 "fixed deposit", "smallcase", "kuvera", "indmoney", "coin")),
    ("Subscriptions", ("netflix", "spotify", "hotstar", "prime video", "youtube premium", "youtube", "icloud",
                       "google one", "google play", "openai", "chatgpt", "anthropic", "notion", "adobe",
                       "microsoft", "github", "zee5", "sonyliv", "jiocinema", "audible", "apple")),
    ("Travel", ("irctc", "makemytrip", "goibibo", "redbus", "cleartrip", "indigo", "air india", "oyo",
                "airbnb", "booking", "ixigo", "yatra", "vistara", "akasa", "spicejet", "railway")),
    ("Food", ("swiggy", "zomato", "mcdonald", "mcdonalds", "kfc", "dominos", "pizza", "starbucks", "cafe",
              "restaurant", "biryani", "bakery", "juice", "dunkin", "burger", "tea", "coffee", "hotel",
              "dhaba", "eatsure", "box8", "faasos")),
    ("Groceries", ("bigbasket", "blinkit", "zepto", "dmart", "instamart", "supermarket", "grocery",
                   "provision", "reliance fresh", "more retail", "milk", "vegetable", "fruits", "nilgiris",
                   "lulu", "spencers", "jiomart", "fresh")),
    ("Transport", ("uber", "ola", "rapido", "metro", "fuel", "petrol", "diesel", "hpcl", "bpcl", "iocl",
                   "indian oil", "fastag", "parking", "kmrl", "ksrtc", "bus", "auto", "shell")),
    ("Health", ("pharmacy", "medplus", "apollo", "1mg", "pharmeasy", "hospital", "clinic", "lab",
                "diagnostic", "netmeds", "dental", "doctor", "medical", "tata 1mg")),
    ("Education", ("udemy", "coursera", "byju", "unacademy", "school", "college", "tuition", "fees",
                   "university", "exam", "course")),
    ("Entertainment", ("bookmyshow", "pvr", "inox", "cinema", "steam", "playstation", "gaming", "dream11",
                       "movie", "concert")),
    ("Bills", ("electricity", "kseb", "bescom", "water", "broadband", "airtel", "jio", "vodafone", "bsnl",
               "recharge", "lpg", "gas", "insurance", "lic", "postpaid", "dth", "tata play", "fibernet",
               "bill", "emi", "credit card")),
    ("Rent", ("rent", "landlord", "nobroker", "maintenance", "society")),
    ("Shopping", ("amazon", "flipkart", "myntra", "ajio", "meesho", "nykaa", "decathlon", "croma",
                  "reliance digital", "lifestyle", "zudio", "ikea", "westside", "pantaloons")),
    ("Income", ("salary", "interest", "dividend", "refund", "cashback", "reversal", "payroll", "bonus")),
]

_INCOME_WORDS = {"salary", "interest", "dividend", "refund", "cashback", "reversal", "payroll", "bonus"}


def keyword_category(text: str, direction: str) -> tuple[str, str] | None:
    """Return (category_name, matched_keyword) from built-in keywords, or None."""
    low = (text or "").lower()
    first: tuple[str, str] | None = None
    for cat, words in KEYWORDS:
        for w in words:
            if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low):
                if direction == "credit":
                    if w in _INCOME_WORDS:
                        return "Income", w
                    first = first or (cat, w)
                    continue
                return cat, w
    # A credit that names a shop but isn't clearly income is probably a refund for that shop's category.
    if direction == "credit" and first and first[0] != "Income":
        return first
    return None


SELF_TRANSFER = re.compile(r"(?i)\b(self[ -]?transfer|own account|to self|from self|own a/c)\b")
