import json
import os
import urllib.request
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_FILE = os.path.join(DATA_DIR, "core_lineups_cache.json")


def load_lineup_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_lineup_cache(cache: dict) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def fetch_espn_rosters(league: str, event_id: str) -> dict[str, list[str]]:
    """Fetch confirmed starting XI (11 players) from ESPN match summary."""
    primary_lg = league.split("+")[0].strip() if league else "all"
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{primary_lg}/summary?event={event_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}

    out = {}
    for r in data.get("rosters", []):
        tname = (r.get("team", {}).get("displayName") or "").strip()
        starters = [
            (p.get("athlete", {}).get("displayName") or "").strip()
            for p in r.get("roster", [])
            if p.get("starter") and p.get("athlete", {}).get("displayName")
        ]
        if tname and len(starters) == 11:
            out[tname] = starters
    return out


def fetch_apifootball_fixture_injuries(fixture_id: int, api_key: str) -> dict[str, list[str]]:
    """Fetch reported injuries / missing players for a specific fixture from API-Football."""
    if not fixture_id or not api_key:
        return {}
    url = f"https://v3.football.api-sports.io/injuries?fixture={fixture_id}"
    req = urllib.request.Request(url, headers={"x-apisports-key": api_key, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}

    by_team = {}
    for item in data.get("response", []):
        tname = item.get("team", {}).get("name") or "Unknown"
        pname = item.get("player", {}).get("name") or "Jugador"
        reason = item.get("player", {}).get("reason") or "Lesión"
        by_team.setdefault(tname, []).append(f"{pname} ({reason})")
    return by_team


def evaluate_team_titularity(
    team_name: str,
    current_starters: list[str],
    core_starters: list[str] | None = None,
    reported_bajas: list[str] | None = None,
) -> dict:
    """Calculate titularity percentage of the starting XI against habitual starters.
    
    Returns an alert dict ONLY if titularity < 75.0% (meaning <= 8 habitual starters,
    i.e., 3 or more key starters absent / rotated / injured).
    """
    # 1. Confirmed starting XI available
    if len(current_starters) == 11:
        core = core_starters or []
        if len(core) >= 11:
            core_set = {n.lower() for n in core[:11]}
            curr_in_core = [p for p in current_starters if p.lower() in core_set]
            missing = [p for p in core[:11] if p.lower() not in {c.lower() for c in current_starters}]
            starters_count = len(curr_in_core)
            pct = round((starters_count / 11.0) * 100.0, 1)
            is_alert = pct < 75.0
            return {
                "team": team_name,
                "is_alert": is_alert,
                "starters_pct": pct,
                "starters_count": starters_count,
                "missing_count": len(missing),
                "missing_names": missing,
                "status": "CONFIRMED_LINEUP",
                "note": (
                    f"⚠️ ALERTA DE ALINEACIÓN: {team_name} inicia con sólo el {pct}% de sus titulares habituales "
                    f"({starters_count}/11). Bajas/Suplentes: {', '.join(missing[:4])}."
                    if is_alert else ""
                ),
            }

    # 2. Pre-match reported absences / injuries
    bajas = reported_bajas or []
    if len(bajas) >= 3:
        starters_count = max(0, 11 - len(bajas))
        pct = round((starters_count / 11.0) * 100.0, 1)
        return {
            "team": team_name,
            "is_alert": True,
            "starters_pct": pct,
            "starters_count": starters_count,
            "missing_count": len(bajas),
            "missing_names": bajas,
            "status": "PROJECTED_ABSENCES",
            "note": (
                f"⚠️ ALERTA PREVIA DE PLANTILLA: {team_name} presenta {len(bajas)} bajas clave "
                f"({pct}% disponibilidad estelar). Bajas: {', '.join(bajas[:4])}."
            ),
        }

    return {"team": team_name, "is_alert": False, "starters_pct": 100.0}


def penalize_lambda_for_lineup(lam: float, starters_pct: float) -> float:
    """Dampen team expected goals lambda if titularity < 75%."""
    if starters_pct >= 75.0:
        return lam
    penalty = 0.70 + 0.30 * (max(10.0, starters_pct) / 100.0)
    return round(lam * penalty, 3)


def check_match_lineup_alerts(
    league: str,
    event_id: str,
    home: str,
    away: str,
    api_fixture_id: int | None = None,
    api_key: str = "",
) -> Optional[dict]:
    """Inspect lineups and injury reports for a match.
    
    Returns an alert dict ONLY if home or away has < 75% starters.
    Otherwise returns None (keeping the UI completely clean when normal).
    """
    cache = load_lineup_cache()
    rosters = fetch_espn_rosters(league, event_id)
    injuries_map = {}
    if api_fixture_id and api_key:
        injuries_map = fetch_apifootball_fixture_injuries(api_fixture_id, api_key)

    h_starters = rosters.get(home) or []
    a_starters = rosters.get(away) or []

    # Update cache if confirmed lineups exist
    updated = False
    if len(h_starters) == 11:
        if home not in cache or len(cache[home]) < 11:
            cache[home] = h_starters
            updated = True
    if len(a_starters) == 11:
        if away not in cache or len(cache[away]) < 11:
            cache[away] = a_starters
            updated = True
    if updated:
        save_lineup_cache(cache)

    h_bajas = injuries_map.get(home) or []
    a_bajas = injuries_map.get(away) or []

    h_eval = evaluate_team_titularity(home, h_starters, cache.get(home), h_bajas)
    a_eval = evaluate_team_titularity(away, a_starters, cache.get(away), a_bajas)

    if h_eval.get("is_alert"):
        return h_eval
    if a_eval.get("is_alert"):
        return a_eval

    return None
