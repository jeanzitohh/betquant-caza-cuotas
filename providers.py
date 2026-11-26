import concurrent.futures
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

from quant_math import american_to_decimal, devig_3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

LEAGUE_LABELS = {
    "uefa.champions": "UEFA Champions League",
    "uefa.europa": "UEFA Europa League",
    "uefa.europa.conf": "UEFA Conference League",
    "ger.1": "Bundesliga — Alemania",
    "ita.1": "Serie A — Italia",
    "eng.1": "Premier League — Inglaterra",
    "esp.1": "LaLiga — España",
    "fra.1": "Ligue 1 — Francia",
    "col.1": "Liga BetPlay — Colombia",
}

APIFOOTBALL_LEAGUE_IDS = {
    "col.1": 239,
    "eng.1": 39,
    "esp.1": 140,
    "ita.1": 135,
    "ger.1": 78,
    "fra.1": 61,
    "uefa.champions": 2,
    "uefa.europa": 3,
    "uefa.europa.conf": 848,
}


@dataclass
class UpcomingMatch:
    league: str
    event_id: str
    match_date: str  # YYYY-MM-DD (UTC date used for ESPN queries)
    kickoff_utc: str
    kickoff_col: str  # YYYY-MM-DD HH:MM (Colombia UTC-5)
    home: str
    away: str
    o1: float
    ox: float
    o2: float
    ou_line: float | None
    o_over: float | None
    o_under: float | None
    provider_name: str
    home_logo: str = ""
    away_logo: str = ""
    sharp_probs: tuple[float, float, float] | None = None
    best_soft_odds: dict[str, tuple[float, str]] | None = None  # key -> (odds, bookmaker)
    is_live: bool = False
    is_completed: bool = False
    live_clock: str = ""
    live_status: str = ""
    home_score: int = 0
    away_score: int = 0


def utc_to_colombia_str(kickoff_utc: str) -> str:
    """Convert ISO UTC string (e.g. 2026-11-25T01:30Z) to Colombia local time (UTC-5)."""
    try:
        utc_dt = dt.datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
        return (utc_dt - dt.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return kickoff_utc[:16].replace("T", " ")


def load_env(env_path: str | None = None) -> dict[str, str]:
    """Read optional .env key-value pairs without requiring python-dotenv."""
    path = env_path or os.path.join(BASE_DIR, ".env")
    env = dict(os.environ)
    if not os.path.exists(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 12) -> dict | None:
    hdrs = {"User-Agent": "Mozilla/5.0"}
    if headers:
        hdrs.update(headers)
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _extract_scoreboard_odds(comp: dict) -> tuple[float, float, float, float | None, float | None, float | None, str] | None:
    odds_arr = comp.get("odds") or []
    for item in odds_arr:
        if not isinstance(item, dict):
            continue
        ml = item.get("moneyline") or {}
        h_raw = (ml.get("home") or {}).get("close", {}).get("odds") or (ml.get("home") or {}).get("open", {}).get("odds")
        d_raw = (ml.get("draw") or {}).get("close", {}).get("odds") or (ml.get("draw") or {}).get("open", {}).get("odds")
        a_raw = (ml.get("away") or {}).get("close", {}).get("odds") or (ml.get("away") or {}).get("open", {}).get("odds")
        o1 = american_to_decimal(h_raw)
        ox = american_to_decimal(d_raw)
        o2 = american_to_decimal(a_raw)
        if not (o1 and ox and o2 and o1 > 1.01 and ox > 1.01 and o2 > 1.01):
            continue

        ou_line = item.get("overUnder")
        tot = item.get("total") or {}
        ov_raw = (tot.get("over") or {}).get("close", {}).get("odds") or (tot.get("over") or {}).get("open", {}).get("odds")
        un_raw = (tot.get("under") or {}).get("close", {}).get("odds") or (tot.get("under") or {}).get("open", {}).get("odds")
        o_over = american_to_decimal(ov_raw)
        o_under = american_to_decimal(un_raw)
        prov = (item.get("provider") or {}).get("displayName") or (item.get("provider") or {}).get("name") or "ESPN"
        return o1, ox, o2, float(ou_line) if ou_line else None, o_over, o_under, prov
    return None


def fetch_espn_upcoming(leagues: list[str], days_ahead: int = 3) -> list[UpcomingMatch]:
    """Fetch upcoming pre-match and in-play fixtures with odds from ESPN's free scoreboard."""
    now_utc = dt.datetime.now(dt.timezone.utc)
    today_col = (now_utc - dt.timedelta(hours=5)).date()
    tasks = [
        (lg, (today_col + dt.timedelta(days=off)).strftime("%Y%m%d"))
        for lg in leagues
        for off in range(days_ahead)
    ]

    seen_ids: set[str] = set()
    matches: list[UpcomingMatch] = []

    def _get(lg_ds: tuple[str, str]):
        lg, ds = lg_ds
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={ds}"
        return lg, fetch_json(url)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for lg, data in ex.map(_get, tasks):
            if not data:
                continue
            for ev in data.get("events", []):
                eid = str(ev.get("id"))
                if eid in seen_ids:
                    continue
                comp = (ev.get("competitions") or [{}])[0]
                st_type = comp.get("status", {}).get("type", {})
                st_state = st_type.get("state", "pre")
                if st_state not in ("pre", "in"):
                    continue
                parsed_odds = _extract_scoreboard_odds(comp)
                if not parsed_odds:
                    parsed_odds = (2.10, 3.10, 3.20, 2.5, 1.85, 1.85, "Live" if st_state == "in" else "CazaCuotas")
                comps = comp.get("competitors") or []
                home = next((c for c in comps if c.get("homeAway") == "home"), None)
                away = next((c for c in comps if c.get("homeAway") == "away"), None)
                if not home or not away:
                    continue
                o1, ox, o2, ou_line, o_over, o_under, prov = parsed_odds
                kick = ev.get("date", "")
                seen_ids.add(eid)
                home_logo = home.get("team", {}).get("logo") or ""
                away_logo = away.get("team", {}).get("logo") or ""
                is_live = (st_state == "in")
                clock = comp.get("status", {}).get("displayClock", "")
                st_desc = st_type.get("description", "")
                try:
                    h_score = int(home.get("score") or 0)
                    a_score = int(away.get("score") or 0)
                except Exception:
                    h_score, a_score = 0, 0
                matches.append(
                    UpcomingMatch(
                        league=lg,
                        event_id=eid,
                        match_date=kick[:10],
                        kickoff_utc=kick,
                        kickoff_col=utc_to_colombia_str(kick),
                        home=home["team"]["displayName"],
                        away=away["team"]["displayName"],
                        o1=o1,
                        ox=ox,
                        o2=o2,
                        ou_line=ou_line,
                        o_over=o_over,
                        o_under=o_under,
                        provider_name=prov,
                        home_logo=home_logo,
                        away_logo=away_logo,
                        is_live=is_live,
                        live_clock=clock,
                        live_status=st_desc,
                        home_score=h_score,
                        away_score=a_score,
                    )
                )

    matches.sort(key=lambda m: (m.kickoff_utc, m.league, m.home))
    return matches


def fetch_recent_history(leagues: list[str], months_back: int = 4) -> tuple[dict, dict, dict, dict, dict]:
    """Load recent completed matches from ESPN (plus local colombia_espn.json if present)."""
    team_all: dict[str, list[tuple[int, int]]] = {}
    team_home: dict[str, list[tuple[int, int]]] = {}
    team_away: dict[str, list[tuple[int, int]]] = {}
    lg_hg: dict[str, list[int]] = {}
    lg_ag: dict[str, list[int]] = {}
    seen: set[str] = set()

    def _add(lg: str, eid: str, home: str, away: str, hg: int, ag: int) -> None:
        if eid in seen:
            return
        seen.add(eid)
        team_all.setdefault(home, []).append((hg, ag))
        team_all.setdefault(away, []).append((ag, hg))
        team_home.setdefault(home, []).append((hg, ag))
        team_away.setdefault(away, []).append((ag, hg))
        lg_hg.setdefault(lg, []).append(hg)
        lg_ag.setdefault(lg, []).append(ag)

    # Seed with local Colombia archive if available
    col_path = os.path.join(DATA_DIR, "colombia_espn.json")
    if os.path.exists(col_path):
        with open(col_path, encoding="utf-8") as f:
            for ev in json.load(f):
                _add("col.1", str(ev["id"]), ev["home"], ev["away"], int(ev["hg"]), int(ev["ag"]))

    today = dt.date.today()
    ym_list = []
    y, m = today.year, today.month
    for _ in range(months_back):
        ym_list.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    ym_list.reverse()

    tasks = [(lg, ym) for lg in leagues for ym in ym_list]
    collected = []

    def _get(lg_ym: tuple[str, str]):
        lg, ym = lg_ym
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={ym}"
        return lg, fetch_json(url)

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for lg, data in ex.map(_get, tasks):
            if not data:
                continue
            for ev in data.get("events", []):
                comp = (ev.get("competitions") or [{}])[0]
                if not comp.get("status", {}).get("type", {}).get("completed"):
                    continue
                comps = comp.get("competitors") or []
                home = next((c for c in comps if c.get("homeAway") == "home"), None)
                away = next((c for c in comps if c.get("homeAway") == "away"), None)
                if not home or not away:
                    continue
                try:
                    hg = int(home.get("score"))
                    ag = int(away.get("score"))
                except (TypeError, ValueError):
                    continue
                collected.append((ev.get("date", ""), lg, str(ev.get("id")), home["team"]["displayName"], away["team"]["displayName"], hg, ag))

    collected.sort(key=lambda x: x[0])
    for _, lg, eid, h, a, hg, ag in collected:
        _add(lg, eid, h, a, hg, ag)

    return team_all, team_home, team_away, lg_hg, lg_ag


def fetch_next_global_matches(limit: int = 8) -> list[dict]:
    """Fetch the next upcoming soccer matches worldwide from ESPN ordered strictly by kickoff time."""
    now_utc = dt.datetime.now(dt.timezone.utc)
    dates = [now_utc.strftime("%Y%m%d"), (now_utc + dt.timedelta(days=1)).strftime("%Y%m%d")]
    seen: set[str] = set()
    rows: list[tuple[dt.datetime, dict]] = []

    for ds in dates:
        data = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={ds}")
        if not data:
            continue
        lg_map = {str(lobj.get("id")): lobj.get("name", "") for lobj in data.get("leagues", []) if isinstance(lobj, dict)}
        for ev in data.get("events", []):
            eid = str(ev.get("id"))
            if eid in seen:
                continue
            seen.add(eid)
            comp = (ev.get("competitions") or [{}])[0]
            if comp.get("status", {}).get("type", {}).get("state") != "pre":
                continue
            k_str = ev.get("date", "")
            try:
                k_dt = dt.datetime.fromisoformat(k_str.replace("Z", "+00:00"))
            except Exception:
                continue
            if k_dt < now_utc - dt.timedelta(minutes=5):
                continue
            odds = _extract_scoreboard_odds(comp)
            if not odds:
                continue
            comps = comp.get("competitors") or []
            home = next((c["team"]["displayName"] for c in comps if c.get("homeAway") == "home"), None)
            away = next((c["team"]["displayName"] for c in comps if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            o1, ox, o2, ou_line, _, _, prov = odds
            lg_id = str((ev.get("league") or {}).get("id", ""))
            raw_lg = lg_map.get(lg_id) or (ev.get("season") or {}).get("slug") or "Fútbol Internacional"
            slug_map = {
                "group-stage": "Torneo Internacional",
                "league-stage": "Torneo Internacional",
                "regular-season": "Liga Nacional",
            }
            lg_label = slug_map.get(raw_lg, raw_lg)
            rows.append(
                (
                    k_dt,
                    {
                        "event_id": eid,
                        "kickoff_utc": k_str,
                        "kickoff_col": utc_to_colombia_str(k_str),
                        "league_label": lg_label,
                        "home": home,
                        "away": away,
                        "o1": round(o1, 2),
                        "ox": round(ox, 2),
                        "o2": round(o2, 2),
                        "ou_line": ou_line,
                        "provider": prov,
                    },
                )
            )

    rows.sort(key=lambda x: x[0])
    return [r[1] for r in rows[:limit]]


def fetch_espn_match_result(league: str, match_date: str, event_id: str) -> tuple[bool, int, int] | None:
    """Return (completed, hg, ag) for a given ESPN event, checking +/-1 day around match_date."""
    base_d = dt.date.fromisoformat(match_date[:10])
    candidate_dates = [
        base_d.strftime("%Y%m%d"),
        (base_d - dt.timedelta(days=1)).strftime("%Y%m%d"),
        (base_d + dt.timedelta(days=1)).strftime("%Y%m%d"),
    ]
    for ds in candidate_dates:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={ds}"
        data = fetch_json(url)
        if not data:
            continue
        for ev in data.get("events", []):
            if str(ev.get("id")) != str(event_id):
                continue
            comp = (ev.get("competitions") or [{}])[0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                return (False, 0, 0)
            comps = comp.get("competitors") or []
            home = next((c for c in comps if c.get("homeAway") == "home"), None)
            away = next((c for c in comps if c.get("homeAway") == "away"), None)
            if not home or not away:
                return None
            return (True, int(home["score"]), int(away["score"]))
    return None


def fetch_espn_match_summary(league: str, match_date: str, event_id: str) -> dict | None:
    """Fetch rich match statistics, final score, scorers, key events, and lineups from ESPN summary."""
    primary_lg = league.split("+")[0].strip() if league else "all"
    candidate_leagues = [primary_lg]
    if primary_lg != "all":
        candidate_leagues.append("all")

    for lg in candidate_leagues:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/summary?event={event_id}"
        data = fetch_json(url)
        if not data:
            continue
        header = data.get("header") or {}
        comp = (header.get("competitions") or [{}])[0]
        st_type = comp.get("status", {}).get("type", {})
        completed = bool(st_type.get("completed", False))
        status_desc = st_type.get("description", "")
        status_detail = st_type.get("detail", "")

        comps = comp.get("competitors") or []
        home_c = next((c for c in comps if c.get("homeAway") == "home"), None)
        away_c = next((c for c in comps if c.get("homeAway") == "away"), None)
        if not home_c or not away_c:
            continue

        home_team = home_c.get("team", {}).get("displayName", "")
        away_team = away_c.get("team", {}).get("displayName", "")
        home_score = int(home_c.get("score") or 0)
        away_score = int(away_c.get("score") or 0)
        home_logo = home_c.get("team", {}).get("logo", "")
        away_logo = away_c.get("team", {}).get("logo", "")

        goals: list[dict] = []
        red_cards: list[dict] = []
        for ev in data.get("keyEvents", []):
            ev_type = (ev.get("type") or {}).get("text", "")
            clk = (ev.get("clock") or {}).get("displayValue", "")
            txt = ev.get("text", "")
            if ev_type == "Goal":
                goals.append({"minute": clk, "text": txt})
            elif "Red Card" in ev_type or "red card" in txt.lower():
                red_cards.append({"minute": clk, "text": txt})

        stats_out = {"home": {}, "away": {}}
        box = data.get("boxscore", {})
        for t in box.get("teams", []):
            ha = t.get("homeAway")
            if ha in ("home", "away"):
                t_stats = {s["name"]: s.get("displayValue", "") for s in t.get("statistics", [])}
                stats_out[ha] = {
                    "possession": t_stats.get("possessionPct", "50"),
                    "shots": t_stats.get("totalShots", "0"),
                    "shots_on_target": t_stats.get("shotsOnTarget", "0"),
                    "corners": t_stats.get("wonCorners", "0"),
                    "fouls": t_stats.get("foulsCommitted", "0"),
                    "yellow_cards": t_stats.get("yellowCards", "0"),
                    "saves": t_stats.get("saves", "0"),
                }

        league_label = (data.get("season") or {}).get("name") or league
        return {
            "event_id": str(event_id),
            "league": league,
            "league_label": league_label,
            "completed": completed,
            "status_desc": status_desc,
            "status_detail": status_detail,
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "home_logo": home_logo,
            "away_logo": away_logo,
            "goals": goals,
            "red_cards": red_cards,
            "stats": stats_out,
        }
    return None



def enrich_with_apifootball(matches: list[UpcomingMatch], api_key: str) -> tuple[int, str | None]:
    """Optional multi-bookmaker line shopping using API-Football; stops early if free plan blocks season."""
    if not api_key or not matches:
        return 0, None
    headers = {"x-apisports-key": api_key}
    dates = sorted({m.match_date for m in matches})
    leagues_present = sorted({m.league for m in matches if m.league in APIFOOTBALL_LEAGUE_IDS})

    # Map API-Football fixtures by normalized (date, home_prefix)
    fixture_map: dict[tuple[str, str], int] = {}
    for lg in leagues_present:
        lg_id = APIFOOTBALL_LEAGUE_IDS[lg]
        for ds in dates:
            yr, mo = int(ds[:4]), int(ds[5:7])
            season = yr if lg == "col.1" or mo >= 7 else yr - 1
            url = f"https://v3.football.api-sports.io/fixtures?league={lg_id}&date={ds}&season={season}"
            data = fetch_json(url, headers=headers)
            errs = (data or {}).get("errors")
            if errs:
                msg = errs.get("plan") if isinstance(errs, dict) else str(errs)
                return 0, str(msg)
            for item in (data or {}).get("response", []):
                fid = item["fixture"]["id"]
                h_name = item["teams"]["home"]["name"].lower()[:6]
                fixture_map[(ds, h_name)] = fid

    enriched = 0
    for m in matches:
        fid = fixture_map.get((m.match_date, m.home.lower()[:6]))
        if not fid:
            continue
        odds_data = fetch_json(f"https://v3.football.api-sports.io/odds?fixture={fid}", headers=headers)
        resp = (odds_data or {}).get("response", [])
        if not resp:
            continue
        bookmakers = resp[0].get("bookmakers", [])
        sharp_1x2 = None
        best_soft: dict[str, tuple[float, str]] = {}
        for bm in bookmakers:
            bname = bm.get("name", "")
            mw = next((b for b in bm.get("bets", []) if b.get("name") == "Match Winner"), None)
            if not mw:
                continue
            vals = {v["value"]: float(v["odd"]) for v in mw.get("values", []) if v.get("odd")}
            if not all(k in vals for k in ("Home", "Draw", "Away")):
                continue
            if "pinnacle" in bname.lower() or "betfair" in bname.lower():
                sharp_1x2 = devig_3(vals["Home"], vals["Draw"], vals["Away"])
            for k_api, k_int in (("Home", "1"), ("Draw", "X"), ("Away", "2")):
                if k_int not in best_soft or vals[k_api] > best_soft[k_int][0]:
                    best_soft[k_int] = (vals[k_api], bname)
        if sharp_1x2 and best_soft:
            m.sharp_probs = sharp_1x2
            m.best_soft_odds = best_soft
            enriched += 1
    return enriched, None


def send_telegram_message(text: str, token: str, chat_id: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False
