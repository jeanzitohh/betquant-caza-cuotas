from contextlib import contextmanager
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "paper_trades.db")


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"{salt.hex()}:{dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split(":", 1)
        expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 120_000).hex()
        return hmac.compare_digest(expected, dk_hex)
    except Exception:
        return False


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    stake_mode TEXT NOT NULL DEFAULT 'flat',
                    fib_step INTEGER NOT NULL DEFAULT 0,
                    bankroll_base REAL NOT NULL DEFAULT 100.0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    match_date TEXT NOT NULL,
                    league TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    market TEXT NOT NULL,
                    market_name TEXT NOT NULL,
                    odds REAL NOT NULL,
                    stake_u REAL NOT NULL,
                    legs_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    profit_u REAL DEFAULT 0.0,
                    settled_at TEXT,
                    result_note TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_favorites (
                    user_id INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, event_id),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
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

        curve = [round(initial_bank, 2)]
        running = initial_bank
        for r in settled:
            running += r["profit_u"]
            curve.append(round(running, 2))

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
            "equity_curve": curve,
            "recent": rows[-100:],
        }

    # --- Real Server-Side Auth & Per-User Paper Bets (No localStorage) ---

    def register_user(self, username: str, display_name: str, password: str) -> tuple[bool, str, dict | None]:
        uname = username.strip().lower()
        dname = display_name.strip() or uname
        if len(uname) < 3 or len(password) < 6:
            return False, "Usuario mínimo 3 caracteres y contraseña mínimo 6 caracteres.", None
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        pw_hash = _hash_password(password)
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO users (username, display_name, password_hash, stake_mode, fib_step, bankroll_base, created_at)
                    VALUES (?, ?, ?, 'flat', 0, 100.0, ?)
                    """,
                    (uname, dname, pw_hash, now),
                )
                uid = cur.lastrowid
        except sqlite3.IntegrityError:
            return False, "Ese nombre de usuario ya existe.", None
        token = self._create_session(uid)
        return True, token, self.get_user_by_session(token)

    def login_user(self, username: str, password: str) -> tuple[bool, str, dict | None]:
        uname = username.strip().lower()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (uname,)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            return False, "Usuario o contraseña incorrectos.", None
        token = self._create_session(row["id"])
        return True, token, self.get_user_by_session(token)

    def _create_session(self, user_id: int, days_valid: int = 7) -> str:
        token = secrets.token_urlsafe(32)
        now = dt.datetime.now(dt.timezone.utc)
        exp = (now + dt.timedelta(days=days_valid)).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token, user_id, exp, now.isoformat(timespec="seconds")),
            )
        return token

    def get_user_by_session(self, token: str | None) -> dict | None:
        if not token:
            return None
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.username, u.display_name, u.stake_mode, u.fib_step, u.bankroll_base, u.created_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = ? AND s.expires_at > ?
                """,
                (token, now_iso),
            ).fetchone()
        return dict(row) if row else None

    def logout_session(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def update_user_prefs(self, user_id: int, stake_mode: str, bankroll_base: float) -> None:
        mode = "fibonacci" if stake_mode == "fibonacci" else "flat"
        base = max(10.0, min(100000.0, float(bankroll_base)))
        with self._connect() as conn:
            conn.execute("UPDATE users SET stake_mode = ?, bankroll_base = ? WHERE id = ?", (mode, base, user_id))

    @staticmethod
    def fib_stake(step: int, unit: float = 2.0) -> float:
        seq = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55]
        idx = max(0, min(step, len(seq) - 1))
        return round(unit * seq[idx], 2)

    def place_user_bet(
        self,
        user_id: int,
        match_date: str,
        league: str,
        event_id: str,
        title: str,
        market: str,
        market_name: str,
        odds: float,
        legs: list[dict],
        custom_stake: float | None = None,
    ) -> dict:
        with self._connect() as conn:
            u = conn.execute("SELECT stake_mode, fib_step FROM users WHERE id = ?", (user_id,)).fetchone()
            mode = u["stake_mode"] if u else "flat"
            fib_step = u["fib_step"] if u else 0
            stake = round(custom_stake, 2) if custom_stake and custom_stake > 0 else (self.fib_stake(fib_step) if mode == "fibonacci" else 2.0)
            now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            cur = conn.execute(
                """
                INSERT INTO user_bets (
                    user_id, created_at, match_date, league, event_id, title,
                    market, market_name, odds, stake_u, legs_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
                """,
                (user_id, now, match_date, league, event_id, title, market, market_name, round(odds, 3), stake, json.dumps(legs, ensure_ascii=False)),
            )
            return {"bet_id": cur.lastrowid, "stake_u": stake, "stake_mode": mode}

    def get_pending_user_bets(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM user_bets WHERE status = 'PENDING' ORDER BY match_date, id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["legs"] = json.loads(d["legs_json"])
            out.append(d)
        return out

    def settle_user_bet(self, bet_id: int, user_id: int, status: str, profit_u: float, note: str) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "UPDATE user_bets SET status = ?, profit_u = ?, settled_at = ?, result_note = ? WHERE id = ?",
                (status, round(profit_u, 3), now, note, bet_id),
            )
            u = conn.execute("SELECT stake_mode, fib_step FROM users WHERE id = ?", (user_id,)).fetchone()
            if u and u["stake_mode"] == "fibonacci":
                next_step = max(0, u["fib_step"] - 2) if status == "WON" else min(9, u["fib_step"] + 1)
                conn.execute("UPDATE users SET fib_step = ? WHERE id = ?", (next_step, user_id))

    def get_favorites(self, user_id: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT event_id FROM user_favorites WHERE user_id = ?", (user_id,)).fetchall()
        return [r["event_id"] for r in rows]

    def toggle_favorite(self, user_id: int, event_id: str) -> bool:
        """Toggle favorite match for user; returns True if added, False if removed."""
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM user_favorites WHERE user_id = ? AND event_id = ?", (user_id, event_id)
            ).fetchone()
            if exists:
                conn.execute("DELETE FROM user_favorites WHERE user_id = ? AND event_id = ?", (user_id, event_id))
                return False
            now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO user_favorites (user_id, event_id, created_at) VALUES (?, ?, ?)",
                (user_id, event_id, now),
            )
            return True

    def get_user_summary(self, user_id: int) -> dict:
        with self._connect() as conn:
            u = conn.execute("SELECT id, username, display_name, stake_mode, fib_step, bankroll_base FROM users WHERE id = ?", (user_id,)).fetchone()
            rows = [dict(r) for r in conn.execute("SELECT * FROM user_bets WHERE user_id = ? ORDER BY match_date, id", (user_id,)).fetchall()]
        base = u["bankroll_base"] if u else 100.0
        settled = [r for r in rows if r["status"] in ("WON", "LOST")]
        total_staked = sum(r["stake_u"] for r in settled)
        total_profit = sum(r["profit_u"] for r in settled)
        roi = (total_profit / total_staked * 100.0) if total_staked > 0 else 0.0
        curve = [round(base, 2)]
        running = base
        for r in settled:
            running += r["profit_u"]
            curve.append(round(running, 2))
        return {
            "user": dict(u) if u else None,
            "total_trades": len(rows),
            "pending": sum(1 for r in rows if r["status"] == "PENDING"),
            "settled": len(settled),
            "won": sum(1 for r in settled if r["status"] == "WON"),
            "lost": sum(1 for r in settled if r["status"] == "LOST"),
            "total_staked_u": round(total_staked, 2),
            "total_profit_u": round(total_profit, 2),
            "roi_pct": round(roi, 2),
            "bankroll_u": round(base + total_profit, 2),
            "next_fib_stake": self.fib_stake(u["fib_step"]) if u else 2.0,
            "equity_curve": curve,
            "favorites": self.get_favorites(user_id),
            "recent": rows[-100:],
        }
