import argparse
import datetime as dt

from paper_db import PaperTradingDB
from providers import (
    LEAGUE_LABELS,
    UpcomingMatch,
    enrich_with_apifootball,
    fetch_espn_match_result,
    fetch_espn_match_summary,
    fetch_espn_upcoming,
    fetch_next_global_matches,
    fetch_recent_history,
    load_env,
    send_telegram_message,
)
from quant_math import (
    calibrate_market_lambdas,
    devig_3,
    estimate_team_lambdas,
    half_time_breakdown,
    poisson_probs,
    rolling_team_summary,
)
from lineup_tracker import check_match_lineup_alerts, penalize_lambda_for_lineup

DEFAULT_LEAGUES = ["col.1", "eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "uefa.champions"]

MARKET_NAMES = {
    "1": "Gana Local (1)",
    "X": "Empate (X)",
    "2": "Gana Visitante (2)",
    "1X": "Local o Empate (1X)",
    "X2": "Visitante o Empate (X2)",
    "H_O05": "Local +0.5 goles",
    "H_O15": "Local +1.5 goles",
    "A_O05": "Visitante +0.5 goles",
    "A_O15": "Visitante +1.5 goles",
    "1H_O05": "1er Tiempo: Más de 0.5 goles (1T +0.5)",
    "1H_O15": "1er Tiempo: Más de 1.5 goles (1T +1.5)",
    "2H_O05": "2do Tiempo: Más de 0.5 goles (2T +0.5)",
    "2H_O15": "2do Tiempo: Más de 1.5 goles (2T +1.5)",
    "1H_H_O05": "1er Tiempo: Local anota gol",
    "1H_A_O05": "1er Tiempo: Visitante anota gol",
    "2H_H_O05": "2do Tiempo: Local anota gol",
    "2H_A_O05": "2do Tiempo: Visitante anota gol",
    "MOST_GOALS_2H": "Mitad con más goles: 2do Tiempo",
    "BB_H_1_O05": "Mismo partido: Local Gana + Local +0.5 goles",
    "BB_H_1_O15": "Mismo partido: Local Gana + Local +1.5 goles",
    "BB_H_1X_O05": "Mismo partido: Local 1X + Local +0.5 goles",
    "BB_H_1X_O15": "Mismo partido: Local 1X + Local +1.5 goles",
    "BB_H_1_T15": "Mismo partido: Local Gana + +1.5 goles en el partido",
    "BB_H_1X_T15": "Mismo partido: Local 1X + +1.5 goles en el partido",
    "BB_A_2_O05": "Mismo partido: Visita Gana + Visita +0.5 goles",
    "BB_A_2_O15": "Mismo partido: Visita Gana + Visita +1.5 goles",
    "BB_A_X2_O05": "Mismo partido: Visita X2 + Visita +0.5 goles",
    "BB_A_X2_O15": "Mismo partido: Visita X2 + Visita +1.5 goles",
    "BB_A_2_T15": "Mismo partido: Visita Gana + +1.5 goles en el partido",
    "BB_A_X2_T15": "Mismo partido: Visita X2 + +1.5 goles en el partido",
}


def build_match_markets(m: UpcomingMatch) -> dict[str, float]:
    """Compute available 1X2 odds plus market-calibrated DC, Team Goals, Half-Time, and Bet Builder odds."""
    p1_f, px_f, p2_f = devig_3(m.o1, m.ox, m.o2)
    lam_h_mkt, lam_a_mkt = calibrate_market_lambdas(m.o1, m.ox, m.o2, m.ou_line, m.o_over, m.o_under)
    mp = poisson_probs(lam_h_mkt, lam_a_mkt)
    ht_mkt = half_time_breakdown(lam_h_mkt, lam_a_mkt)
    hp = ht_mkt["probs"]

    def from_p(p: float, vig: float) -> float:
        return round(max(1.01, min(35.0, 1.0 / max(p * vig, 0.01))), 3)

    return {
        "1": m.o1,
        "X": m.ox,
        "2": m.o2,
        "1X": from_p(p1_f + px_f, 1.055),
        "X2": from_p(p2_f + px_f, 1.055),
        "H_O05": from_p(mp["H_O05"], 1.065),
        "H_O15": from_p(mp["H_O15"], 1.065),
        "A_O05": from_p(mp["A_O05"], 1.065),
        "A_O15": from_p(mp["A_O15"], 1.065),
        "1H_O05": from_p(hp["1H_O05"], 1.065),
        "1H_O15": from_p(hp["1H_O15"], 1.065),
        "2H_O05": from_p(hp["2H_O05"], 1.065),
        "2H_O15": from_p(hp["2H_O15"], 1.065),
        "1H_H_O05": from_p(hp["1H_H_O05"], 1.07),
        "1H_A_O05": from_p(hp["1H_A_O05"], 1.07),
        "2H_H_O05": from_p(hp["2H_H_O05"], 1.07),
        "2H_A_O05": from_p(hp["2H_A_O05"], 1.07),
        "MOST_GOALS_2H": from_p(hp["MOST_GOALS_2H"], 1.075),
        "BB_H_1_O05": from_p(mp["BB_H_1_O05"], 1.10),
        "BB_H_1_O15": from_p(mp["BB_H_1_O15"], 1.10),
        "BB_H_1X_O05": from_p(mp["BB_H_1X_O05"], 1.10),
        "BB_H_1X_O15": from_p(mp["BB_H_1X_O15"], 1.10),
        "BB_H_1_T15": from_p(mp["BB_H_1_T15"], 1.10),
        "BB_H_1X_T15": from_p(mp["BB_H_1X_T15"], 1.10),
        "BB_A_2_O05": from_p(mp["BB_A_2_O05"], 1.10),
        "BB_A_2_O15": from_p(mp["BB_A_2_O15"], 1.10),
        "BB_A_X2_O05": from_p(mp["BB_A_X2_O05"], 1.10),
        "BB_A_X2_O15": from_p(mp["BB_A_X2_O15"], 1.10),
        "BB_A_2_T15": from_p(mp["BB_A_2_T15"], 1.10),
        "BB_A_X2_T15": from_p(mp["BB_A_X2_T15"], 1.10),
    }


def grade_market(market: str, hg: int, ag: int, summary: dict | None = None) -> bool:
    checks = {
        "1": hg > ag,
        "X": hg == ag,
        "2": ag > hg,
        "1X": hg >= ag,
        "X2": ag >= hg,
        "H_O05": hg >= 1,
        "H_O15": hg >= 2,
        "A_O05": ag >= 1,
        "A_O15": ag >= 2,
        "O15": (hg + ag) >= 2,
        "O25": (hg + ag) >= 3,
        "BTTS": hg >= 1 and ag >= 1,
        "BB_H_1_O05": hg > ag and hg >= 1,
        "BB_H_1_O15": hg > ag and hg >= 2,
        "BB_H_1X_O05": hg >= ag and hg >= 1,
        "BB_H_1X_O15": hg >= ag and hg >= 2,
        "BB_H_1_T15": hg > ag and (hg + ag) >= 2,
        "BB_H_1X_T15": hg >= ag and (hg + ag) >= 2,
        "BB_A_2_O05": ag > hg and ag >= 1,
        "BB_A_2_O15": ag > hg and ag >= 2,
        "BB_A_X2_O05": ag >= hg and ag >= 1,
        "BB_A_X2_O15": ag >= hg and ag >= 2,
        "BB_A_2_T15": ag > hg and (hg + ag) >= 2,
        "BB_A_X2_T15": ag >= hg and (hg + ag) >= 2,
    }
    if market in checks:
        return checks[market]

    # Half-time markets evaluation using minute of goals
    if summary and summary.get("goals"):
        goals = summary["goals"]
        def _get_m(g):
            clk = str(g.get("minute") or g.get("clock") or "0").replace("'", "").split("+")[0].strip()
            try:
                return int(clk)
            except Exception:
                return 50
        g_1h = sum(1 for g in goals if _get_m(g) <= 45)
        g_2h = max(0, (hg + ag) - g_1h)
        if market == "1H_O05": return g_1h >= 1
        if market == "1H_O15": return g_1h >= 2
        if market == "2H_O05": return g_2h >= 1
        if market == "2H_O15": return g_2h >= 2
        if market == "MOST_GOALS_2H": return g_2h > g_1h
        if market == "MOST_GOALS_1H": return g_1h > g_2h
    elif (hg + ag) >= 2:
        # Fallback if no goal breakdown: 2H has >=1 goal if total is >= 2 in 85% of cases
        if market == "2H_O05": return True

    return False


def evaluate_match(
    m: UpcomingMatch,
    team_all: dict,
    team_home: dict,
    team_away: dict,
    lg_hg: dict,
    lg_ag: dict,
    calibration: dict | None = None,
    lineup_alert: dict | None = None,
) -> dict:
    """Evaluate Sharp Value (if available), Poisson stats, Formula Option A legs, and Option B Bet Builders."""
    mkt_odds = build_match_markets(m)
    h_recent = team_all.get(m.home, [])[-10:]
    a_recent = team_all.get(m.away, [])[-10:]
    h_stat = rolling_team_summary(h_recent)
    a_stat = rolling_team_summary(a_recent)

    h_sp = team_home.get(m.home, [])
    a_sp = team_away.get(m.away, [])
    lg_h_vals = lg_hg.get(m.league) or [1.45]
    lg_a_vals = lg_ag.get(m.league) or [1.10]
    avg_h = sum(lg_h_vals[-200:]) / len(lg_h_vals[-200:])
    avg_a = sum(lg_a_vals[-200:]) / len(lg_a_vals[-200:])

    if len(h_sp) >= 2 and len(a_sp) >= 2:
        lam_h, lam_a = estimate_team_lambdas(h_sp, a_sp, avg_h, avg_a)
    else:
        lam_h, lam_a = calibrate_market_lambdas(m.o1, m.ox, m.o2, m.ou_line, m.o_over, m.o_under)

    # Penalize expected goals lambda if either team has < 75% titularity
    if lineup_alert:
        if lineup_alert.get("team") == m.home:
            lam_h = penalize_lambda_for_lineup(lam_h, lineup_alert.get("starters_pct", 70.0))
        elif lineup_alert.get("team") == m.away:
            lam_a = penalize_lambda_for_lineup(lam_a, lineup_alert.get("starters_pct", 70.0))

    qprobs = poisson_probs(lam_h, lam_a)

    # 1st Half (1T) & 2nd Half (2T) Goal Modeling
    half_data = half_time_breakdown(lam_h, lam_a)
    qprobs.update(half_data["probs"])

    sharp_picks = []
    if m.sharp_probs and m.best_soft_odds:
        p_map = {"1": m.sharp_probs[0], "X": m.sharp_probs[1], "2": m.sharp_probs[2]}
        for k in ("1", "X", "2"):
            if k not in m.best_soft_odds:
                continue
            soft_o, bm_name = m.best_soft_odds[k]
            ev = (p_map[k] * soft_o - 1.0) * 100.0
            if ev >= 2.0:
                sharp_picks.append({"market": k, "odds": soft_o, "bookmaker": bm_name, "sharp_prob": p_map[k], "ev_pct": ev})

    opt_a_cands = []
    if h_stat["n"] >= 5 and a_stat["n"] >= 5:
        if h_stat["win_pct"] >= 0.50 and (h_stat["win_pct"] - a_stat["win_pct"]) >= 0.15 and h_stat["gf_avg"] >= 1.3:
            opt_a_cands.append("1")
        if h_stat["unbeaten_pct"] >= 0.70 and h_stat["gf_avg"] >= 1.0:
            opt_a_cands.append("1X")
        if a_stat["win_pct"] >= 0.50 and (a_stat["win_pct"] - h_stat["win_pct"]) >= 0.15 and a_stat["gf_avg"] >= 1.3:
            opt_a_cands.append("2")
        if a_stat["unbeaten_pct"] >= 0.70 and a_stat["gf_avg"] >= 1.0:
            opt_a_cands.append("X2")
        if h_stat["o05_pct"] >= 0.75 and h_stat["gf_avg"] >= 1.2 and a_stat["ga_avg"] >= 0.9:
            opt_a_cands.append("H_O05")
        if h_stat["o15_pct"] >= 0.45 and h_stat["gf_avg"] >= 1.5 and a_stat["ga_avg"] >= 1.2:
            opt_a_cands.append("H_O15")
        if a_stat["o05_pct"] >= 0.75 and a_stat["gf_avg"] >= 1.2 and h_stat["ga_avg"] >= 0.9:
            opt_a_cands.append("A_O05")
        if a_stat["o15_pct"] >= 0.45 and a_stat["gf_avg"] >= 1.5 and h_stat["ga_avg"] >= 1.2:
            opt_a_cands.append("A_O15")

    # High-probability half-time goal lines as candidate straight legs
    if qprobs.get("2H_O05", 0) >= 0.72:
        opt_a_cands.append("2H_O05")
    if qprobs.get("1H_O05", 0) >= 0.65:
        opt_a_cands.append("1H_O05")

    cal = calibration or {}

    def _cal_prob(mkt_key: str) -> tuple[float, bool]:
        info = cal.get(mkt_key) or {}
        if info.get("blocked"):
            return 0.0, True
        adj = qprobs[mkt_key] + float(info.get("bias", 0.0))
        return max(0.05, min(0.95, adj)), False

    opt_a_valid = []
    for k in opt_a_cands:
        cp, blk = _cal_prob(k)
        if not blk and 1.18 <= mkt_odds[k] <= 1.65 and cp >= 0.62:
            opt_a_valid.append((k, mkt_odds[k], cp))
    best_opt_a = max(opt_a_valid, key=lambda x: (x[2], -abs(x[1] - 1.32))) if opt_a_valid else None

    # Straight real bookmaker markets ONLY (1, X, 2, 1X, X2, 2H_O05, 1H_O05, H_O15, A_O15, etc.)
    # Synthetic same-match Bet Builders are blocked because bookmakers apply correlation discounts.
    straight_cands = []
    for k in ("1X", "X2", "1", "2", "2H_O05", "1H_O05", "H_O15", "A_O15", "H_O05", "A_O05", "MOST_GOALS_2H"):
        if k in mkt_odds and not k.startswith("BB_"):
            straight_cands.append(k)

    opt_b_valid = []
    for k in straight_cands:
        cp, blk = _cal_prob(k)
        if not blk and 1.22 <= mkt_odds[k] <= 2.10 and cp >= 0.55:
            opt_b_valid.append((k, mkt_odds[k], cp))
    best_opt_b = max(opt_b_valid, key=lambda x: (x[1] >= 1.40, x[2], -abs(x[1] - 1.50))) if opt_b_valid else None

    # Best individual pick for daily accuracy tracking ("BOT_DIARIO") — Straight markets only
    safe_pool = []
    for k, odd in mkt_odds.items():
        if k.startswith("BB_") or not (1.20 <= odd <= 1.75):
            continue
        cp, blk = _cal_prob(k)
        if not blk and cp >= 0.65:
            safe_pool.append((k, odd, cp))
    best_daily_safe = max(safe_pool, key=lambda x: (x[2], -abs(x[1] - 1.40))) if safe_pool else None

    return {
        "match": m,
        "h_stat": h_stat,
        "a_stat": a_stat,
        "h_recent": h_recent,
        "a_recent": a_recent,
        "lam_h": lam_h,
        "lam_a": lam_a,
        "half_data": half_data,
        "mkt_odds": mkt_odds,
        "qprobs": qprobs,
        "sharp_picks": sharp_picks,
        "opt_a_all": opt_a_valid,
        "best_opt_a": best_opt_a,
        "best_opt_b": best_opt_b,
        "best_daily_safe": best_daily_safe,
        "lineup_alert": lineup_alert,
    }


def run_scan_pipeline(leagues: list[str] | None = None, days: int = 3, save: bool = False) -> dict:
    """Shared scan pipeline used by both the CLI and the local Web Dashboard."""
    env = load_env()
    target_leagues = leagues or DEFAULT_LEAGUES
    upcoming = fetch_espn_upcoming(target_leagues, days_ahead=days)
    team_all, team_home, team_away, lg_hg, lg_ag = fetch_recent_history(target_leagues)

    api_key = env.get("APIFOOTBALL_KEY", "").strip()
    if api_key:
        enriched_count, api_note = enrich_with_apifootball(upcoming, api_key)
    else:
        enriched_count, api_note = 0, None

    db_read = PaperTradingDB()
    calibration = db_read.get_market_calibration()
    db_read.set_state("last_calibration", f"{len(calibration)} mercados medidos")

    evals = []
    for m in upcoming:
        l_alert = check_match_lineup_alerts(m.league, m.event_id, m.home, m.away, kickoff_col=m.kickoff_col, api_key=api_key)
        e = evaluate_match(m, team_all, team_home, team_away, lg_hg, lg_ag, calibration=calibration, lineup_alert=l_alert)
        evals.append(e)
    db = db_read if save else None
    saved_count = 0

    if db:
        for e in evals:
            safe = e.get("best_daily_safe")
            if not safe:
                continue
            m = e["match"]
            ks, osafe, psafe = safe
            imp_s = 1.0 / osafe
            ev_s = (psafe * osafe - 1.0) * 100.0
            saved_count += int(
                db.record_trade(
                    match_date=m.kickoff_col[:10],
                    league=m.league,
                    match_key=m.event_id,
                    title=f"{m.home} vs {m.away}",
                    strategy="BOT_DIARIO",
                    market=ks,
                    odds=osafe,
                    model_prob=psafe,
                    implied_prob=imp_s,
                    ev_pct=ev_s,
                    stake_u=2.0,
                    legs=[{"event_id": m.event_id, "league": m.league, "match_date": m.match_date, "market": ks}],
                )
            )

    sharp_list = []
    for e in evals:
        m = e["match"]
        for sp in e["sharp_picks"]:
            sharp_list.append(
                {
                    "kickoff_col": m.kickoff_col,
                    "league": m.league,
                    "title": f"{m.home} vs {m.away}",
                    "market": sp["market"],
                    "market_name": MARKET_NAMES[sp["market"]],
                    "odds": sp["odds"],
                    "bookmaker": sp["bookmaker"],
                    "prob": round(sp["sharp_prob"] * 100.0, 1),
                    "ev_pct": round(sp["ev_pct"], 2),
                }
            )
            if db:
                saved_count += int(
                    db.record_trade(
                        match_date=m.kickoff_col[:10],
                        league=m.league,
                        match_key=m.event_id,
                        title=f"{m.home} vs {m.away}",
                        strategy="SHARP_VALUE",
                        market=sp["market"],
                        odds=sp["odds"],
                        model_prob=sp["sharp_prob"],
                        implied_prob=1.0 / sp["odds"],
                        ev_pct=sp["ev_pct"],
                        stake_u=2.0,
                        legs=[{"event_id": m.event_id, "league": m.league, "match_date": m.match_date, "market": sp["market"]}],
                    )
                )

    # Build 2-match same-day combinadas strictly targeting >= 1.50 (1.50–1.95) sorted by highest probability
    # ONLY uses pure real straight markets (no same-match Bet Builders) so bookmakers never slash correlated odds
    leg_pool: list[tuple[int, str, float, float]] = []
    for idx, e in enumerate(evals):
        seen_k: set[str] = set()
        for k, o, p in e.get("opt_a_all") or []:
            if k not in seen_k and 1.12 <= o <= 1.65 and p >= 0.62:
                leg_pool.append((idx, k, o, p))
                seen_k.add(k)

    cand_pairs = []
    for a_i in range(len(leg_pool)):
        i, k1, o1, p1 = leg_pool[a_i]
        m1 = evals[i]["match"]
        d1 = dt.date.fromisoformat(m1.kickoff_col[:10])
        for b_j in range(a_i + 1, len(leg_pool)):
            j, k2, o2, p2 = leg_pool[b_j]
            if i == j:
                continue
            m2 = evals[j]["match"]
            d2 = dt.date.fromisoformat(m2.kickoff_col[:10])
            if abs((d2 - d1).days) > 0:
                continue
            combo = round(o1 * o2, 3)
            p_combo = p1 * p2
            if 1.50 <= combo <= 1.95 and p_combo >= 0.45:
                cand_pairs.append((p_combo >= 0.50, round(p_combo, 4), -abs(combo - 1.65), i, k1, o1, p1, j, k2, o2, p2, combo, p_combo))

    cand_pairs.sort(reverse=True)
    parlays_a = []
    used: set[int] = set()
    for _, _, _, i, k1, o1, p1, j, k2, o2, p2, combo, p_combo in cand_pairs:
        if i in used or j in used:
            continue
        used.add(i)
        used.add(j)
        m1 = evals[i]["match"]
        m2 = evals[j]["match"]
        imp = 1.0 / combo
        ev_est = (p_combo * combo - 1.0) * 100.0
        parlays_a.append(
            {
                "kickoff_col": min(m1.kickoff_col, m2.kickoff_col),
                "leg1_kickoff": m1.kickoff_col,
                "leg2_kickoff": m2.kickoff_col,
                "title": f"{m1.home} vs {m1.away} + {m2.home} vs {m2.away}",
                "leg1": f"({m1.league}) {m1.home} vs {m1.away}: {MARKET_NAMES[k1]} @{o1:.2f}",
                "leg2": f"({m2.league}) {m2.home} vs {m2.away}: {MARKET_NAMES[k2]} @{o2:.2f}",
                "market_key": f"{k1}+{k2}",
                "combo_odds": combo,
                "prob_est": round(p_combo * 100.0, 1),
                "prob_impl": round(imp * 100.0, 1),
                "ev_pct": round(ev_est, 1),
                "legs": [
                    {"event_id": m1.event_id, "league": m1.league, "match_date": m1.match_date, "kickoff_col": m1.kickoff_col, "market": k1},
                    {"event_id": m2.event_id, "league": m2.league, "match_date": m2.match_date, "kickoff_col": m2.kickoff_col, "market": k2},
                ],
            }
        )
        if db:
            saved_count += int(
                db.record_trade(
                    match_date=max(m1.kickoff_col[:10], m2.kickoff_col[:10]),
                    league=f"{m1.league}+{m2.league}",
                    match_key=f"{m1.event_id}+{m2.event_id}",
                    title=f"{m1.home} vs {m1.away} + {m2.home} vs {m2.away}",
                    strategy="FORMULA_OPT_A",
                    market=f"{k1}+{k2}",
                    odds=combo,
                    model_prob=p_combo,
                    implied_prob=imp,
                    ev_pct=ev_est,
                    stake_u=2.0,
                    legs=[
                        {"event_id": m1.event_id, "league": m1.league, "match_date": m1.match_date, "market": k1},
                        {"event_id": m2.event_id, "league": m2.league, "match_date": m2.match_date, "market": k2},
                    ],
                )
            )

    # Sort parlays strictly chronologically so today's games are sent/listed first
    parlays_a.sort(key=lambda p: (p["kickoff_col"], -p["prob_est"]))

    opt_b = []
    for e in evals:
        if e["best_opt_b"] is None:
            continue
        m = e["match"]
        kb, ob, pb = e["best_opt_b"]
        imp = 1.0 / ob
        ev_est = (pb * ob - 1.0) * 100.0
        opt_b.append(
            {
                "kickoff_col": m.kickoff_col,
                "league": m.league,
                "title": f"{m.home} vs {m.away}",
                "market": kb,
                "market_name": MARKET_NAMES[kb],
                "odds": ob,
                "prob_est": round(pb * 100.0, 1),
                "prob_impl": round(imp * 100.0, 1),
                "ev_pct": round(ev_est, 1),
            }
        )
        if db:
            saved_count += int(
                db.record_trade(
                    match_date=m.kickoff_col[:10],
                    league=m.league,
                    match_key=m.event_id,
                    title=f"{m.home} vs {m.away}",
                    strategy="FORMULA_OPT_B",
                    market=kb,
                    odds=ob,
                    model_prob=pb,
                    implied_prob=imp,
                    ev_pct=ev_est,
                    stake_u=2.0,
                    legs=[{"event_id": m.event_id, "league": m.league, "match_date": m.match_date, "market": kb}],
                )
            )

    matches_detail = []
    for e in evals:
        m = e["match"]
        hs, as_ = e["h_stat"], e["a_stat"]
        qp = e["qprobs"]
        p_btts = max(0.0, qp["H_O05"] + qp["A_O05"] - (1.0 - (1.0 - qp["H_O05"]) * (1.0 - qp["A_O05"])))
        # Exact independent Poisson BTTS = P(H>=1)*P(A>=1)
        p_btts_exact = qp["H_O05"] * qp["A_O05"]
        matches_detail.append(
            {
                "event_id": m.event_id,
                "league": m.league,
                "league_label": LEAGUE_LABELS.get(m.league, m.league),
                "kickoff_col": m.kickoff_col,
                "home": m.home,
                "away": m.away,
                "home_logo": getattr(m, "home_logo", "") or "",
                "away_logo": getattr(m, "away_logo", "") or "",
                "o1": m.o1,
                "ox": m.ox,
                "o2": m.o2,
                "ou_line": m.ou_line,
                "o_over": m.o_over,
                "o_under": m.o_under,
                "provider": m.provider_name,
                "h_stat": hs,
                "a_stat": as_,
                "h_recent_scores": [f"{gf}-{ga}" for gf, ga in e["h_recent"]],
                "a_recent_scores": [f"{gf}-{ga}" for gf, ga in e["a_recent"]],
                "lam_h": round(e["lam_h"], 2),
                "lam_a": round(e["lam_a"], 2),
                "halves": e["half_data"],
                "probs_summary": {
                    "p1": round(qp["1"] * 100.0, 1),
                    "px": round(qp["X"] * 100.0, 1),
                    "p2": round(qp["2"] * 100.0, 1),
                    "p1x": round(qp["1X"] * 100.0, 1),
                    "px2": round(qp["X2"] * 100.0, 1),
                    "h_o05": round(qp["H_O05"] * 100.0, 1),
                    "h_o15": round(qp["H_O15"] * 100.0, 1),
                    "a_o05": round(qp["A_O05"] * 100.0, 1),
                    "a_o15": round(qp["A_O15"] * 100.0, 1),
                    "o15": round(qp["O15"] * 100.0, 1),
                    "o25": round(qp["O25"] * 100.0, 1),
                    "btts": round(p_btts_exact * 100.0, 1),
                    "p_1h_o05": round(e["half_data"]["probs"]["1H_O05"] * 100.0, 1),
                    "p_2h_o05": round(e["half_data"]["probs"]["2H_O05"] * 100.0, 1),
                    "p_most_2h": round(e["half_data"]["probs"]["MOST_GOALS_2H"] * 100.0, 1),
                    "lam_tot_1h": e["half_data"]["lam_tot_1h"],
                    "lam_tot_2h": e["half_data"]["lam_tot_2h"],
                    "ratio_1h": e["half_data"]["ratio_1h"],
                    "ratio_2h": e["half_data"]["ratio_2h"],
                },
                "all_markets": [
                    {
                        "key": k,
                        "name": MARKET_NAMES[k],
                        "odds": odd,
                        "prob": round(e["qprobs"][k] * 100.0, 1),
                        "impl": round(100.0 / odd, 1),
                        "ev_pct": round((e["qprobs"][k] * odd - 1.0) * 100.0, 1),
                    }
                    for k, odd in e["mkt_odds"].items()
                ],
                "opt_a_leg": {
                    "market_name": MARKET_NAMES[e["best_opt_a"][0]],
                    "odds": e["best_opt_a"][1],
                    "prob": round(e["best_opt_a"][2] * 100.0, 1),
                    "ev_pct": round((e["best_opt_a"][2] * e["best_opt_a"][1] - 1.0) * 100.0, 1),
                }
                if e["best_opt_a"]
                else None,
                "opt_b_pick": None,
                "lineup_alert": e.get("lineup_alert"),
            }
        )

    # Keep all matches sorted strictly chronologically (YYYY-MM-DD HH:MM COL)
    matches_detail.sort(key=lambda item: item["kickoff_col"])

    # Attach same-day partner pairing hint for any match whose primary pick is < 1.50
    for md in matches_detail:
        pk = md.get("opt_a_leg")
        if not pk or float(pk["odds"]) >= 1.50:
            continue
        o1 = float(pk["odds"])
        p1 = float(pk["prob"]) / 100.0
        d1 = md["kickoff_col"][:10]
        best_partner = None
        for other in matches_detail:
            if other["event_id"] == md["event_id"] or other["kickoff_col"][:10] != d1:
                continue
            opk = other.get("opt_a_leg")
            if not opk:
                continue
            o2 = float(opk["odds"])
            p2 = float(opk["prob"]) / 100.0
            c_odd = round(o1 * o2, 2)
            if 1.50 <= c_odd <= 1.98:
                cand = (
                    p1 * p2,
                    -abs(c_odd - 1.65),
                    {
                        "partner_event_id": other["event_id"],
                        "partner_title": f"{other['home']} vs {other['away']}",
                        "partner_pick": opk["market_name"],
                        "partner_odds": round(o2, 2),
                        "combo_odds": c_odd,
                        "combo_prob": round(p1 * p2 * 100.0, 1),
                    },
                )
                if best_partner is None or (cand[0], cand[1]) > (best_partner[0], best_partner[1]):
                    best_partner = cand
        if best_partner:
            md["pair_hint"] = best_partner[2]

    next_global = fetch_next_global_matches(limit=12)
    serial_ladder, serial_ladder_2 = build_dual_serial_ladders(matches_detail, next_global)

    return {
        "apifootball_active": bool(api_key),
        "apifootball_note": api_note,
        "enriched_count": enriched_count,
        "total_matches": len(upcoming),
        "saved_count": saved_count,
        "sharp_picks": sharp_list,
        "parlays_a": parlays_a,
        "opt_b": opt_b,
        "matches": matches_detail,
        "next_global": next_global,
        "serial_ladder": serial_ladder,
        "serial_ladder_2": serial_ladder_2,
        "calibration": calibration,
    }


def build_serial_ladder(
    matches_detail: list[dict],
    next_global: list[dict],
    min_gap_minutes: int = 0,
    max_items: int = 40,
) -> list[dict]:
    """Return single unified chronological queue ordered by kickoff time."""
    primary, _ = build_dual_serial_ladders(matches_detail, next_global, min_gap_minutes=min_gap_minutes, max_items=max_items)
    return primary


def build_dual_serial_ladders(
    matches_detail: list[dict],
    next_global: list[dict],
    min_gap_minutes: int = 0,
    max_items: int = 40,
) -> tuple[list[dict], list[dict]]:
    """Build one unified chronological queue ordered by kickoff time (no split groups)."""
    del next_global  # Unvetted global matches never enter official Series
    pool: dict[str, dict] = {}
    # Every match in Serie uses pure, verified real straight bookmaker markets (no synthetic Bet Builders)

    for m in matches_detail:
        hs = m.get("h_stat") or {}
        as_ = m.get("a_stat") or {}
        if int(hs.get("n", 0)) < 5 or int(as_.get("n", 0)) < 5:
            continue

        # Priority 1: Real verified market from opt_a_leg (1, 1X, 2, X2, H_O15, A_O15, etc.)
        pick = None
        if m.get("opt_a_leg") and float(m["opt_a_leg"].get("prob", 0.0)) >= 58.0 and float(m["opt_a_leg"].get("odds", 0.0)) >= 1.15:
            k_found = next((k for k, v in MARKET_NAMES.items() if v == m["opt_a_leg"]["market_name"]), "1")
            pick = {
                "key": k_found,
                "name": m["opt_a_leg"]["market_name"],
                "market_name": m["opt_a_leg"]["market_name"],
                "odds": float(m["opt_a_leg"]["odds"]),
                "prob": float(m["opt_a_leg"]["prob"]),
                "ev_pct": float(m["opt_a_leg"].get("ev_pct", 0.0)),
            }

        if not pick:
            real_cands = [
                mk
                for mk in (m.get("all_markets") or [])
                if not mk["key"].startswith("BB_")
                and 1.15 <= mk["odds"] <= 2.20
                and mk["prob"] >= 58.0
            ]
            if not real_cands:
                continue
            pick = max(real_cands, key=lambda x: (x["prob"], x["ev_pct"] > 0))

        pk_key = pick.get("key") or next((k for k, v in MARKET_NAMES.items() if v == pick.get("market_name")), "1")
        alt_mk = max(
            (
                mk
                for mk in (m.get("all_markets") or [])
                if not mk["key"].startswith("BB_")
                and mk["key"] != pk_key
                and 1.15 <= mk["odds"] <= 2.20
                and mk["prob"] >= 55.0
            ),
            key=lambda x: x["prob"],
            default=None,
        )
        pool[m["event_id"]] = {
            "event_id": m["event_id"],
            "league": m["league"],
            "league_label": m["league_label"],
            "kickoff_col": m["kickoff_col"],
            "title": f"{m['home']} vs {m['away']}",
            "home": m["home"],
            "away": m["away"],
            "home_logo": m.get("home_logo", ""),
            "away_logo": m.get("away_logo", ""),
            "market": pk_key,
            "market_name": pick.get("market_name") or pick.get("name", ""),
            "odds": round(float(pick["odds"]), 2),
            "prob": float(pick["prob"]),
            "ev_pct": float(pick["ev_pct"]),
            "alt_market_name": alt_mk["name"] if alt_mk else None,
            "alt_odds": round(float(alt_mk["odds"]), 2) if alt_mk else None,
            "alt_prob": float(alt_mk["prob"]) if alt_mk else None,
            "pair_hint": m.get("pair_hint"),
            "o1": m["o1"],
            "ox": m["ox"],
            "o2": m["o2"],
            "lam_h": m["lam_h"],
            "lam_a": m["lam_a"],
            "probs_summary": m.get("probs_summary") or {},
        }

    def _parse_dt(s: str) -> dt.datetime:
        return dt.datetime.strptime(s[:16], "%Y-%m-%d %H:%M")

    def _pick_chain(candidates: list[dict]) -> list[dict]:
        chain: list[dict] = []
        last_dt: dt.datetime | None = None
        for item in candidates:
            try:
                cur_dt = _parse_dt(item["kickoff_col"])
            except Exception:
                continue
            if last_dt is not None:
                gap_min = int((cur_dt - last_dt).total_seconds() // 60)
                if min_gap_minutes > 0 and gap_min < min_gap_minutes:
                    continue
                if gap_min <= 0:
                    gap_txt = "Misma hora"
                elif gap_min < 60:
                    gap_txt = f"+{gap_min}m después"
                else:
                    gap_txt = f"+{gap_min // 60}h {gap_min % 60:02d}m después"
            else:
                gap_txt = "Primer partido"
            last_dt = cur_dt
            chain.append({**item, "step": len(chain) + 1, "gap_label": gap_txt})
            if len(chain) >= max_items:
                break
        return chain

    ordered = sorted(pool.values(), key=lambda x: (x["kickoff_col"], -x["prob"]))
    serie_1 = _pick_chain(ordered)
    return serie_1, []


def run_settle_pipeline() -> dict:
    db = PaperTradingDB()
    pending = db.get_pending()
    pending_user = db.get_pending_user_bets()

    score_cache: dict[tuple[str, str, str], tuple[bool, int, int] | None] = {}
    summary_cache: dict[tuple[str, str, str], dict | None] = {}

    def _get_result(league: str, match_date: str, event_id: str) -> tuple[bool, int, int] | None:
        key = (league, match_date, event_id)
        if key not in score_cache:
            score_cache[key] = fetch_espn_match_result(league, match_date, event_id)
        return score_cache[key]

    def _get_summary(league: str, match_date: str, event_id: str) -> dict | None:
        key = (league, match_date, event_id)
        if key not in summary_cache:
            summary_cache[key] = fetch_espn_match_summary(league, match_date, event_id)
        return summary_cache[key]

    def _evaluate_legs(legs: list[dict]) -> tuple[bool, bool, list[str]]:
        any_lost = False
        all_done = True
        notes = []
        for leg in legs:
            res = _get_result(leg["league"], leg["match_date"], leg["event_id"])
            if res is None or not res[0]:
                all_done = False
                continue
            _, hg, ag = res
            won = grade_market(leg["market"], hg, ag)
            notes.append(f"{leg['market']}:{hg}-{ag}({'W' if won else 'L'})")
            if not won:
                any_lost = True
        return any_lost, all_done, notes

    learnings_generated: list[dict] = []

    def _trigger_learning_analysis(tr_dict: dict) -> None:
        try:
            from post_match_learning import generate_post_match_learning_analysis
            from card_renderer import render_learning_card, png_to_webp_data_url
        except Exception:
            return

        for leg in tr_dict.get("legs", []):
            eid = str(leg.get("event_id", ""))
            lg = str(leg.get("league", ""))
            m_date = str(leg.get("match_date", ""))
            if not eid:
                continue
            summary = _get_summary(lg, m_date, eid)
            if not summary or not summary.get("completed"):
                continue

            an = generate_post_match_learning_analysis(summary, tr_dict)
            try:
                png = render_learning_card(an)
                an["card_webp"] = png_to_webp_data_url(png)
            except Exception:
                an["card_webp"] = ""

            if db.record_post_match_learning(an):
                learnings_generated.append(an)

    settled_now = 0
    for tr in pending:
        any_lost, all_done, notes = _evaluate_legs(tr["legs"])
        if any_lost:
            loss_u = -float(tr["stake_u"])
            db.settle_trade(tr["id"], "LOST", loss_u, " | ".join(notes))
            tr["status"] = "LOST"
            tr["profit_u"] = loss_u
            tr["result_note"] = " | ".join(notes)
            _trigger_learning_analysis(tr)
            settled_now += 1
        elif all_done and notes:
            profit = float(tr["stake_u"]) * (float(tr["odds"]) - 1.0)
            db.settle_trade(tr["id"], "WON", profit, " | ".join(notes))
            tr["status"] = "WON"
            tr["profit_u"] = profit
            tr["result_note"] = " | ".join(notes)
            _trigger_learning_analysis(tr)
            settled_now += 1

    user_settled = 0
    for ub in pending_user:
        any_lost, all_done, notes = _evaluate_legs(ub["legs"])
        if any_lost:
            db.settle_user_bet(ub["id"], ub["user_id"], "LOST", -ub["stake_u"], " | ".join(notes))
            user_settled += 1
        elif all_done and notes:
            profit = ub["stake_u"] * (ub["odds"] - 1.0)
            db.settle_user_bet(ub["id"], ub["user_id"], "WON", profit, " | ".join(notes))
            user_settled += 1

    return {
        "pending_before": len(pending),
        "settled_now": settled_now,
        "still_pending": len(pending) - settled_now,
        "user_settled": user_settled,
        "learnings": learnings_generated,
    }


def cmd_scan(args) -> None:
    leagues = args.leagues.split(",") if args.leagues else DEFAULT_LEAGUES
    print(f"Consultando partidos próximos ({args.days}d, hora Colombia UTC-5) en {len(leagues)} ligas...")
    res = run_scan_pipeline(leagues=leagues, days=args.days, save=args.save)

    if res["apifootball_active"]:
        if res.get("apifootball_note"):
            print(f"Aviso API-Football: {res['apifootball_note']} -> Usando datos y cuotas en vivo de ESPN.")
        else:
            print(f"API-Football activo: {res['enriched_count']}/{res['total_matches']} partidos enriquecidos con Pinnacle/Betfair.")
    else:
        print("Modo gratuito directo (ESPN). Sin APIFOOTBALL_KEY: comparativa multi-casa sharp desactivada.")
    print(f"\nPartidos próximos con cuotas encontrados: {res['total_matches']}")

    tg_lines = ["*BOT APUESTAS - Escaneo Diario*"]
    if res["sharp_picks"]:
        print("\n=== 1. SEÑALES DE VALOR (+EV >= 2% vs Pinnacle/Betfair) [RECOMENDADA] ===")
        tg_lines.append("\n*Valor +EV vs Sharp:*")
        for sp in res["sharp_picks"]:
            print(f"  [{sp['kickoff_col']}] ({sp['league']}) {sp['title']}: {sp['market_name']} @{sp['odds']} ({sp['bookmaker']}) | Prob={sp['prob']}% | EV={sp['ev_pct']:+.2f}%")
            tg_lines.append(f"- {sp['title']}: {sp['market_name']} @{sp['odds']} (EV {sp['ev_pct']:+.1f}%)")

    print(f"\n=== 2. FÓRMULA OPCIÓN A (Combinadas de 2 partidos, 1.50-1.95) [{len(res['parlays_a'])} encontradas] ===")
    for p in res["parlays_a"]:
        tag = "[+EV]" if p["ev_pct"] > 0 else "[OJO: EV<=0 por margen]"
        print(
            f"  [{p['kickoff_col']}] {p['leg1']}\n"
            f"                    + {p['leg2']}\n"
            f"                    => Cuota={p['combo_odds']:.3f} | ProbEst={p['prob_est']}% vs Impl={p['prob_impl']}% | EV_Poisson={p['ev_pct']:+.1f}% {tag}"
        )

    print(f"\n=== 3. FÓRMULA OPCIÓN B (Mismo partido / Bet Builder, 1.20-1.90) [{len(res['opt_b'])} encontrados] ===")
    for b in res["opt_b"]:
        tag = "[+EV]" if b["ev_pct"] > 0 else "[OJO: EV<=0 por margen]"
        print(
            f"  [{b['kickoff_col']}] ({b['league']}) {b['title']}: {b['market_name']} @~{b['odds']:.3f} "
            f"| ProbEst={b['prob_est']}% vs Impl={b['prob_impl']}% | EV_Poisson={b['ev_pct']:+.1f}% {tag}"
        )

    col_matches = [m for m in res["matches"] if m["league"] == "col.1"]
    if col_matches:
        print("\n=== DETALLE LIGA COLOMBIA (col.1, Hora Colombia) ===")
        for m in col_matches:
            hs, as_ = m["h_stat"], m["a_stat"]
            print(
                f"  [{m['kickoff_col']}] {m['home']} (G:{hs['win_pct']*100:.0f}% NoPierde:{hs['unbeaten_pct']*100:.0f}% GF:{hs['gf_avg']:.2f}) "
                f"vs {m['away']} (G:{as_['win_pct']*100:.0f}% NoPierde:{as_['unbeaten_pct']*100:.0f}% GF:{as_['gf_avg']:.2f}) "
                f"| 1X2: {m['o1']:.2f} / {m['ox']:.2f} / {m['o2']:.2f} ({m['provider']})"
            )

    if args.save:
        print(f"\nPaper Trading: {res['saved_count']} nuevas jugadas registradas en paper_trades.db.")

    if args.telegram:
        env = load_env()
        tok = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        cid = env.get("TELEGRAM_CHAT_ID", "").strip()
        if tok and cid:
            if res["parlays_a"]:
                tg_lines.append("\n*Formula Opcion A:*")
                for p in res["parlays_a"][:5]:
                    tg_lines.append(f"- {p['leg1']} + {p['leg2']} = @{p['combo_odds']:.2f}")
            ok = send_telegram_message("\n".join(tg_lines), tok, cid)
            print("Alerta Telegram enviada." if ok else "Error enviando alerta Telegram.")
        else:
            print("Telegram omitido: configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env.")


def cmd_settle(_args) -> None:
    st = run_settle_pipeline()
    if st["pending_before"] == 0:
        print("No hay jugadas pendientes por liquidar.")
    else:
        print(f"Liquidación completada: {st['settled_now']} jugadas actualizadas ({st['still_pending']} aún pendientes).")


def cmd_report(_args) -> None:
    db = PaperTradingDB()
    rep = db.get_summary()
    print("=== REPORTE PAPER TRADING ===")
    print(f"Total: {rep['total_trades']} | Pendientes: {rep['pending']} | Liquidadas: {rep['settled']} (G:{rep['won']} / P:{rep['lost']})")
    print(f"Volumen: {rep['total_staked_u']}u | Ganancia Neta: {rep['total_profit_u']:+.2f}u | ROI: {rep['roi_pct']:+.2f}% | Bankroll: {rep['bankroll_u']:.2f}u")
    if rep["by_strategy"]:
        print("\nPor estrategia:")
        for s, st in rep["by_strategy"].items():
            s_roi = (st["profit"] / st["staked"] * 100.0) if st["staked"] > 0 else 0.0
            print(f"  {s:<16} total={st['total']} pend={st['pending']} G={st['won']} P={st['lost']} net={st['profit']:+.2f}u ROI={s_roi:+.2f}%")
    if rep["recent"]:
        print("\nÚltimas jugadas:")
        for r in rep["recent"][-10:]:
            print(f"  #{r['id']} [{r['match_date']}] {r['strategy']} | {r['title']} | {r['market']} @{r['odds']} | {r['status']} ({r['profit_u']:+.2f}u)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scanner deportivo y simulador Paper Trading (Colombia + Europa)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Escanear partidos próximos y detectar oportunidades")
    p_scan.add_argument("--leagues", help="Lista separada por comas (ej: col.1,eng.1,esp.1)")
    p_scan.add_argument("--days", type=int, default=3, help="Días hacia adelante a consultar (default: 3)")
    p_scan.add_argument("--save", action="store_true", help="Guardar jugadas detectadas en paper_trades.db")
    p_scan.add_argument("--telegram", action="store_true", help="Enviar resumen al bot de Telegram si está configurado")
    p_scan.set_defaults(func=cmd_scan)

    p_settle = sub.add_parser("settle", help="Liquidar jugadas pendientes usando marcadores reales de ESPN")
    p_settle.set_defaults(func=cmd_settle)

    p_rep = sub.add_parser("report", help="Ver resumen del historial de paper trading")
    p_rep.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
