import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Tests never touch the real database, rules file or the paid/free API.
_TMP = Path(tempfile.mkdtemp(prefix="rto_tests_"))
os.environ["RTO_DB_PATH"] = str(_TMP / "test.db")
os.environ["RTO_RULES_PATH"] = str(_TMP / "rules.yaml")
os.environ["OPENROUTER_API_KEY"] = ""
shutil.copy(ROOT / "config" / "rules.yaml", _TMP / "rules.yaml")

import pytest  # noqa: E402

from rto.config import load_rules  # noqa: E402
from rto.model import load_model  # noqa: E402


class FakeLLM:
    """Stands in for OpenRouter: answers from fixed tables, counts calls."""

    def __init__(self, address=None, name=None, replies=None):
        self.address, self.name, self.replies = address or {}, name or {}, replies or {}
        self.calls = 0
        self.available = True

    def check_texts(self, items, cache_only=False):
        self.calls += 1
        out = {}
        for it in items:
            out[it["id"]] = {
                "address": self.address.get(it["address"]) if it.get("need_address") else None,
                "name": self.name.get(it["name"]) if it.get("need_name") else None,
            }
        return out

    def classify_reply(self, text, flow):
        self.calls += 1
        return self.replies.get(text)


@pytest.fixture
def rules():
    return load_rules()


@pytest.fixture
def model():
    return load_model()


@pytest.fixture
def good_order():
    return dict(order_id="T-GOOD", order_datetime="2026-10-30 14:00", customer_name="Neha Mishra",
                phone="9876543210", address="Flat 408, Royal Apartments, Mall Road", city="Mumbai",
                state="Maharashtra", pincode="400050", order_value=599, items="Satin Bonnet", num_items=1,
                customer_prior_orders=3, customer_prior_rto=0, utm_source="direct")


@pytest.fixture
def tmp_rules_file():
    """Path of the test copy of rules.yaml, restored after each test that edits it."""
    path = Path(os.environ["RTO_RULES_PATH"])
    backup = path.read_text(encoding="utf-8")
    yield path
    path.write_text(backup, encoding="utf-8")
