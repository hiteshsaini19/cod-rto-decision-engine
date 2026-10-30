"""Cleans the raw orders CSV into something we can learn from.

Problems found in orders_sample.csv (see docs/DATA_FINDINGS.md):
- final_status spelt several ways ("RTO", "Rto", "RTO ", "delivered") + one IN_TRANSIT
- 30 rows are exact duplicates of another row
- phones in mixed formats ("+91 61348 94572") and some only 9 digits
- missing pincode / city, Rs 0 orders
"""
from __future__ import annotations

import json

import pandas as pd

from .config import CLEAN_CSV, DATA_DIR, RAW_CSV
from .text_checks import normalize_phone


def load_raw(path=RAW_CSV) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"pincode": str, "phone": str})


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = raw.copy()
    report = {"raw_rows": len(df)}

    df["final_status"] = df["final_status"].astype(str).str.strip().str.upper()
    report["status_values_after_fix"] = df["final_status"].value_counts().to_dict()
    unfinished = ~df["final_status"].isin(["RTO", "DELIVERED"])
    report["dropped_not_final"] = int(unfinished.sum())
    df = df[~unfinished]

    before = len(df)
    df = df.drop_duplicates()
    report["dropped_exact_duplicates"] = before - len(df)
    before = len(df)
    df = df.drop_duplicates(subset="order_id", keep="first")
    report["dropped_duplicate_order_ids"] = before - len(df)

    df["order_datetime"] = pd.to_datetime(df["order_datetime"])
    phones = df["phone"].map(normalize_phone)
    df["phone_clean"] = phones.map(lambda p: p[0])
    df["phone_valid"] = phones.map(lambda p: p[1])
    report["invalid_phones"] = int((~df["phone_valid"]).sum())
    report["missing_pincode"] = int(df["pincode"].isna().sum())
    report["missing_city"] = int(df["city"].isna().sum())
    report["zero_value_orders"] = int((df["order_value"] <= 0).sum())

    df["rto"] = (df["final_status"] == "RTO").astype(int)
    df = df.sort_values("order_datetime").reset_index(drop=True)
    report["clean_rows"] = len(df)
    report["rto_rate"] = round(float(df["rto"].mean()), 4)
    return df, report


def load_clean() -> pd.DataFrame:
    if not CLEAN_CSV.exists():
        build_clean()
    df = pd.read_csv(CLEAN_CSV, dtype={"pincode": str, "phone": str, "phone_clean": str})
    df["order_datetime"] = pd.to_datetime(df["order_datetime"])
    return df


def build_clean() -> dict:
    df, report = clean(load_raw())
    df.to_csv(CLEAN_CSV, index=False)
    with open(DATA_DIR / "cleaning_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return report
