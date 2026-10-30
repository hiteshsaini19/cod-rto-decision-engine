"""The risk score: what is the chance this COD order comes back?

Plain logistic regression on a handful of yes/no facts about the order, learnt from
past orders. Each fact adds or removes "points"; points -> risk %. Simple maths,
so every decision can say exactly which facts pushed the risk up or down.

The learnt weights live in config/risk_model.json (rebuild: scripts/build_model.py).
"""
from __future__ import annotations

import json
import math
from datetime import datetime

import numpy as np
import pandas as pd

from .assess import assess_orders
from .config import MODEL_PATH

AREA_SMOOTHING = 10      # pull small cities towards their state's rate
HIGH_VALUE_RS = 1500     # orders >= this were riskier in the data (38% vs 20-28%)
POINTS_PER_LOGIT = 10    # 1 point = 0.1 on the log-odds scale (only for display)

# feature -> plain-English label (area_risk gets a dynamic label)
FEATURES = {
    "addr_unusable": "Address can't be delivered",
    "addr_incomplete": "Address has no house/flat number",
    "name_flag": "Name looks fake",
    "phone_invalid": "Phone number is invalid",
    "first_order": "First order from this customer",
    "past_rto_1": "Customer refused 1 earlier COD order",
    "past_rto_2plus": "Customer refused 2+ earlier COD orders",
    "high_value": f"High order value (Rs {HIGH_VALUE_RS:,}+)",
    "area_risk": "Delivery area's past return rate",
    "meta_ads": "Came from a Meta (Facebook/Instagram) ad",
}


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


# ---------------------------------------------------------------- area rates
def area_counts(df: pd.DataFrame) -> dict:
    """Raw order / RTO counts per city and state (saved in the model file)."""
    city = df.groupby("city", dropna=True).agg(n=("rto", "size"), rto=("rto", "sum"), state=("state", "first"))
    state = df.groupby("state").agg(n=("rto", "size"), rto=("rto", "sum"))
    return {
        "overall": {"n": int(len(df)), "rto": int(df["rto"].sum())},
        "state": {s: {"n": int(r.n), "rto": int(r.rto)} for s, r in state.iterrows()},
        "city": {c: {"n": int(r.n), "rto": int(r.rto), "state": r.state} for c, r in city.iterrows()},
    }


def area_rate(areas: dict, city, state, min_city_orders: int, exclude_rto: int | None = None) -> dict:
    """Smoothed RTO rate for a city (falls back to state, then overall).

    exclude_rto: for training only - removes the order's own outcome (no peeking).
    """
    ov = areas["overall"]
    drop_n = 1 if exclude_rto is not None else 0
    drop_r = exclude_rto or 0
    overall = (ov["rto"] - drop_r) / max(ov["n"] - drop_n, 1)

    st = areas["state"].get(state) if isinstance(state, str) else None
    if st and st["n"] - drop_n > 0:
        state_rate = (st["rto"] - drop_r + AREA_SMOOTHING * overall) / (st["n"] - drop_n + AREA_SMOOTHING)
        st_n = st["n"] - drop_n
    else:
        state_rate, st_n = overall, 0

    ct = areas["city"].get(city) if isinstance(city, str) else None
    if ct and ct["n"] - drop_n >= min_city_orders:
        rate = (ct["rto"] - drop_r + AREA_SMOOTHING * state_rate) / (ct["n"] - drop_n + AREA_SMOOTHING)
        return {"rate": rate, "level": "city", "name": city, "orders": ct["n"] - drop_n, "overall": overall}
    if st_n:
        return {"rate": state_rate, "level": "state", "name": state, "orders": st_n, "overall": overall}
    return {"rate": overall, "level": "overall", "name": "all areas", "orders": ov["n"], "overall": overall}


# ---------------------------------------------------------------- features
def make_features(order: dict, assessment: dict, area: dict) -> dict:
    prior_rto = int(order.get("customer_prior_rto") or 0)
    return {
        "addr_unusable": float(assessment["address"]["quality"] == "unusable"),
        "addr_incomplete": float(assessment["address"]["quality"] == "incomplete"),
        "name_flag": float(assessment["name"]["quality"] in ("fake", "suspicious")),
        "phone_invalid": float(not assessment["phone"]["valid"]),
        "first_order": float(int(order.get("customer_prior_orders") or 0) == 0),
        "past_rto_1": float(prior_rto == 1),
        "past_rto_2plus": float(prior_rto >= 2),
        "high_value": float(float(order.get("order_value") or 0) >= HIGH_VALUE_RS),
        "area_risk": _logit(area["rate"]) - _logit(area["overall"]),
        "meta_ads": float(str(order.get("utm_source") or "").lower() == "meta_ads"),
    }


# ---------------------------------------------------------------- fitting
def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> np.ndarray:
    """Newton's method with a small L2 penalty (intercept not penalised). Returns [b0, b1..]."""
    Xb = np.hstack([np.ones((len(X), 1)), X])
    w = np.zeros(Xb.shape[1])
    pen = np.full(Xb.shape[1], l2)
    pen[0] = 0.0
    for _ in range(iters):
        p = _sigmoid(Xb @ w)
        grad = Xb.T @ (p - y) + pen * w
        H = (Xb * (p * (1 - p))[:, None]).T @ Xb + np.diag(pen)
        step = np.linalg.solve(H, grad)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w


def auc(y, p) -> float:
    """Chance a random refused order scores higher than a random delivered one."""
    y, p = np.asarray(y), np.asarray(p)
    ranks = pd.Series(p).rank().to_numpy()
    n1, n0 = y.sum(), len(y) - y.sum()
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def feature_frame(df: pd.DataFrame, assessments: list[dict], areas: dict, min_city_orders: int,
                  leave_one_out: bool) -> pd.DataFrame:
    rows = []
    for o, a in zip(df.to_dict("records"), assessments):
        area = area_rate(areas, o.get("city"), o.get("state"), min_city_orders,
                         exclude_rto=int(o["rto"]) if leave_one_out else None)
        rows.append(make_features(o, a, area))
    return pd.DataFrame(rows, columns=list(FEATURES))


def build_model(df: pd.DataFrame, train_until: str, min_city_orders: int, llm=None) -> dict:
    """Learn weights on orders before `train_until`; report how well it ranks later orders."""
    df = df[df["order_value"] > 0].reset_index(drop=True)
    assessments = assess_orders(df.to_dict("records"), llm=llm, cache_only=True)
    train_mask = (df["order_datetime"] < pd.Timestamp(train_until)).to_numpy()
    train = df[train_mask]
    areas = area_counts(train)

    X_train = feature_frame(train, [a for a, m in zip(assessments, train_mask) if m], areas,
                            min_city_orders, leave_one_out=True)
    w = fit_logistic(X_train.to_numpy(), train["rto"].to_numpy())
    model = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "trained_on": {"from": str(train["order_datetime"].min().date()),
                       "until": str(train["order_datetime"].max().date()),
                       "orders": int(len(train)), "rto_rate": round(float(train["rto"].mean()), 4)},
        "intercept": float(w[0]),
        "weights": {f: float(v) for f, v in zip(FEATURES, w[1:])},
        "labels": FEATURES,
        "high_value_rs": HIGH_VALUE_RS,
        "areas": areas,
    }

    test = df[~train_mask]
    if len(test):
        X_test = feature_frame(test, [a for a, m in zip(assessments, train_mask) if not m], areas,
                               min_city_orders, leave_one_out=False)
        p = _sigmoid(model["intercept"] + X_test.to_numpy() @ np.array(list(model["weights"].values())))
        bands = pd.cut(p, [0, .15, .25, .35, .5, .7, 1.0])
        calib = pd.DataFrame({"band": bands, "p": p, "y": test["rto"].to_numpy()}).groupby("band", observed=True) \
            .agg(orders=("y", "size"), predicted=("p", "mean"), actual=("y", "mean"))
        model["tested_on"] = {
            "from": str(test["order_datetime"].min().date()), "until": str(test["order_datetime"].max().date()),
            "orders": int(len(test)), "rto_rate": round(float(test["rto"].mean()), 4),
            "auc": round(auc(test["rto"].to_numpy(), p), 3),
            "calibration": [{"band": str(b), "orders": int(r.orders), "predicted": round(float(r.predicted), 3),
                             "actual": round(float(r.actual), 3)} for b, r in calib.iterrows()],
        }
    return model


def save_model(model: dict, path=MODEL_PATH) -> None:
    path.write_text(json.dumps(model, indent=1, ensure_ascii=False), encoding="utf-8")


_model_cache: dict = {"mtime": None, "model": None}


def load_model(path=MODEL_PATH) -> dict:
    mtime = path.stat().st_mtime
    if _model_cache["mtime"] != mtime:
        _model_cache.update(mtime=mtime, model=json.loads(path.read_text(encoding="utf-8")))
    return _model_cache["model"]


# ---------------------------------------------------------------- scoring
def score(order: dict, assessment: dict, model: dict, min_city_orders: int) -> dict:
    """Risk % plus the facts that moved it, biggest first."""
    area = area_rate(model["areas"], order.get("city"), order.get("state"), min_city_orders)
    feats = make_features(order, assessment, area)
    z = model["intercept"]
    factors = []
    for f, x in feats.items():
        contrib = model["weights"][f] * x
        z += contrib
        if abs(contrib) < 0.05:
            continue
        label = model["labels"][f]
        if f == "area_risk":
            where = area["name"] if area["level"] != "overall" else "This area"
            label = (f"{where}: {area['rate']:.0%} of past COD orders came back "
                     f"(average {area['overall']:.0%})")
        factors.append({"feature": f, "label": label, "points": round(contrib * POINTS_PER_LOGIT),
                        "effect": "raises risk" if contrib > 0 else "lowers risk"})
    if feats["first_order"] == 0 and feats["past_rto_1"] == 0 and feats["past_rto_2plus"] == 0:
        factors.append({"feature": "repeat_clean", "label": "Repeat customer with no past refusals",
                        "points": round(-model["weights"]["first_order"] * POINTS_PER_LOGIT),
                        "effect": "lowers risk"})
    factors.sort(key=lambda x: -abs(x["points"]))
    return {"risk": float(_sigmoid(z)), "factors": factors, "features": feats, "area": area,
            "base_points": round(model["intercept"] * POINTS_PER_LOGIT)}
