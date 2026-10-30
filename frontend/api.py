"""Small helper the Streamlit pages use to talk to the backend."""
from __future__ import annotations

import os
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

ACTION_STYLE = {   # label, colour for the action badge, emoji
    "ship": ("Ship as-is", "green", "✅"),
    "nudge": ("Nudge to prepaid", "blue", "💳"),
    "confirm": ("Ship after confirmation", "orange", "💬"),
    "hold": ("Hold / cancel", "red", "⛔"),
}
STATUS_LABEL = {
    "ship_cod": "Shipping (COD)", "ship_prepaid": "Shipping (prepaid)", "cancelled": "Cancelled",
    "waiting_on_customer": "Waiting for customer", "with_team": "With support team",
    "manual_review": "Ops to check by hand",
}


def call(method: str, path: str, timeout: float = 120, **kwargs):
    """Call the backend; show a friendly error (and stop the page) if it's not running."""
    try:
        r = requests.request(method, f"{BACKEND}{path}", timeout=timeout, **kwargs)
    except requests.ConnectionError:
        st.error(f"Can't reach the backend at {BACKEND}. Start it first:\n\n"
                 "`uvicorn backend.main:app --port 8000`")
        st.stop()
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        return None, f"{r.status_code}: {detail}"
    return r.json(), None


def get(path, **params):
    data, err = call("GET", path, params=params)
    if err:
        st.error(err)
        st.stop()
    return data


def rs(x) -> str:
    """Rs with Indian-style sign: +Rs 1,234 / -Rs 1,234"""
    x = float(x or 0)
    sign = "-" if x < 0 else ""
    return f"{sign}₹{abs(x):,.0f}"


def badge(action: str) -> str:
    label, colour, emoji = ACTION_STYLE[action]
    return f":{colour}-background[{emoji} **{label}**]"
