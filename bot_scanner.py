import argparse
import datetime as dt

from paper_db import PaperTradingDB
from providers import (
    LEAGUE_LABELS,
    UpcomingMatch,
    enrich_with_apifootball,
    fetch_espn_match_result,
    fetch_espn_upcoming,
    fetch_recent_history,
    load_env,
    send_telegram_message,
)
from quant_math import (
    calibrate_market_lambdas,
    devig_3,
    estimate_team_lambdas,
    poisson_probs,
    rolling_team_summary,
)

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
    "BB_H_1_O05": "BetBuilder: Local Gana + Local +0.5 goles",
    "BB_H_1_O15": "BetBuilder: Local Gana + Local +1.5 goles",
    "BB_H_1X_O05": "BetBuilder: Local 1X + Local +0.5 goles",
    "BB_H_1X_O15": "BetBuilder: Local 1X + Local +1.5 goles",
    "BB_A_2_O05": "BetBuilder: Visita Gana + Visita +0.5 goles",
    "BB_A_2_O15": "BetBuilder: Visita Gana + Visita +1.5 goles",
    "BB_A_X2_O05": "BetBuilder: Visita X2 + Visita +0.5 goles",
    "BB_A_X2_O15": "BetBuilder: Visita X2 + Visita +1.5 goles",
}


def build_match_markets(m: UpcomingMatch) -> dict[str, float]:
    """Compute available 1X2 odds plus market-calibrated DC, Team Goals, and Bet Builder odds."""
    p1_f, px_f, p2_f = devig_3(m.o1, m.ox, m.o2)
    lam_h_mkt, lam_a_mkt = calibrate_market_lambdas(m.o1, m.ox, m.o2, m.ou_line, m.o_over, m.o_under)
    mp = poisson_probs(lam_h_mkt, lam_a_mkt)

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
        "BB_H_1_O05": from_p(mp["BB_H_1_O05"], 1.10),
        "BB_H_1_O15": from_p(mp["BB_H_1_O15"], 1.10),
        "BB_H_1X_O05": from_p(mp["BB_H_1X_O05"], 1.10),
        "BB_H_1X_O15": from_p(mp["BB_H_1X_O15"], 1.10),
        "BB_A_2_O05": from_p(mp["BB_A_2_O05"], 1.10),
        "BB_A_2_O15": from_p(mp["BB_A_2_O15"], 1.10),
        "BB_A_X2_O05": from_p(mp["BB_A_X2_O05"], 1.10),
        "BB_A_X2_O15": from_p(mp["BB_A_X2_O15"], 1.10),
    }


def grade_market(market: str, hg: int, ag: int) -> bool:
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
        "BB_H_1_O05": hg > ag and hg >= 1,
        "BB_H_1_O15": hg > ag and hg >= 2,
        "BB_H_1X_O05": hg >= ag and hg >= 1,
        "BB_H_1X_O15": hg >= ag and hg >= 2,
        "BB_A_2_O05": ag > hg and ag >= 1,
        "BB_A_2_O15": ag > hg and ag >= 2,
        "BB_A_X2_O05": ag >= hg and ag >= 1,
        "BB_A_X2_O15": ag >= hg and ag >= 2,
    }
    return checks[market]


def evaluate_match(m: UpcomingMatch, team_all: dict, team_home: dict, team_away: dict, lg_hg: dict, lg_ag: dict) -> dict:
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
        qprobs = poisson_probs(lam_h, lam_a)
    else:
        lam_h, lam_a = calibrate_market_lambdas(m.o1, m.ox, m.o2, m.ou_line, m.o_over, m.o_under)
        qprobs = poisson_probs(lam_h, lam_a)

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

    opt_a_valid = [(k, mkt_odds[k], qprobs[k]) for k in opt_a_cands if 1.08 <= mkt_odds[k] <= 1.70]
    best_opt_a = min(opt_a_valid, key=lambda x: abs(x[1] - 1.30)) if opt_a_valid else None

    bb_cands = []
    if h_stat["n"] >= 5 and a_stat["n"] >= 5:
        if h_stat["unbeaten_pct"] >= 0.70 and h_stat["o05_pct"] >= 0.75 and h_stat["gf_avg"] >= 1.2:
            bb_cands.append("BB_H_1X_O05")
        if h_stat["win_pct"] >= 0.55 and h_stat["o05_pct"] >= 0.80 and h_stat["gf_avg"] >= 1.4:
            bb_cands.append("BB_H_1_O05")
        if h_stat["unbeaten_pct"] >= 0.75 and h_stat["o15_pct"] >= 0.50 and h_stat["gf_avg"] >= 1.5 and a_stat["ga_avg"] >= 1.2:
            bb_cands.append("BB_H_1X_O15")
        if a_stat["unbeaten_pct"] >= 0.70 and a_stat["o05_pct"] >= 0.75 and a_stat["gf_avg"] >= 1.2:
            bb_cands.append("BB_A_X2_O05")
        if a_stat["win_pct"] >= 0.55 and a_stat["o05_pct"] >= 0.80 and a_stat["gf_avg"] >= 1.4:
            bb_cands.append("BB_A_2_O05")
    bb_valid = [(k, mkt_odds[k], qprobs[k]) for k in bb_cands if 1.20 <= mkt_odds[k] <= 1.90]
    best_opt_b = min(bb_valid, key=lambda x: abs(x[1] - 1.50)) if bb_valid else None

    return {
        "match": m,
        "h_stat": h_stat,
        "a_stat": a_stat,
        "h_recent": h_recent,
        "a_recent": a_recent,
        "lam_h": lam_h,
        "lam_a": lam_a,
        "mkt_odds": mkt_odds,
        "qprobs": qprobs,
        "sharp_picks": sharp_picks,
        "opt_a_all": opt_a_valid,
        "best_opt_a": best_opt_a,
        "best_opt_b": best_opt_b,
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

    evals = [evaluate_match(m, team_all, team_home, team_away, lg_hg, lg_ag) for m in upcoming]
    db = PaperTradingDB() if save else None
    saved_count = 0

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

    legs_a = [e for e in evals if e["best_opt_a"] is not None]
    parlays_a = []
    used: set[int] = set()
    for i in range(len(legs_a)):
        if i in used:
            continue
        m1 = legs_a[i]["match"]
        k1, o1, p1 = legs_a[i]["best_opt_a"]
        d1 = dt.date.fromisoformat(m1.kickoff_col[:10])
        for j in range(i + 1, len(legs_a)):
            if j in used:
                continue
            m2 = legs_a[j]["match"]
            d2 = dt.date.fromisoformat(m2.kickoff_col[:10])
            if abs((d2 - d1).days) > 3:
                continue
            k2, o2, p2 = legs_a[j]["best_opt_a"]
            combo = round(o1 * o2, 3)
            if 1.20 <= combo <= 1.90:
                used.add(i)
                used.add(j)
                p_combo = p1 * p2
                imp = 1.0 / combo
                ev_est = (p_combo * combo - 1.0) * 100.0
                parlays_a.append(
                    {
                        "kickoff_col": m1.kickoff_col,
                        "title": f"{m1.home} vs {m1.away} + {m2.home} vs {m2.away}",
                        "leg1": f"({m1.league}) {m1.home} vs {m1.away}: {MARKET_NAMES[k1]} @{o1:.2f}",
                        "leg2": f"({m2.league}) {m2.home} vs {m2.away}: {MARKET_NAMES[k2]} @{o2:.2f}",
                        "market_key": f"{k1}+{k2}",
                        "combo_odds": combo,
                        "prob_est": round(p_combo * 100.0, 1),
                        "prob_impl": round(imp * 100.0, 1),
                        "ev_pct": round(ev_est, 1),
                        "legs": [
                            {"event_id": m1.event_id, "league": m1.league, "match_date": m1.match_date, "market": k1},
                            {"event_id": m2.event_id, "league": m2.league, "match_date": m2.match_date, "market": k2},
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
                break

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
        matches_detail.append(
            {
                "event_id": m.event_id,
                "league": m.league,
                "league_label": LEAGUE_LABELS.get(m.league, m.league),
                "kickoff_col": m.kickoff_col,
                "home": m.home,
                "away": m.away,
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
                "opt_b_pick": {
                    "market_name": MARKET_NAMES[e["best_opt_b"][0]],
                    "odds": e["best_opt_b"][1],
                    "prob": round(e["best_opt_b"][2] * 100.0, 1),
                    "ev_pct": round((e["best_opt_b"][2] * e["best_opt_b"][1] - 1.0) * 100.0, 1),
                }
                if e["best_opt_b"]
                else None,
            }
        )

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
    }


def run_settle_pipeline() -> dict:
    db = PaperTradingDB()
    pending = db.get_pending()
    pending_user = db.get_pending_user_bets()

    def _evaluate_legs(legs: list[dict]) -> tuple[bool, bool, list[str]]:
        any_lost = False
        all_done = True
        notes = []
        for leg in legs:
            res = fetch_espn_match_result(leg["league"], leg["match_date"], leg["event_id"])
            if res is None or not res[0]:
                all_done = False
                continue
            _, hg, ag = res
            won = grade_market(leg["market"], hg, ag)
            notes.append(f"{leg['market']}:{hg}-{ag}({'W' if won else 'L'})")
            if not won:
                any_lost = True
        return any_lost, all_done, notes

    settled_now = 0
    for tr in pending:
        any_lost, all_done, notes = _evaluate_legs(tr["legs"])
        if any_lost:
            db.settle_trade(tr["id"], "LOST", -tr["stake_u"], " | ".join(notes))
            settled_now += 1
        elif all_done and notes:
            profit = tr["stake_u"] * (tr["odds"] - 1.0)
            db.settle_trade(tr["id"], "WON", profit, " | ".join(notes))
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

    print(f"\n=== 2. FÓRMULA OPCIÓN A (Combinadas de 2 partidos, 1.20-1.90) [{len(res['parlays_a'])} encontradas] ===")
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
