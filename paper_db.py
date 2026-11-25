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
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    stake_mode TEXT NOT NULL DEFAULT 'flat',
                    fib_step INTEGER NOT NULL DEFAULT 0,
                    bankroll_base REAL NOT NULL DEFAULT 100.0,
                    created_at TEXT NOT NULL
                )
                """
            )
            try:
                conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

            # Ensure juanmanuelton7@gmail.com has full super-admin privileges
            conn.execute("UPDATE users SET is_admin = 1 WHERE username = 'juanmanuelton7@gmail.com'")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS invitations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT NOT NULL UNIQUE,
                    email TEXT,
                    role TEXT NOT NULL DEFAULT 'member',
                    max_uses INTEGER NOT NULL DEFAULT 1,
                    uses_count INTEGER NOT NULL DEFAULT 0,
                    created_by INTEGER,
                    expires_at TEXT,
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS post_match_learnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    league TEXT NOT NULL,
                    match_date TEXT NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    home_score INTEGER NOT NULL,
                    away_score INTEGER NOT NULL,
                    forecast_market TEXT NOT NULL,
                    forecast_odds REAL NOT NULL,
                    forecast_prob REAL NOT NULL,
                    verdict TEXT NOT NULL,
                    profit_u REAL NOT NULL,
                    verif_analysis TEXT NOT NULL,
                    learning_note TEXT NOT NULL,
                    stats_json TEXT NOT NULL,
                    body_html TEXT NOT NULL,
                    card_webp TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(event_id, forecast_market)
                )
                """
            )

    def record_post_match_learning(self, an: dict) -> bool:
        """Insert a post-match learning analysis record. Returns True if inserted, False if duplicate."""
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        stats_json = json.dumps(an.get("stats") or {}, ensure_ascii=False)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO post_match_learnings (
                    event_id, league, match_date, home_team, away_team,
                    home_score, away_score, forecast_market, forecast_odds, forecast_prob,
                    verdict, profit_u, verif_analysis, learning_note, stats_json,
                    body_html, card_webp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(an.get("event_id", "")),
                    str(an.get("league", "")),
                    str(an.get("match_date", now[:10])),
                    str(an.get("home_team", "")),
                    str(an.get("away_team", "")),
                    int(an.get("home_score", 0)),
                    int(an.get("away_score", 0)),
                    str(an.get("market", "")),
                    float(an.get("odds", 1.50)),
                    float(an.get("prob_pct", 65.0)),
                    str(an.get("status", "WON")),
                    float(an.get("profit_u", 0.0)),
                    str(an.get("verif_analysis", "")),
                    str(an.get("learning_note", "")),
                    stats_json,
                    str(an.get("body_html", "")),
                    str(an.get("card_webp", "")),
                    now,
                ),
            )
            return cur.rowcount > 0

    def get_recent_post_match_learnings(self, limit: int = 15) -> list[dict]:
        """Fetch the most recent post-match learning reports."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM post_match_learnings ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

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
        won_cnt = sum(1 for r in settled if r["status"] == "WON")
        lost_cnt = sum(1 for r in settled if r["status"] == "LOST")
        bot_acc = round((won_cnt / len(settled)) * 100.0, 1) if settled else 0.0

        curve = [round(initial_bank, 2)]
        running = initial_bank
        for r in settled:
            running += r["profit_u"]
            curve.append(round(running, 2))

        daily_stats = self.get_daily_effectiveness(days=14)
        calibration = self.get_market_calibration()

        return {
            "total_trades": len(rows),
            "pending": len(pending),
            "settled": len(settled),
            "won": won_cnt,
            "lost": lost_cnt,
            "accuracy_pct": bot_acc,
            "total_staked_u": round(total_staked, 2),
            "total_profit_u": round(total_profit, 2),
            "roi_pct": round(roi, 2),
            "bankroll_u": round(initial_bank + total_profit, 2),
            "by_strategy": by_strategy,
            "daily_stats": daily_stats,
            "calibration": calibration,
            "equity_curve": curve,
            "recent": rows[-100:],
        }

    def get_daily_effectiveness(self, days: int = 14) -> list[dict]:
        """Measure daily prediction accuracy (e.g. 7 of 10 = 70%) by match_date."""
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY match_date, id").fetchall()]

        by_day: dict[str, dict] = {}
        for r in rows:
            d = str(r["match_date"])[:10]
            if d not in by_day:
                by_day[d] = {"date": d, "total": 0, "settled": 0, "won": 0, "lost": 0, "pending": 0, "pending_eids": set(), "staked_u": 0.0, "profit_u": 0.0}
            st = by_day[d]
            st["total"] += 1
            if r["status"] == "PENDING":
                st["pending"] += 1
                for leg in json.loads(r["legs_json"] or "[]"):
                    st["pending_eids"].add(str(leg.get("event_id") or r["match_key"]))
            elif r["status"] in ("WON", "LOST"):
                st["settled"] += 1
                st["staked_u"] += float(r["stake_u"])
                st["profit_u"] += float(r["profit_u"])
                if r["status"] == "WON":
                    st["won"] += 1
                else:
                    st["lost"] += 1

        out = []
        for d in sorted(by_day.keys(), reverse=True)[:days]:
            st = by_day[d]
            eids = st.pop("pending_eids")
            st["pending_matches"] = len(eids) if eids else st["pending"]
            st["accuracy_pct"] = round((st["won"] / st["settled"]) * 100.0, 1) if st["settled"] > 0 else None
            st["roi_pct"] = round((st["profit_u"] / st["staked_u"]) * 100.0, 1) if st["staked_u"] > 0 else 0.0
            st["staked_u"] = round(st["staked_u"], 2)
            st["profit_u"] = round(st["profit_u"], 2)
            out.append(st)
        return out

    def get_market_calibration(self) -> dict[str, dict]:
        """Auto-calibrate each market type from settled paper-trade outcomes."""
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM trades WHERE status IN ('WON', 'LOST') ORDER BY id").fetchall()]

        stats: dict[str, dict] = {}
        for r in rows:
            legs = json.loads(r["legs_json"]) if r.get("legs_json") else [{"market": r["market"]}]
            won = r["status"] == "WON"
            for leg in legs:
                mk = str(leg.get("market") or r["market"])
                st = stats.setdefault(mk, {"settled": 0, "won": 0, "lost": 0, "prob_sum": 0.0, "profit_u": 0.0})
                st["settled"] += 1
                st["won"] += int(won)
                st["lost"] += int(not won)
                st["prob_sum"] += float(r["model_prob"])
                st["profit_u"] += float(r["profit_u"])

        calibration: dict[str, dict] = {}
        for mk, st in stats.items():
            n = st["settled"]
            win_rate = st["won"] / n if n > 0 else 0.0
            avg_prob = st["prob_sum"] / n if n > 0 else 0.5
            # Empirical Bayes adjustment toward actual settled accuracy
            shrunk = (st["won"] + 5.0 * avg_prob) / (n + 5.0)
            bias = round(shrunk - avg_prob, 4)
            blocked = n >= 5 and win_rate < 0.52 and st["profit_u"] < -3.0
            label = "Bloqueado temporalmente" if blocked else ("Ajuste estricto" if bias < -0.04 else ("Rendimiento óptimo" if win_rate >= 0.68 and n >= 3 else "Calibrando"))
            calibration[mk] = {
                "settled": n,
                "won": st["won"],
                "lost": st["lost"],
                "win_rate_pct": round(win_rate * 100.0, 1),
                "bias": bias,
                "blocked": blocked,
                "profit_u": round(st["profit_u"], 2),
                "status": label,
            }
        return calibration

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
                SELECT u.id, u.username, u.display_name, COALESCE(u.is_admin, 0) AS is_admin,
                       u.stake_mode, u.fib_step, u.bankroll_base, u.created_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = ? AND s.expires_at > ?
                """,
                (token, now_iso),
            ).fetchone()
        return dict(row) if row else None

    # --- Super Admin User Management & Invitation System ---

    def list_all_users(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT u.id, u.username, u.display_name, COALESCE(u.is_admin, 0) AS is_admin,
                       u.stake_mode, u.bankroll_base, u.created_at,
                       COUNT(ub.id) AS total_bets,
                       SUM(CASE WHEN ub.status = 'PENDING' THEN 1 ELSE 0 END) AS pending_bets,
                       COALESCE(SUM(ub.profit_u), 0.0) AS net_profit_u
                FROM users u
                LEFT JOIN user_bets ub ON ub.user_id = u.id
                GROUP BY u.id
                ORDER BY u.created_at DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def admin_create_user(
        self, username: str, display_name: str, password: str, is_admin: bool = False, bankroll_base: float = 100.0
    ) -> tuple[bool, str, dict | None]:
        uname = username.strip().lower()
        dname = display_name.strip() or uname
        if len(uname) < 3 or len(password) < 6:
            return False, "Usuario mínimo 3 caracteres y contraseña mínimo 6.", None
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        pw_hash = _hash_password(password)
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO users (username, display_name, password_hash, is_admin, stake_mode, fib_step, bankroll_base, created_at)
                    VALUES (?, ?, ?, ?, 'flat', 0, ?, ?)
                    """,
                    (uname, dname, pw_hash, 1 if is_admin else 0, max(10.0, float(bankroll_base)), now),
                )
                uid = cur.lastrowid
                row = conn.execute("SELECT id, username, display_name, is_admin, bankroll_base, created_at FROM users WHERE id = ?", (uid,)).fetchone()
            return True, "Usuario creado exitosamente.", dict(row) if row else None
        except sqlite3.IntegrityError:
            return False, "El nombre de usuario o correo ya existe.", None

    def admin_update_user(
        self, user_id: int, display_name: str, is_admin: bool, bankroll_base: float, new_password: str | None = None
    ) -> tuple[bool, str]:
        with self._connect() as conn:
            if new_password and len(new_password.strip()) >= 6:
                pw_hash = _hash_password(new_password.strip())
                conn.execute(
                    """
                    UPDATE users
                    SET display_name = ?, is_admin = ?, bankroll_base = ?, password_hash = ?
                    WHERE id = ?
                    """,
                    (display_name.strip(), 1 if is_admin else 0, max(10.0, float(bankroll_base)), pw_hash, user_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET display_name = ?, is_admin = ?, bankroll_base = ?
                    WHERE id = ?
                    """,
                    (display_name.strip(), 1 if is_admin else 0, max(10.0, float(bankroll_base)), user_id),
                )
        return True, "Usuario actualizado correctamente."

    def admin_delete_user(self, user_id: int) -> tuple[bool, str]:
        with self._connect() as conn:
            # Protect juanmanuelton7@gmail.com
            u = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
            if u and u["username"] == "juanmanuelton7@gmail.com":
                return False, "No se puede eliminar la cuenta del Super Administrador principal."
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_bets WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_favorites WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return True, "Usuario eliminado correctamente."

    def create_invitation(
        self, created_by: int | None, email: str | None = None, role: str = "member", max_uses: int = 1, days_valid: int = 7
    ) -> dict:
        token = secrets.token_urlsafe(16)
        now = dt.datetime.now(dt.timezone.utc)
        exp = (now + dt.timedelta(days=days_valid)).isoformat(timespec="seconds")
        clean_email = email.strip().lower() if email else None
        clean_role = "admin" if role == "admin" else "member"
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO invitations (token, email, role, max_uses, uses_count, created_by, expires_at, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (token, clean_email, clean_role, max(1, int(max_uses)), created_by, exp, now.isoformat(timespec="seconds")),
            )
            inv_id = cur.lastrowid
            row = conn.execute("SELECT * FROM invitations WHERE id = ?", (inv_id,)).fetchone()
        return dict(row)

    def list_invitations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM invitations ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_invitation(self, invite_id: int) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM invitations WHERE id = ?", (invite_id,))
        return True

    def validate_invitation(self, token: str) -> tuple[bool, str, dict | None]:
        if not token:
            return False, "Token de invitación requerido.", None
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            inv = conn.execute("SELECT * FROM invitations WHERE token = ?", (token.strip(),)).fetchone()
        if not inv:
            return False, "Invitación no válida o no encontrada.", None
        if inv["expires_at"] and inv["expires_at"] < now_iso:
            return False, "Esta invitación ha expirado.", None
        if inv["uses_count"] >= inv["max_uses"]:
            return False, "Esta invitación ya alcanzó el número máximo de usos.", None
        return True, "Invitación válida.", dict(inv)

    def consume_invitation(self, token: str) -> bool:
        with self._connect() as conn:
            conn.execute("UPDATE invitations SET uses_count = uses_count + 1 WHERE token = ?", (token.strip(),))
        return True

    def logout_session(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def update_user_prefs(self, user_id: int, stake_mode: str, bankroll_base: float) -> None:
        mode = stake_mode if stake_mode in ("flat", "fibonacci", "fibonacci_3") else "flat"
        base = max(10.0, min(100000.0, float(bankroll_base)))
        with self._connect() as conn:
            conn.execute("UPDATE users SET stake_mode = ?, bankroll_base = ? WHERE id = ?", (mode, base, user_id))

    @staticmethod
    def fib_stake(step: int, unit: float = 2.0, stake_mode: str = "fibonacci") -> float:
        seq = (1, 2, 3) if stake_mode == "fibonacci_3" else (1, 2, 3, 5, 8)
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
            stake = (
                round(custom_stake, 2)
                if custom_stake and custom_stake > 0
                else (self.fib_stake(fib_step, stake_mode=mode) if mode in ("fibonacci", "fibonacci_3") else 2.0)
            )
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
            if u and u["stake_mode"] in ("fibonacci", "fibonacci_3"):
                cur_step = int(u["fib_step"])
                if status == "WON":
                    next_step = 0
                elif u["stake_mode"] == "fibonacci_3":
                    next_step = 0 if cur_step >= 2 else cur_step + 1
                else:
                    next_step = min(4, cur_step + 1)
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
            "next_fib_stake": self.fib_stake(u["fib_step"], stake_mode=u["stake_mode"]) if u else 2.0,
            "equity_curve": curve,
            "favorites": self.get_favorites(user_id),
            "recent": rows[-100:],
        }
