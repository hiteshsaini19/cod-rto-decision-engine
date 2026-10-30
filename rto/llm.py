"""OpenRouter LLM client - used ONLY for messy text the rules can't judge.

Used for:
  1. Is this address deliverable? (incl. Hinglish like "chowk se left, Mandir ke saamne")
  2. Does this name look real?
  3. What does this WhatsApp reply mean? ("kal bhej dena", "address galat hai")

Not used for risk %, thresholds, money or anything maths can do.

Safety nets:
  - results cached in data/llm_cache.json (same text is never sent twice)
  - many orders sent in one request (free tier = ~50 requests/day)
  - no key / error / bad JSON -> returns None and the caller falls back to rules
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time

import requests
from dotenv import load_dotenv

from .config import LLM_CACHE_PATH, ROOT

load_dotenv(ROOT / ".env")
log = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
# Tested on our messy addresses (Oct 2026). Free models come and go - override with OPENROUTER_MODELS in .env.
DEFAULT_MODELS = ("dots-studio/dots-3-note-preview:free,nvidia/nemotron-3.5-lightning:free,"
                  "nvidia/nemotron-3.5-super-vl:free,google/gemma-4-31b-it:free")
ADDRESS_QUALITIES = {"complete", "incomplete", "unusable"}
NAME_QUALITIES = {"real", "suspicious", "fake"}
REPLY_INTENTS = {"yes", "no", "pay_online", "keep_cod", "cancel", "change_address", "question", "unclear"}

TEXT_PROMPT = """You check delivery details for an Indian online store before a Cash-on-Delivery order is shipped.
Addresses may be in English, Hinglish (Hindi in English letters) or a mix.

For EACH item decide:
- address_quality:
    "complete"   = a courier can find it: has a house/flat/plot/shop number (or a named building with a flat no.) plus area/street
    "incomplete" = real place but courier will need to call: only landmarks, lane number, or house name without street/area
    "unusable"   = not an address: placeholder text, a single word, only the city name, "call me", gibberish
- address_issue: short plain-English problem for an ops person ("" if complete)
- address_english: the address rewritten in plain English for the courier
- name_quality: "real" (plausible Indian or other real name), "suspicious" (odd but possible), "fake" (keyboard mash, "test", "asdf", placeholder)

Reply with ONLY this JSON, no other text:
{"results":[{"id":"<id>","address_quality":"...","address_issue":"...","address_english":"...","name_quality":"..."}]}"""

REPLY_PROMPT = """You read WhatsApp replies from Indian shoppers (English, Hindi, Hinglish) to a message about their Cash-on-Delivery order.
Flow "{flow}": {flow_desc}
Classify the customer's reply into exactly one intent:
- "yes"            = confirms the order / go ahead - INCLUDING "send it tomorrow", "deliver in the
                     evening", "not home now, come later" (they still want the order, only the timing differs)
- "no"             = does not want the order
- "pay_online"     = wants to pay online now
- "keep_cod"       = wants to keep cash on delivery
- "cancel"         = wants to cancel the order
- "change_address" = wants to change or correct the address (or sends a new address)
- "question"       = asks something (price, delivery date, etc.)
- "unclear"        = anything else
Reply with ONLY JSON: {{"intent":"...","summary":"<5-10 word English summary>"}}"""

FLOW_DESC = {
    "confirm": "we asked them to confirm the COD order before we ship it.",
    "nudge": "we offered a discount to pay online now instead of cash on delivery.",
    "hold": "we told them we can't ship until they send a complete address or pay online.",
}


class LLMClient:
    def __init__(self, api_key: str | None = None, models: str | None = None,
                 timeout: float | None = None, cache_path=LLM_CACHE_PATH, use_cache: bool = True):
        self.api_key = (api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")).strip()
        self.models = [m.strip() for m in (models or os.getenv("OPENROUTER_MODELS") or DEFAULT_MODELS).split(",") if m.strip()]
        # Per-request timeout, and a total budget across all fallback models, so a live
        # order never waits more than ~45s before falling back to the rules.
        self.timeout = timeout or float(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
        self.total_budget = float(os.getenv("LLM_TOTAL_BUDGET_SECONDS", "45"))
        self.batch_size = int(os.getenv("LLM_BATCH_SIZE", "20"))
        self.cache_path = cache_path
        self.use_cache = use_cache
        self._lock = threading.Lock()
        self._cache = self._load_cache()
        self.last_error: str | None = None
        self.requests_made = 0

    # ---------- plumbing ----------
    @property
    def available(self) -> bool:
        return bool(self.api_key) and not self.api_key.startswith("your-")

    def _load_cache(self) -> dict:
        if self.use_cache and self.cache_path and self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
        return {}

    def _save_cache(self) -> None:
        if not (self.use_cache and self.cache_path):
            return
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self.cache_path)

    @staticmethod
    def _key(kind: str, *parts) -> str:
        norm = "|".join(re.sub(r"\s+", " ", str(p or "")).strip().lower() for p in parts)
        return f"{kind}:{hashlib.sha1(norm.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _parse_json(text: str):
        if not text:
            return None
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            return None

    def _chat(self, system: str, user: str):
        """Try each model in turn; return parsed JSON or None."""
        if not self.available:
            self.last_error = "no API key"
            return None
        errors = []
        started = time.monotonic()
        for model in self.models:
            for attempt in range(2):
                left = self.total_budget - (time.monotonic() - started)
                if left < 3:
                    errors.append("time budget used up")
                    break
                try:
                    self.requests_made += 1
                    r = requests.post(
                        API_URL,
                        headers={"Authorization": f"Bearer {self.api_key}",
                                 "X-Title": "COD RTO decision engine"},
                        json={"model": model, "temperature": 0,
                              "response_format": {"type": "json_object"},
                              "messages": [{"role": "system", "content": system},
                                           {"role": "user", "content": user}]},
                        timeout=min(self.timeout, left),
                    )
                except requests.RequestException as e:
                    errors.append(f"{model}: {type(e).__name__}")
                    break
                if r.status_code == 429 and attempt == 0:
                    time.sleep(3)
                    continue
                if r.status_code != 200:
                    errors.append(f"{model}: HTTP {r.status_code}")
                    break
                try:
                    body = r.json()
                    content = body["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError):
                    errors.append(f"{model}: bad response")
                    break
                parsed = self._parse_json(content)
                if parsed is not None:
                    self.last_error = None
                    return parsed
                errors.append(f"{model}: reply was not JSON")
                break
        self.last_error = "; ".join(errors)
        log.warning("LLM unavailable: %s", self.last_error)
        return None

    # ---------- address + name ----------
    def check_texts(self, items: list[dict], cache_only: bool = False) -> dict:
        """items: [{id, name, address, city, state, pincode, need_address, need_name}]

        Returns {id: {"address": {...} | None, "name": {...} | None}} for items it could judge.
        """
        out: dict = {}
        todo = []
        for it in items:
            res = {"address": None, "name": None}
            # Keyed on the address text only, so the same address in another order is free.
            akey = self._key("addr", it.get("address"))
            nkey = self._key("name", it.get("name"))
            if it.get("need_address"):
                res["address"] = self._cache.get(akey)
            if it.get("need_name"):
                res["name"] = self._cache.get(nkey)
            missing = (it.get("need_address") and res["address"] is None) or \
                      (it.get("need_name") and res["name"] is None)
            out[it["id"]] = res
            if missing:
                todo.append((it, akey, nkey))
        if cache_only or not todo or not self.available:
            return out

        # Send each distinct text once; every order sharing it is filled from the cache after.
        unique = list({(a if it.get("need_address") else "", n if it.get("need_name") else ""): (it, a, n)
                       for it, a, n in todo}.values())
        for i in range(0, len(unique), self.batch_size):
            batch = unique[i:i + self.batch_size]
            payload = [{"id": str(k), "name": it.get("name") or "", "address": it.get("address") or "",
                        "city": it.get("city") or "", "state": it.get("state") or "",
                        "pincode": it.get("pincode") or ""}
                       for k, (it, _, _) in enumerate(batch)]
            parsed = self._chat(TEXT_PROMPT, json.dumps(payload, ensure_ascii=False))
            results = (parsed or {}).get("results") if isinstance(parsed, dict) else None
            if not isinstance(results, list):
                continue
            by_id = {str(r.get("id")): r for r in results if isinstance(r, dict)}
            with self._lock:
                for k, (it, akey, nkey) in enumerate(batch):
                    r = by_id.get(str(k))
                    if not r:
                        continue
                    aq = str(r.get("address_quality", "")).lower().strip()
                    nq = str(r.get("name_quality", "")).lower().strip()
                    if aq in ADDRESS_QUALITIES and it.get("need_address"):
                        self._cache[akey] = {"quality": aq, "issue": str(r.get("address_issue") or "")[:200],
                                             "english": str(r.get("address_english") or "")[:300]}
                    if nq in NAME_QUALITIES and it.get("need_name"):
                        self._cache[nkey] = {"quality": nq}
                self._save_cache()
        for it, akey, nkey in todo:
            if it.get("need_address") and out[it["id"]]["address"] is None:
                out[it["id"]]["address"] = self._cache.get(akey)
            if it.get("need_name") and out[it["id"]]["name"] is None:
                out[it["id"]]["name"] = self._cache.get(nkey)
        return out

    # ---------- WhatsApp replies ----------
    def classify_reply(self, text: str, flow: str) -> dict | None:
        key = self._key("reply", flow, text)
        if key in self._cache:
            return self._cache[key]
        if not self.available:
            return None
        parsed = self._chat(REPLY_PROMPT.format(flow=flow, flow_desc=FLOW_DESC.get(flow, "")), text)
        if not isinstance(parsed, dict) or parsed.get("intent") not in REPLY_INTENTS:
            return None
        result = {"intent": parsed["intent"], "summary": str(parsed.get("summary") or "")[:120]}
        with self._lock:
            self._cache[key] = result
            self._save_cache()
        return result


_default: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default
    if _default is None:
        _default = LLMClient()
    return _default
