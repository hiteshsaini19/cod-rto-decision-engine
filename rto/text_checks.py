"""Cheap, rule-based checks on phone, address and name.

These handle the obvious cases (most orders) for free and instantly.
Only text the rules can't judge is marked "unclear" and sent to the LLM.
"""
from __future__ import annotations

import re

# Things people type when they don't want to give an address.
JUNK_ADDRESSES = {
    ".", "..", "-", "xyz", "abc", "na", "n/a", "nil", "none", "test", "home", "my home",
    "house", "call me", "call", "near station", "station", "address", "same", "asdf",
    "qwerty", "india", "ghar", "mera ghar",
}
FAKE_NAMES = {
    "asdf", "qwerty", "test", "test order", "testing", "abc", "aaa", "xyz", "xyz xyz",
    "na", "n/a", "none", "null", "customer", "user", "name", "abcd", "sdf", "dummy",
}
# A house / flat / plot number makes an address findable.
HOUSE_NUMBER = re.compile(
    r"(\b(flat|house|h\.?\s?no|plot|door|room|shop|block|qtr|quarter)\b\s*(no\.?)?\s*[-#:]?\s*\d+)"
    r"|(\b[a-z]-\s?\d+)"          # B-597
    r"|(\b\d+\s*/\s*\d+\b)"       # 399/13
    r"|(#\s*\d+)"
    r"|(^\s*\d+[a-z]?\s*,)",      # "12, MG Road"
    re.IGNORECASE,
)
# Hinglish markers - addresses written in Hindi words using English letters.
HINGLISH_WORDS = re.compile(
    r"\b(ke|ka|ki|paas|saamne|samne|peeche|piche|andar|gali|wala|wali|ghar|naam|niwas|"
    r"krke|karke|aana|chowk|mod|se)\b",
    re.IGNORECASE,
)

# First digit of a pincode -> states it can belong to.
PIN_FIRST_DIGIT_STATES = {
    "1": {"Delhi", "Haryana", "Punjab", "Himachal Pradesh", "Jammu and Kashmir", "Chandigarh"},
    "2": {"Uttar Pradesh", "Uttarakhand"},
    "3": {"Rajasthan", "Gujarat", "Dadra and Nagar Haveli", "Daman and Diu"},
    "4": {"Maharashtra", "Madhya Pradesh", "Chhattisgarh", "Goa"},
    "5": {"Telangana", "Andhra Pradesh", "Karnataka"},
    "6": {"Tamil Nadu", "Kerala", "Puducherry", "Lakshadweep"},
    "7": {"West Bengal", "Odisha", "Assam", "Sikkim", "Arunachal Pradesh", "Meghalaya",
          "Manipur", "Mizoram", "Nagaland", "Tripura", "Andaman and Nicobar Islands"},
    "8": {"Bihar", "Jharkhand"},
}


def normalize_phone(phone) -> tuple[str | None, bool]:
    """Return (10-digit mobile, is_valid). Accepts '+91 98xxx xxxxx', '098...', etc."""
    if phone is None or (isinstance(phone, float) and phone != phone):
        return None, False
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    valid = bool(re.fullmatch(r"[6-9]\d{9}", digits))
    return digits or None, valid


def _clean_text(s) -> str:
    if s is None or (isinstance(s, float) and s != s):
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def is_hinglish(text: str) -> bool:
    return len(HINGLISH_WORDS.findall(text or "")) >= 2


def check_pincode(pincode, state) -> str | None:
    """Return a problem description, or None if the pincode looks fine."""
    pin = _clean_text(pincode)
    if not pin:
        return "pincode missing"
    if not re.fullmatch(r"[1-9]\d{5}", pin):
        return "pincode is not 6 digits"
    allowed = PIN_FIRST_DIGIT_STATES.get(pin[0])
    if state and allowed and _clean_text(state) not in allowed:
        return f"pincode {pin} doesn't belong to {state}"
    return None


def rule_address(address, city=None, state=None, pincode=None) -> dict:
    """Judge an address with rules.

    quality: complete | incomplete | unusable | unclear (unclear -> ask the LLM)
    """
    a = _clean_text(address)
    low = a.lower().strip(" .,")
    city_l, state_l = _clean_text(city).lower(), _clean_text(state).lower()
    pin_issue = check_pincode(pincode, state)

    if a and (low in JUNK_ADDRESSES or a.strip().lower() in JUNK_ADDRESSES):
        return {"quality": "unusable", "issue": f'address is just "{a}"'}
    if not low or len(low) < 4 or not re.search(r"[a-z]", low):
        return {"quality": "unusable", "issue": "address is empty or too short"}
    if low in (city_l, state_l):
        return {"quality": "unusable", "issue": "address is only the city name"}
    if len(low.split()) <= 2 and not HOUSE_NUMBER.search(a):
        return {"quality": "unusable", "issue": f'address "{a}" is too vague to deliver'}

    if HOUSE_NUMBER.search(a) and len(re.findall(r"[A-Za-z]{3,}", a)) >= 2:
        if pin_issue:
            return {"quality": "incomplete", "issue": pin_issue}
        return {"quality": "complete", "issue": ""}
    # Landmark-only / Hinglish / anything else: a person (or the LLM) has to read it.
    return {"quality": "unclear", "issue": pin_issue or ""}


def fallback_address(address, city=None, state=None, pincode=None) -> dict:
    """What we decide for an 'unclear' address when the LLM is not available."""
    pin_issue = check_pincode(pincode, state)
    issue = "no house/flat number, only landmarks"
    if pin_issue:
        issue += f"; {pin_issue}"
    return {"quality": "incomplete", "issue": issue}


def rule_name(name) -> dict:
    """quality: real | fake | unclear"""
    n = _clean_text(name)
    low = n.lower()
    if not low or low in FAKE_NAMES:
        return {"quality": "fake", "issue": f'name "{n}" looks fake' if n else "name is empty"}
    words = low.split()
    if len(set(words)) == 1 and len(words) > 1:
        return {"quality": "fake", "issue": f'name "{n}" repeats the same word'}
    if any(w in FAKE_NAMES for w in words) and len(words) <= 2:
        return {"quality": "fake", "issue": f'name "{n}" looks fake'}
    if re.search(r"\d", low) or re.search(r"(.)\1{3,}", low):
        return {"quality": "fake", "issue": f'name "{n}" has numbers or repeated letters'}
    if re.fullmatch(r"[a-z][a-z.']+( [a-z][a-z.']+){1,3}", low):
        return {"quality": "real", "issue": ""}
    return {"quality": "unclear", "issue": ""}


def fallback_name(name) -> dict:
    """An 'unclear' name without the LLM: single words like 'Rahul' are fine, odd ones suspicious."""
    n = _clean_text(name)
    if re.fullmatch(r"[A-Za-z]{3,}", n):
        return {"quality": "real", "issue": ""}
    return {"quality": "suspicious", "issue": f'name "{n}" looks unusual'}
