from contextlib import contextmanager
import datetime as dt
import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "paper_trades.db")


class PaperTradingDB:
    """SQLite persistence for simulated (paper) sports bets and automatic settlement."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    match_date TEXT NOT NULL,
                    league TEXT NOT NULL,
                    match_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    market TEXT NOT NULL,
                    odds REAL NOT NULL,
                    model_prob REAL NOT NULL,
                    implied_prob REAL NOT NULL,
                    ev_pct REAL NOT NULL,
                    stake_u REAL NOT NULL,
                    legs_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    profit_u REAL DEFAULT 0.0,
                    settled_at TEXT,
                    result_note TEXT,
                    UNIQUE(strategy, match_key, market)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_alerts (
                    alert_key TEXT PRIMARY KEY,
                    sent_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    k TEXT PRIMARY KEY,
                    v TEXT NOT NULL
                )
                """
            )

    def was_alert_sent(self, alert_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM sent_alerts WHERE alert_key = ?", (alert_key,)).fetchone()
            return row is not None

    def mark_alert_sent(self, alert_key: str) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO sent_alerts (alert_key, sent_at) VALUES (?, ?)", (alert_key, now))

    def get_state(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT v FROM bot_state WHERE k = ?", (key,)).fetchone()
            return row["v"] if row else default

    def set_state(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO bot_state (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                (key, value),
            )

    def get_recent_settled(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status IN ('WON', 'LOST') ORDER BY settled_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_trade(
        self,
        match_date: str,
        league: str,
        match_key: str,
        title: str,
        strategy: str,
        market: str,
        odds: float,
        model_prob: float,
        implied_prob: float,
        ev_pct: float,
        stake_u: float,
        legs: list[dict],
    ) -> bool:
        """Insert a paper trade; returns True if newly inserted, False if duplicate."""
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO trades (
                    created_at, match_date, league, match_key, title,
                    strategy, market, odds, model_prob, implied_prob,
                    ev_pct, stake_u, legs_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
                """,
                (
                    now,
                    match_date,
                    league,
                    match_key,
                    title,
                    strategy,
                    market,
                    round(odds, 3),
                    round(model_prob, 4),
                    round(implied_prob, 4),
                    round(ev_pct, 2),
                    round(stake_u, 2),
                    json.dumps(legs, ensure_ascii=False),
                ),
            )
            return cur.rowcount > 0

    def get_pending(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM trades WHERE status = 'PENDING' ORDER BY match_date, id").fetchall()
        res = []
        for r in rows:
            d = dict(r)
            d["legs"] = json.loads(d["legs_json"])
            res.append(d)
        return res

    def settle_trade(self, trade_id: int, status: str, profit_u: float, note: str) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE trades
                SET status = ?, profit_u = ?, settled_at = ?, result_note = ?
                WHERE id = ?
                """,
                (status, round(profit_u, 3), now, note, trade_id),
            )

    def get_summary(self, initial_bank: float = 100.0) -> dict:
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY match_date, id").fetchall()]

        settled = [r for r in rows if r["status"] in ("WON", "LOST")]
        pending = [r for r in rows if r["status"] == "PENDING"]

        by_strategy: dict[str, dict] = {}
        for r in rows:
            s = r["strategy"]
            if s not in by_strategy:
                by_strategy[s] = {"total": 0, "pending": 0, "won": 0, "lost": 0, "staked": 0.0, "profit": 0.0}
            st = by_strategy[s]
            st["total"] += 1
            if r["status"] == "PENDING":
                st["pending"] += 1
            elif r["status"] == "WON":
                st["won"] += 1
                st["staked"] += r["stake_u"]
                st["profit"] += r["profit_u"]
            elif r["status"] == "LOST":
                st["lost"] += 1
                st["staked"] += r["stake_u"]
                st["profit"] += r["profit_u"]

        total_staked = sum(r["stake_u"] for r in settled)
        total_profit = sum(r["profit_u"] for r in settled)
        roi = (total_profit / total_staked * 100.0) if total_staked > 0 else 0.0

        return {
            "total_trades": len(rows),
            "pending": len(pending),
            "settled": len(settled),
            "won": sum(1 for r in settled if r["status"] == "WON"),
            "lost": sum(1 for r in settled if r["status"] == "LOST"),
            "total_staked_u": round(total_staked, 2),
            "total_profit_u": round(total_profit, 2),
            "roi_pct": round(roi, 2),
            "bankroll_u": round(initial_bank + total_profit, 2),
            "by_strategy": by_strategy,
            "recent": rows[-100:],
        }
