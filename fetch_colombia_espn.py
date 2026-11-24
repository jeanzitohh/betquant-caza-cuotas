import concurrent.futures
import json
import os
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE_DIR, "data", "colombia_espn.json")


def fetch_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def parse_odds_item(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    home_close = item.get("homeTeamOdds", {}).get("close", {}).get("moneyLine", {}).get("decimal")
    away_close = item.get("awayTeamOdds", {}).get("close", {}).get("moneyLine", {}).get("decimal")
    draw_close = item.get("close", {}).get("draw", {}).get("decimal")

    home_open = item.get("homeTeamOdds", {}).get("open", {}).get("moneyLine", {}).get("decimal")
    away_open = item.get("awayTeamOdds", {}).get("open", {}).get("moneyLine", {}).get("decimal")
    draw_open = item.get("open", {}).get("draw", {}).get("decimal")

    ou_line = item.get("overUnder")
    over_close = item.get("close", {}).get("over", {}).get("decimal")
    under_close = item.get("close", {}).get("under", {}).get("decimal")

    if not (home_close and away_close and draw_close):
        return None
    return {
        "provider": item.get("provider", {}).get("name"),
        "h_close": float(home_close),
        "d_close": float(draw_close),
        "a_close": float(away_close),
        "h_open": float(home_open) if home_open else None,
        "d_open": float(draw_open) if draw_open else None,
        "a_open": float(away_open) if away_open else None,
        "ou_line": float(ou_line) if ou_line is not None else None,
        "over_close": float(over_close) if over_close else None,
        "under_close": float(under_close) if under_close else None,
    }


def fetch_event_odds(ev_basic: dict) -> dict:
    eid = ev_basic["id"]
    url = f"https://sports.core.api.espn.com/v2/sports/soccer/leagues/col.1/events/{eid}/competitions/{eid}/odds"
    data = fetch_json(url)
    odds_list = []
    if data and "items" in data:
        for it in data["items"]:
            parsed = parse_odds_item(it)
            if parsed:
                odds_list.append(parsed)
    ev_basic["odds_list"] = odds_list
    return ev_basic


def main() -> None:
    months = []
    for yr in (2024, 2025, 2026):
        max_m = 11 if yr == 2026 else 12
        for m in range(1, max_m + 1):
            months.append(f"{yr}{m:02d}")

    raw_events = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {
            ex.submit(fetch_json, f"https://site.api.espn.com/apis/site/v2/sports/soccer/col.1/scoreboard?dates={ym}"): ym
            for ym in months
        }
        for fut in concurrent.futures.as_completed(futs):
            d = fut.result()
            if not d:
                continue
            for ev in d.get("events", []):
                comp = ev.get("competitions", [{}])[0]
                status = comp.get("status", {}).get("type", {})
                if not status.get("completed"):
                    continue
                comps = comp.get("competitors", [])
                home = next((c for c in comps if c.get("homeAway") == "home"), None)
                away = next((c for c in comps if c.get("homeAway") == "away"), None)
                if not home or not away:
                    continue
                try:
                    hg = int(home.get("score"))
                    ag = int(away.get("score"))
                except (TypeError, ValueError):
                    continue
                eid = ev["id"]
                raw_events[eid] = {
                    "id": eid,
                    "date": ev["date"],
                    "home": home["team"]["displayName"],
                    "away": away["team"]["displayName"],
                    "hg": hg,
                    "ag": ag,
                }

    events = sorted(raw_events.values(), key=lambda x: x["date"])
    print(f"Found {len(events)} completed Colombia Primera A matches (2024-2026). Fetching odds...")

    enriched = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        for res in ex.map(fetch_event_odds, events):
            enriched.append(res)

    with_odds = sum(1 for e in enriched if e["odds_list"])
    with_ou = sum(1 for e in enriched if any(o.get("over_close") for o in e["odds_list"]))
    print(f"Completed: {len(enriched)}, with 1X2 odds: {with_odds}, with O/U odds: {with_ou}")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False)
    print(f"Saved {OUT_PATH}")


if __name__ == "__main__":
    main()
