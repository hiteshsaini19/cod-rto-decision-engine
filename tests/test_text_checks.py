import pytest

from rto.assess import assess_orders
from rto.text_checks import check_pincode, is_hinglish, normalize_phone, rule_address, rule_name

from conftest import FakeLLM


@pytest.mark.parametrize("raw,expected", [
    ("9876543210", ("9876543210", True)),
    ("+91 98765 43210", ("9876543210", True)),
    ("09876543210", ("9876543210", True)),
    ("723013610", ("723013610", False)),       # 9 digits (seen in the data)
    ("5876543210", ("5876543210", False)),     # Indian mobiles start 6-9
    (None, (None, False)),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("address,city,quality", [
    ("xyz", "Pune", "unusable"),
    (".", "Pune", "unusable"),
    ("call me", "Chennai", "unusable"),
    ("near station", "Mumbai", "unusable"),
    ("Mumbai", "Mumbai", "unusable"),                       # only the city name
    ("Flat 408, Royal Apartments, Mall Road", "Kolkata", "complete"),
    ("House No. 380, Sector 24, near Water Tank", "Jaipur", "complete"),
    ("399/13, Station Nagar, Opp. Railway Crossing", "Chennai", "complete"),
    ("B-597, Sunrise Society, Gandhi Marg", "Bengaluru", "complete"),
    ("Station chowk se left, Hanuman Mandir ke saamne", "Chennai", "unclear"),   # needs the LLM
    ("gali no 22 ke andar, Petrol Pump ke paas", "Patna", "unclear"),
])
def test_rule_address(address, city, quality):
    assert rule_address(address, city, None, "400001")["quality"] == quality


def test_junk_address_issue_is_specific():
    assert rule_address("xyz", "Pune")["issue"] == 'address is just "xyz"'


def test_pincode_checks():
    assert check_pincode("", "Bihar") == "pincode missing"
    assert check_pincode("400080", "Tamil Nadu") == "pincode 400080 doesn't belong to Tamil Nadu"
    assert check_pincode("600080", "Tamil Nadu") is None
    # a full address with a wrong-state pincode is downgraded
    assert rule_address("Flat 4, Lotus Apartments, MG Road", "Chennai", "Tamil Nadu", "400080")["quality"] == "incomplete"


@pytest.mark.parametrize("name,quality", [
    ("asdf", "fake"), ("qwerty", "fake"), ("Test Order", "fake"), ("xyz xyz", "fake"), ("na", "fake"),
    ("aaa", "fake"), ("Priya Patel", "real"), ("Lakshmi Kulkarni", "real"), ("Rahul", "unclear"),
])
def test_rule_name(name, quality):
    assert rule_name(name)["quality"] == quality


def test_hinglish_detection():
    assert is_hinglish("Station chowk se left, Hanuman Mandir ke saamne")
    assert not is_hinglish("Flat 408, Royal Apartments, Mall Road")


def test_llm_only_called_for_unclear_text():
    llm = FakeLLM()
    assess_orders([{"customer_name": "Priya Patel", "phone": "9876543210",
                    "address": "Flat 1, Om Apartments, MG Road", "city": "Pune", "pincode": "411001"}], llm=llm)
    assert llm.calls == 0


def test_llm_answer_used_and_fallback_without_llm():
    addr = "Station chowk se left, Hanuman Mandir ke saamne"
    order = {"customer_name": "Priya Patel", "phone": "9876543210", "address": addr,
             "city": "Chennai", "state": "Tamil Nadu", "pincode": "600084"}
    llm = FakeLLM(address={addr: {"quality": "incomplete", "issue": "only landmarks", "english": "Opp. temple"}})
    with_llm = assess_orders([order], llm=llm)[0]["address"]
    assert with_llm["source"] == "llm" and with_llm["english"] == "Opp. temple"
    without = assess_orders([order], llm=None)[0]["address"]
    assert without == {"quality": "incomplete", "issue": "no house/flat number, only landmarks", "source": "rules"}


def test_llm_unusable_on_a_real_place_is_downgraded():
    addr = "ph krke aana, Masjid ke paas"
    llm = FakeLLM(address={addr: {"quality": "unusable", "issue": "asks to call", "english": ""}})
    a = assess_orders([{"customer_name": "Riya Das", "phone": "9876543210", "address": addr,
                        "city": "Lucknow", "state": "Uttar Pradesh", "pincode": "226001"}], llm=llm)[0]["address"]
    assert a["quality"] == "incomplete"


def test_llm_failure_falls_back_to_rules():
    llm = FakeLLM()  # knows nothing -> returns None for every text
    a = assess_orders([{"customer_name": "Riya Das", "phone": "9876543210",
                        "address": "gali no 4 ke andar, Big Bazaar ke paas", "city": "Patna",
                        "state": "Bihar", "pincode": "800001"}], llm=llm)[0]["address"]
    assert a["source"] == "rules" and a["quality"] == "incomplete"
