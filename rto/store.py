"""Tiny SQLite store for processed orders and their WhatsApp conversations."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .config import DB_PATH
from .whatsapp import OUTCOME_TO_STATUS

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id     TEXT PRIMARY KEY,
    order_date   TEXT NOT NULL,
    order_json   TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    action       TEXT NOT NULL,
    risk_pct     REAL NOT NULL,
    status       TEXT NOT NULL,
    demo         INTEGER NOT NULL DEFAULT 0,
    actual_outcome TEXT,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
CREATE TABLE IF NOT EXISTS conversations (
    order_id   TEXT PRIMARY KEY,
    conv_json  TEXT NOT NULL,
    status     TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path=DB_PATH):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(sep=" ", timespec="seconds")

    # ---------- orders ----------
    def save_order(self, order: dict, decision: dict, conv: dict | None, demo: bool = False,
                   actual_outcome: str | None = None) -> None:
        status = self.status_for(decision, conv)
        o = {k: (v.isoformat(sep=" ") if isinstance(v, datetime) else v) for k, v in order.items()
             if not k.startswith("_")}
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?)",
                (decision["order_id"], decision["order_datetime"][:10], json.dumps(o, ensure_ascii=False),
                 json.dumps(decision, ensure_ascii=False), decision["action"], decision["risk_pct"], status,
                 int(demo), actual_outcome, self._now()),
            )
            if conv is not None:
                c.execute("INSERT OR REPLACE INTO conversations VALUES (?,?,?,?)",
                          (conv["order_id"], json.dumps(conv, ensure_ascii=False), conv["status"], self._now()))

    @staticmethod
    def status_for(decision: dict, conv: dict | None) -> str:
        if decision["action"] == "ship":
            return "ship_cod"
        if conv is None:
            return "manual_review"     # hold that ops must handle by hand (bad phone, Rs 0 order)
        if conv["status"] != "closed":
            return "waiting_on_customer"
        return OUTCOME_TO_STATUS.get(conv["outcome"], "waiting_on_customer")

    def get_order(self, order_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
            cv = c.execute("SELECT conv_json FROM conversations WHERE order_id=?", (order_id,)).fetchone()
        if not r:
            return None
        return self._row(r, json.loads(cv["conv_json"]) if cv else None)

    @staticmethod
    def _row(r, conv=None) -> dict:
        return {"order_id": r["order_id"], "order_date": r["order_date"], "order": json.loads(r["order_json"]),
                "decision": json.loads(r["decision_json"]), "action": r["action"], "risk_pct": r["risk_pct"],
                "status": r["status"], "demo": bool(r["demo"]), "actual_outcome": r["actual_outcome"],
                "conversation": conv}

    def list_orders(self, date: str | None = None, limit: int = 500, with_conversations: bool = False) -> list[dict]:
        q, args = "SELECT * FROM orders", []
        if date:
            q += " WHERE order_date=?"
            args.append(date)
        q += " ORDER BY json_extract(decision_json, '$.order_datetime') DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
            convs = {}
            if with_conversations and rows:
                ids = [r["order_id"] for r in rows]
                for i in range(0, len(ids), 500):
                    chunk = ids[i:i + 500]
                    for cv in c.execute(f"SELECT order_id, conv_json FROM conversations WHERE order_id IN "
                                        f"({','.join('?' * len(chunk))})", chunk):
                        convs[cv["order_id"]] = json.loads(cv["conv_json"])
        return [self._row(r, convs.get(r["order_id"])) for r in rows]

    def recent_orders(self, since: str) -> list[dict]:
        """Orders placed since `since` (for duplicate checks)."""
        with self._conn() as c:
            rows = c.execute("SELECT order_json, decision_json FROM orders WHERE order_date>=?", (since[:10],)).fetchall()
        out = []
        for r in rows:
            o, d = json.loads(r["order_json"]), json.loads(r["decision_json"])
            out.append({"order_id": d["order_id"], "order_datetime": d["order_datetime"],
                        "phone": d["checks"]["phone"]["number"]})
        return out

    def dates(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT order_date, COUNT(*) n FROM orders GROUP BY order_date ORDER BY order_date DESC").fetchall()
        return [{"date": r["order_date"], "orders": r["n"]} for r in rows]

    def clear(self, demo_only: bool = False) -> int:
        with self._conn() as c:
            if demo_only:
                ids = [r[0] for r in c.execute("SELECT order_id FROM orders WHERE demo=1")]
                c.executemany("DELETE FROM conversations WHERE order_id=?", [(i,) for i in ids])
                c.execute("DELETE FROM orders WHERE demo=1")
                return len(ids)
            n = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            c.execute("DELETE FROM conversations")
            c.execute("DELETE FROM orders")
            return n

    # ---------- conversations ----------
    def get_conversation(self, order_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT conv_json FROM conversations WHERE order_id=?", (order_id,)).fetchone()
        return json.loads(r["conv_json"]) if r else None

    def save_conversation(self, conv: dict) -> str:
        """Save the conversation and update the order's status. Returns the new order status."""
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO conversations VALUES (?,?,?,?)",
                      (conv["order_id"], json.dumps(conv, ensure_ascii=False), conv["status"], self._now()))
            r = c.execute("SELECT decision_json FROM orders WHERE order_id=?", (conv["order_id"],)).fetchone()
            status = self.status_for(json.loads(r["decision_json"]), conv) if r else "unknown"
            c.execute("UPDATE orders SET status=?, updated_at=? WHERE order_id=?",
                      (status, self._now(), conv["order_id"]))
        return status

    def list_conversations(self, open_only: bool = False, limit: int = 200) -> list[dict]:
        q = ("SELECT c.conv_json, o.order_date FROM conversations c JOIN orders o USING(order_id)"
             + (" WHERE c.status != 'closed'" if open_only else "")
             + " ORDER BY c.updated_at DESC, o.order_date DESC LIMIT ?")
        with self._conn() as c:
            rows = c.execute(q, (limit,)).fetchall()
        out = []
        for r in rows:
            cv = json.loads(r["conv_json"])
            out.append({k: cv.get(k) for k in ("order_id", "flow", "status", "outcome", "language", "risk_pct",
                                               "clock", "deadline", "needs_human")}
                       | {"customer_name": cv["order"].get("customer_name"), "order_date": r["order_date"],
                          "messages": len(cv["messages"])})
        return out
