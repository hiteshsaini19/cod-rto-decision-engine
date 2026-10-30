"""Combines the rule checks with the LLM for address / name / phone.

Rules first. Only 'unclear' text goes to the LLM. If the LLM can't answer,
the rule fallback is used and the result says so (source = "rules").
"""
from __future__ import annotations

import re

from .llm import LLMClient
from .text_checks import (
    check_pincode,
    fallback_address,
    fallback_name,
    is_hinglish,
    normalize_phone,
    rule_address,
    rule_name,
)

# Words that mean the text points at a real place a courier can ask about.
PLACE_WORDS = re.compile(
    r"\b(near|opp|opposite|behind|chowk|road|marg|mandir|temple|masjid|church|school|bank|market|bazaar|"
    r"station|gali|lane|sector|nagar|colony|society|apartment|tower|ke paas|ke saamne|ke peeche)\b",
    re.IGNORECASE,
)


def assess_orders(orders: list[dict], llm: LLMClient | None = None, cache_only: bool = False) -> list[dict]:
    """Return one assessment per order: {address, name, phone, hinglish}."""
    pending, results = [], []
    for i, o in enumerate(orders):
        addr = rule_address(o.get("address"), o.get("city"), o.get("state"), o.get("pincode"))
        name = rule_name(o.get("customer_name"))
        addr["source"] = name["source"] = "rules"
        phone, phone_ok = normalize_phone(o.get("phone"))
        results.append({
            "address": addr,
            "name": name,
            "phone": {"number": phone, "valid": phone_ok,
                      "issue": "" if phone_ok else f'phone "{o.get("phone")}" is not a valid 10-digit mobile'},
            "hinglish": is_hinglish(str(o.get("address") or "")),
        })
        if addr["quality"] == "unclear" or name["quality"] == "unclear":
            pending.append({
                "id": i, "name": o.get("customer_name"), "address": o.get("address"),
                "city": o.get("city"), "state": o.get("state"), "pincode": o.get("pincode"),
                "need_address": addr["quality"] == "unclear", "need_name": name["quality"] == "unclear",
            })

    llm_out = llm.check_texts(pending, cache_only=cache_only) if (llm and pending) else {}

    for p in pending:
        r, o = results[p["id"]], orders[p["id"]]
        got = llm_out.get(p["id"], {})
        if p["need_address"]:
            a = got.get("address")
            if a:
                pin_issue = check_pincode(o.get("pincode"), o.get("state"))
                quality, issue = a["quality"], a.get("issue", "")
                if quality == "unusable" and PLACE_WORDS.search(str(o.get("address") or "")):
                    # Guardrail: the LLM was inconsistent here (same "call me, near Masjid" pattern
                    # marked unusable 3 times, incomplete 40+ times). An address naming a real place
                    # is findable with a phone call, so never hold an order on that opinion alone.
                    quality = "incomplete"
                if pin_issue and quality == "complete":
                    quality, issue = "incomplete", pin_issue
                elif pin_issue and pin_issue not in issue:
                    issue = f"{issue}; {pin_issue}" if issue else pin_issue
                r["address"] = {"quality": quality, "issue": issue,
                                "english": a.get("english", ""), "source": "llm"}
            else:
                r["address"] = {**fallback_address(o.get("address"), o.get("city"), o.get("state"),
                                                   o.get("pincode")), "source": "rules"}
        if p["need_name"]:
            n = got.get("name")
            if n:
                issue = "" if n["quality"] == "real" else f'name "{o.get("customer_name")}" looks {n["quality"]}'
                r["name"] = {"quality": n["quality"], "issue": issue, "source": "llm"}
            else:
                r["name"] = {**fallback_name(o.get("customer_name")), "source": "rules"}
    return results
