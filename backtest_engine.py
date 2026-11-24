import csv
import datetime as dt
import glob
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


@dataclass
class MatchRecord:
    league: str
    date: dt.date
    home: str
    away: str
    hg: int
    ag: int
    o1: float
    ox: float
    o2: float
    ou_line: float | None = None
    o_over: float | None = None
    o_under: float | None = None


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_probs(lam_h: float, lam_a: float, max_g: int = 9) -> dict[str, float]:
    """Return exact truncated Poisson match probabilities."""
    ph = [poisson_pmf(i, lam_h) for i in range(max_g + 1)]
    pa = [poisson_pmf(j, lam_a) for j in range(max_g + 1)]

    p_h_win = 0.0
    p_draw = 0.0
    p_a_win = 0.0
    p_over15 = 0.0
    p_over25 = 0.0
    p_h_o05_and_1x = 0.0
    p_h_o15_and_1x = 0.0
    p_h_o05_and_1 = 0.0
    p_h_o15_and_1 = 0.0
    p_a_o05_and_x2 = 0.0
    p_a_o15_and_x2 = 0.0
    p_a_o05_and_2 = 0.0
    p_a_o15_and_2 = 0.0

    for i in range(max_g + 1):
        for j in range(max_g + 1):
            p = ph[i] * pa[j]
            tot = i + j
            if tot >= 2:
                p_over15 += p
            if tot >= 3:
                p_over25 += p
            if i > j:
                p_h_win += p
                if i >= 1:
                    p_h_o05_and_1 += p
                    p_h_o05_and_1x += p
                if i >= 2:
                    p_h_o15_and_1 += p
                    p_h_o15_and_1x += p
            elif i == j:
                p_draw += p
                if i >= 1:
                    p_h_o05_and_1x += p
                if i >= 2:
                    p_h_o15_and_1x += p
                if j >= 1:
                    p_a_o05_and_x2 += p
                if j >= 2:
                    p_a_o15_and_x2 += p
            else:
                p_a_win += p
                if j >= 1:
                    p_a_o05_and_2 += p
                    p_a_o05_and_x2 += p
                if j >= 2:
                    p_a_o15_and_2 += p
                    p_a_o15_and_x2 += p

    p_h_o05 = 1.0 - ph[0]
    p_h_o15 = 1.0 - ph[0] - ph[1]
    p_a_o05 = 1.0 - pa[0]
    p_a_o15 = 1.0 - pa[0] - pa[1]

    return {
        "1": p_h_win,
        "X": p_draw,
        "2": p_a_win,
        "1X": p_h_win + p_draw,
        "X2": p_a_win + p_draw,
        "O15": p_over15,
        "O25": p_over25,
        "H_O05": p_h_o05,
        "H_O15": p_h_o15,
        "A_O05": p_a_o05,
        "A_O15": p_a_o15,
        "BB_H_1_O05": p_h_o05_and_1,
        "BB_H_1_O15": p_h_o15_and_1,
        "BB_H_1X_O05": p_h_o05_and_1x,
        "BB_H_1X_O15": p_h_o15_and_1x,
        "BB_A_2_O05": p_a_o05_and_2,
        "BB_A_2_O15": p_a_o15_and_2,
        "BB_A_X2_O05": p_a_o05_and_x2,
        "BB_A_X2_O15": p_a_o15_and_x2,
    }


def calibrate_market_lambdas(
    o1: float, ox: float, o2: float, ou_line: float | None, o_over: float | None, o_under: float | None, default_tot: float = 2.55
) -> tuple[float, float]:
    """Find (lam_h, lam_a) matching fair 1X2 ratio and fair Over/Under line."""
    inv_sum = 1.0 / o1 + 1.0 / ox + 1.0 / o2
    p1_mkt = (1.0 / o1) / inv_sum
    p2_mkt = (1.0 / o2) / inv_sum

    if ou_line in (1.5, 2.5) and o_over and o_under and o_over > 1.01 and o_under > 1.01:
        ou_inv = 1.0 / o_over + 1.0 / o_under
        p_over_mkt = (1.0 / o_over) / ou_inv
    else:
        p_over_mkt = None

    # Coordinate search over (total_goals, home_share)
    tot = default_tot
    share = p1_mkt / max(p1_mkt + p2_mkt, 1e-6)
    share = max(0.15, min(0.85, share))

    if p_over_mkt is not None:
        lo, hi = 1.0, 5.2
        key = "O15" if ou_line == 1.5 else "O25"
        for _ in range(16):
            mid = 0.5 * (lo + hi)
            probs = poisson_probs(mid * share, mid * (1.0 - share))
            if probs[key] < p_over_mkt:
                lo = mid
            else:
                hi = mid
        tot = 0.5 * (lo + hi)

    target_diff = p1_mkt - p2_mkt
    lo_s, hi_s = 0.12, 0.88
    for _ in range(16):
        mid_s = 0.5 * (lo_s + hi_s)
        probs = poisson_probs(tot * mid_s, tot * (1.0 - mid_s))
        diff = probs["1"] - probs["2"]
        if diff < target_diff:
            lo_s = mid_s
        else:
            hi_s = mid_s
    share = 0.5 * (lo_s + hi_s)

    if p_over_mkt is not None:
        lo, hi = 1.0, 5.2
        key = "O15" if ou_line == 1.5 else "O25"
        for _ in range(12):
            mid = 0.5 * (lo + hi)
            probs = poisson_probs(mid * share, mid * (1.0 - share))
            if probs[key] < p_over_mkt:
                lo = mid
            else:
                hi = mid
        tot = 0.5 * (lo + hi)

    return tot * share, tot * (1.0 - share)


def parse_date(s: str) -> dt.date:
    s = s.strip()
    if len(s) >= 10 and s[4] == "-":
        return dt.date.fromisoformat(s[:10])
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unknown date: {s}")


def safe_float(val: str | None) -> float | None:
    if not val:
        return None
    try:
        v = float(val)
        return v if v > 1.01 else None
    except ValueError:
        return None


def load_football_data_europe() -> list[MatchRecord]:
    records = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*_*.csv"))):
        fname = os.path.basename(path)
        league = fname.split("_")[0]
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get("HomeTeam") or not row.get("FTHG"):
                    continue
                try:
                    d = parse_date(row["Date"])
                    hg = int(row["FTHG"])
                    ag = int(row["FTAG"])
                except Exception:
                    continue
                o1 = safe_float(row.get("AvgCH")) or safe_float(row.get("B365CH")) or safe_float(row.get("AvgH")) or safe_float(row.get("B365H"))
                ox = safe_float(row.get("AvgCD")) or safe_float(row.get("B365CD")) or safe_float(row.get("AvgD")) or safe_float(row.get("B365D"))
                o2 = safe_float(row.get("AvgCA")) or safe_float(row.get("B365CA")) or safe_float(row.get("AvgA")) or safe_float(row.get("B365A"))
                if not (o1 and ox and o2):
                    continue
                o_over = safe_float(row.get("AvgC>2.5")) or safe_float(row.get("B365C>2.5")) or safe_float(row.get("Avg>2.5")) or safe_float(row.get("B365>2.5"))
                o_under = safe_float(row.get("AvgC<2.5")) or safe_float(row.get("B365C<2.5")) or safe_float(row.get("Avg<2.5")) or safe_float(row.get("B365<2.5"))
                records.append(MatchRecord(league, d, row["HomeTeam"].strip(), row["AwayTeam"].strip(), hg, ag, o1, ox, o2, 2.5 if (o_over and o_under) else None, o_over, o_under))
    return records


def load_south_america_csv() -> list[MatchRecord]:
    records = []
    for code in ("ARG", "BRA"):
        path = os.path.join(DATA_DIR, f"{code}.csv")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get("Home") or not row.get("HG"):
                    continue
                try:
                    d = parse_date(row["Date"])
                    hg = int(row["HG"])
                    ag = int(row["AG"])
                except Exception:
                    continue
                if d.year < 2022:
                    continue
                o1 = safe_float(row.get("AvgCH")) or safe_float(row.get("B365CH"))
                ox = safe_float(row.get("AvgCD")) or safe_float(row.get("B365CD"))
                o2 = safe_float(row.get("AvgCA")) or safe_float(row.get("B365CA"))
                if not (o1 and ox and o2):
                    continue
                records.append(MatchRecord(code, d, row["Home"].strip(), row["Away"].strip(), hg, ag, o1, ox, o2))
    return records


def load_colombia_espn() -> list[MatchRecord]:
    path = os.path.join(DATA_DIR, "colombia_espn.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        events = json.load(f)
    records = []
    for ev in events:
        odds_list = ev.get("odds_list") or []
        if not odds_list:
            continue
        # Prefer DraftKings or ESPN BET
        chosen = next((o for o in odds_list if o.get("h_close") and o.get("d_close") and o.get("a_close")), None)
        if not chosen:
            continue
        o1, ox, o2 = chosen["h_close"], chosen["d_close"], chosen["a_close"]
        if not (o1 > 1.01 and ox > 1.01 and o2 > 1.01):
            continue
        d = parse_date(ev["date"])
        records.append(
            MatchRecord(
                "COL",
                d,
                ev["home"],
                ev["away"],
                int(ev["hg"]),
                int(ev["ag"]),
                o1,
                ox,
                o2,
                chosen.get("ou_line"),
                chosen.get("over_close"),
                chosen.get("under_close"),
            )
        )
    return records


def market_odds_for_match(m: MatchRecord) -> dict[str, tuple[float, bool]]:
    """Return dict of market_key -> (bookmaker_odds, did_win)."""
    inv_sum = 1.0 / m.o1 + 1.0 / m.ox + 1.0 / m.o2
    p1_f = (1.0 / m.o1) / inv_sum
    px_f = (1.0 / m.ox) / inv_sum
    p2_f = (1.0 / m.o2) / inv_sum

    lam_h_mkt, lam_a_mkt = calibrate_market_lambdas(m.o1, m.ox, m.o2, m.ou_line, m.o_over, m.o_under)
    mp = poisson_probs(lam_h_mkt, lam_a_mkt)

    # Double chance vig ~5.5%, Team goals vig ~6.5%, Bet Builder vig ~10%
    dc_vig = 1.055
    tg_vig = 1.065
    bb_vig = 1.10

    def odds_from_p(p: float, vig: float) -> float:
        return round(max(1.01, min(35.0, 1.0 / max(p * vig, 0.01))), 3)

    res = {
        "1": (m.o1, m.hg > m.ag),
        "2": (m.o2, m.ag > m.hg),
        "1X": (odds_from_p(p1_f + px_f, dc_vig), m.hg >= m.ag),
        "X2": (odds_from_p(p2_f + px_f, dc_vig), m.ag >= m.hg),
        "H_O05": (odds_from_p(mp["H_O05"], tg_vig), m.hg >= 1),
        "H_O15": (odds_from_p(mp["H_O15"], tg_vig), m.hg >= 2),
        "A_O05": (odds_from_p(mp["A_O05"], tg_vig), m.ag >= 1),
        "A_O15": (odds_from_p(mp["A_O15"], tg_vig), m.ag >= 2),
        "BB_H_1_O05": (odds_from_p(mp["BB_H_1_O05"], bb_vig), (m.hg > m.ag and m.hg >= 1)),
        "BB_H_1_O15": (odds_from_p(mp["BB_H_1_O15"], bb_vig), (m.hg > m.ag and m.hg >= 2)),
        "BB_H_1X_O05": (odds_from_p(mp["BB_H_1X_O05"], bb_vig), (m.hg >= m.ag and m.hg >= 1)),
        "BB_H_1X_O15": (odds_from_p(mp["BB_H_1X_O15"], bb_vig), (m.hg >= m.ag and m.hg >= 2)),
        "BB_A_2_O05": (odds_from_p(mp["BB_A_2_O05"], bb_vig), (m.ag > m.hg and m.ag >= 1)),
        "BB_A_2_O15": (odds_from_p(mp["BB_A_2_O15"], bb_vig), (m.ag > m.hg and m.ag >= 2)),
        "BB_A_X2_O05": (odds_from_p(mp["BB_A_X2_O05"], bb_vig), (m.ag >= m.hg and m.ag >= 1)),
        "BB_A_X2_O15": (odds_from_p(mp["BB_A_X2_O15"], bb_vig), (m.ag >= m.hg and m.ag >= 2)),
    }
    return res


def run_league_backtest(matches: list[MatchRecord], league_name: str, allow_team_goals: bool = True) -> dict:
    matches = sorted(matches, key=lambda x: (x.date, x.home, x.away))

    # Rolling team history (all matches + home/away split)
    team_all = defaultdict(list)   # list of (gf, ga)
    team_home = defaultdict(list)  # list of (gf, ga)
    team_away = defaultdict(list)  # list of (gf, ga)
    league_hg = defaultdict(list)
    league_ag = defaultdict(list)

    # Candidate legs per match for Option A (2 different matches) and Option B (same match)
    legs_by_strategy = defaultdict(list)  # strat -> list of (date, match_id, market_key, odds, won)
    bets_by_strategy = defaultdict(list)  # strat -> list of (date, odds, won)

    for idx, m in enumerate(matches):
        h_all = team_all[(m.league, m.home)]
        a_all = team_all[(m.league, m.away)]
        h_hm = team_home[(m.league, m.home)]
        a_aw = team_away[(m.league, m.away)]
        lg_h_hist = league_hg[m.league]
        lg_a_hist = league_ag[m.league]

        if len(h_all) >= 6 and len(a_all) >= 6 and len(h_hm) >= 3 and len(a_aw) >= 3 and len(lg_h_hist) >= 30:
            mkt = market_odds_for_match(m)

            # Simple rolling stats (last 10 overall)
            def stats(hist):
                sub = hist[-10:]
                n = len(sub)
                wins = sum(1 for gf, ga in sub if gf > ga)
                unbeaten = sum(1 for gf, ga in sub if gf >= ga)
                o05 = sum(1 for gf, _ in sub if gf >= 1)
                o15 = sum(1 for gf, _ in sub if gf >= 2)
                gf_avg = sum(gf for gf, _ in sub) / n
                ga_avg = sum(ga for _, ga in sub) / n
                return wins / n, unbeaten / n, o05 / n, o15 / n, gf_avg, ga_avg

            hw, hub, ho05, ho15, hgf, hga = stats(h_all)
            aw, aub, ao05, ao15, agf, aga = stats(a_all)

            # Quant Poisson model (shrunk home/away attack & defense over last 12 home/away)
            lg_h = sum(lg_h_hist[-200:]) / len(lg_h_hist[-200:])
            lg_a = sum(lg_a_hist[-200:]) / len(lg_a_hist[-200:])
            w_prior = 4.0

            h_sub = h_hm[-12:]
            a_sub = a_aw[-12:]
            h_att = (sum(gf for gf, _ in h_sub) + w_prior * lg_h) / (len(h_sub) + w_prior) / lg_h
            h_def = (sum(ga for _, ga in h_sub) + w_prior * lg_a) / (len(h_sub) + w_prior) / lg_a
            a_att = (sum(gf for gf, _ in a_sub) + w_prior * lg_a) / (len(a_sub) + w_prior) / lg_a
            a_def = (sum(ga for _, ga in a_sub) + w_prior * lg_h) / (len(a_sub) + w_prior) / lg_h

            lam_h = max(0.25, min(3.5, lg_h * h_att * a_def))
            lam_a = max(0.25, min(3.5, lg_a * a_att * h_def))
            qprobs = poisson_probs(lam_h, lam_a)

            # --- S0: Pure Real-Odds 1X2/DC Naive 2-Match Parlay (no team-goal odds estimation) ---
            s0_cands = []
            if hw >= 0.50 and hw - aw >= 0.15 and hgf >= 1.3:
                s0_cands.append("1")
            if hub >= 0.70 and hgf >= 1.0:
                s0_cands.append("1X")
            if aw >= 0.50 and aw - hw >= 0.15 and agf >= 1.3:
                s0_cands.append("2")
            if aub >= 0.70 and agf >= 1.0:
                s0_cands.append("X2")
            s0_valid = [(k, mkt[k][0], mkt[k][1]) for k in s0_cands if 1.08 <= mkt[k][0] <= 1.70]
            if s0_valid:
                best0 = min(s0_valid, key=lambda x: abs(x[1] - 1.30))
                legs_by_strategy["S0_OptA_Naive_1X2_DC_Only"].append((m.date, idx, best0[0], best0[1], best0[2]))

            # --- S1: Naive formula (person's description) ---
            # Single-leg candidates for Option A (odds 1.08..1.70 so 2 legs land in 1.20..1.90)
            s1_cands = list(s0_cands)
            if allow_team_goals:
                if ho05 >= 0.75 and hgf >= 1.2 and aga >= 0.9:
                    s1_cands.append("H_O05")
                if ho15 >= 0.45 and hgf >= 1.5 and aga >= 1.2:
                    s1_cands.append("H_O15")
                if ao05 >= 0.75 and agf >= 1.2 and hga >= 0.9:
                    s1_cands.append("A_O05")
                if ao15 >= 0.45 and agf >= 1.5 and hga >= 1.2:
                    s1_cands.append("A_O15")

            s1_valid = [(k, mkt[k][0], mkt[k][1]) for k in s1_cands if 1.08 <= mkt[k][0] <= 1.70]
            if s1_valid:
                best = min(s1_valid, key=lambda x: abs(x[1] - 1.30))
                legs_by_strategy["S1_OptA_Naive_2Match"].append((m.date, idx, best[0], best[1], best[2]))

            # S1 Option B: Same-match Bet Builder
            if allow_team_goals:
                bb_cands = []
                if hub >= 0.70 and ho05 >= 0.75 and hgf >= 1.2:
                    bb_cands.append("BB_H_1X_O05")
                if hw >= 0.55 and ho05 >= 0.80 and hgf >= 1.4:
                    bb_cands.append("BB_H_1_O05")
                if hub >= 0.75 and ho15 >= 0.50 and hgf >= 1.5 and aga >= 1.2:
                    bb_cands.append("BB_H_1X_O15")
                if aub >= 0.70 and ao05 >= 0.75 and agf >= 1.2:
                    bb_cands.append("BB_A_X2_O05")
                if aw >= 0.55 and ao05 >= 0.80 and agf >= 1.4:
                    bb_cands.append("BB_A_2_O05")
                bb_valid = [(k, mkt[k][0], mkt[k][1]) for k in bb_cands if 1.20 <= mkt[k][0] <= 1.90]
                if bb_valid:
                    best_bb = min(bb_valid, key=lambda x: abs(x[1] - 1.50))
                    bets_by_strategy["S1_OptB_Naive_BetBuilder"].append((m.date, best_bb[1], best_bb[2]))

            # --- S2: Strict Naive (higher thresholds, tighter odds 1.25-1.65) ---
            s2_cands = []
            if hw >= 0.60 and hw - aw >= 0.25 and hgf >= 1.5:
                s2_cands.append("1")
            if hub >= 0.80 and hgf >= 1.2:
                s2_cands.append("1X")
            if aub >= 0.80 and agf >= 1.2:
                s2_cands.append("X2")
            if allow_team_goals:
                if ho05 >= 0.85 and hgf >= 1.4 and aga >= 1.0:
                    s2_cands.append("H_O05")
                if ao05 >= 0.85 and agf >= 1.4 and hga >= 1.0:
                    s2_cands.append("A_O05")
            s2_valid = [(k, mkt[k][0], mkt[k][1]) for k in s2_cands if 1.12 <= mkt[k][0] <= 1.45]
            if s2_valid:
                best2 = min(s2_valid, key=lambda x: abs(x[1] - 1.25))
                legs_by_strategy["S2_OptA_Strict_2Match"].append((m.date, idx, best2[0], best2[1], best2[2]))

            # --- S3: Quant Poisson Single Value (+EV > 3%) ---
            allowed_keys = ["1", "2", "1X", "X2"] + (["H_O05", "H_O15", "A_O05", "A_O15"] if allow_team_goals else [])
            ev_legs = []
            for k in allowed_keys:
                odds, won = mkt[k]
                ev = qprobs[k] * odds - 1.0
                if ev >= 0.03 and 1.15 <= odds <= 2.50:
                    ev_legs.append((k, odds, won, ev))
            if ev_legs:
                best_ev = max(ev_legs, key=lambda x: x[3])
                bets_by_strategy["S3_Quant_Poisson_Single_EV"].append((m.date, best_ev[1], best_ev[2]))

            # --- S4: Quant Option A (2-match parlay of +EV legs in 1.20..1.90) ---
            ev_parlay_legs = [x for x in ev_legs if 1.08 <= x[1] <= 1.60]
            if ev_parlay_legs:
                best_p = max(ev_parlay_legs, key=lambda x: x[3])
                legs_by_strategy["S4_OptA_Quant_EV_2Match"].append((m.date, idx, best_p[0], best_p[1], best_p[2]))

            # --- S5: Quant Option B (Bet Builder +EV > 3% in 1.20..1.90) ---
            if allow_team_goals:
                bb_keys = ["BB_H_1_O05", "BB_H_1_O15", "BB_H_1X_O05", "BB_H_1X_O15", "BB_A_2_O05", "BB_A_2_O15", "BB_A_X2_O05", "BB_A_X2_O15"]
                ev_bb = []
                for k in bb_keys:
                    odds, won = mkt[k]
                    ev = qprobs[k] * odds - 1.0
                    if ev >= 0.03 and 1.20 <= odds <= 1.90:
                        ev_bb.append((k, odds, won, ev))
                if ev_bb:
                    best_ebb = max(ev_bb, key=lambda x: x[3])
                    bets_by_strategy["S5_OptB_Quant_EV_BetBuilder"].append((m.date, best_ebb[1], best_ebb[2]))

        # Update rolling stats AFTER evaluating match
        team_all[(m.league, m.home)].append((m.hg, m.ag))
        team_all[(m.league, m.away)].append((m.ag, m.hg))
        team_home[(m.league, m.home)].append((m.hg, m.ag))
        team_away[(m.league, m.away)].append((m.ag, m.hg))
        league_hg[m.league].append(m.hg)
        league_ag[m.league].append(m.ag)

    # Pair Option A legs into 2-match parlays within <= 3 days, odds in [1.20, 1.90]
    for sname, legs in legs_by_strategy.items():
        used = set()
        for i in range(len(legs)):
            if i in used:
                continue
            d1, id1, _, o1, w1 = legs[i]
            for j in range(i + 1, len(legs)):
                if j in used:
                    continue
                d2, id2, _, o2, w2 = legs[j]
                if (d2 - d1).days > 3:
                    break
                combo = round(o1 * o2, 3)
                lo_b, hi_b = (1.25, 1.65) if "Strict" in sname else (1.20, 1.90)
                if lo_b <= combo <= hi_b:
                    used.add(i)
                    used.add(j)
                    bets_by_strategy[sname].append((d2, combo, w1 and w2))
                    break

    return {sname: summarize_bets(bets) for sname, bets in sorted(bets_by_strategy.items())}


def summarize_bets(bets: list[tuple[dt.date, float, bool]]) -> dict:
    n = len(bets)
    if n == 0:
        return {"bets": 0, "win_rate": 0.0, "avg_odds": 0.0, "roi": 0.0, "profit_u": 0.0, "max_dd_pct": 0.0, "z_score": 0.0}

    wins = sum(1 for _, _, w in bets if w)
    avg_odds = sum(o for _, o, _ in bets) / n
    profits = [(o - 1.0) if w else -1.0 for _, o, w in bets]
    total_profit = sum(profits)
    roi = (total_profit / n) * 100.0

    # Bankroll with 2% fixed stake of initial 100u (flat 2u per bet)
    bank = 100.0
    peak = 100.0
    max_dd = 0.0
    for p in profits:
        bank += 2.0 * p
        if bank > peak:
            peak = bank
        dd = (peak - bank) / peak * 100.0 if peak > 0 else 100.0
        if dd > max_dd:
            max_dd = dd

    # Z-score of ROI under flat 1u betting
    mean_p = total_profit / n
    var_p = sum((p - mean_p) ** 2 for p in profits) / max(n - 1, 1)
    se = math.sqrt(var_p / n) if var_p > 0 else 1.0
    z = mean_p / se if se > 0 else 0.0

    return {
        "bets": n,
        "win_rate": round(wins / n * 100.0, 2),
        "avg_odds": round(avg_odds, 3),
        "roi": round(roi, 2),
        "profit_u": round(total_profit, 2),
        "final_bank_100": round(bank, 2),
        "max_dd_pct": round(max_dd, 2),
        "z_score": round(z, 2),
    }


def main() -> None:
    eu = load_football_data_europe()
    sa = load_south_america_csv()
    col = load_colombia_espn()

    print(f"Loaded matches -> Europe Top5: {len(eu)}, ARG+BRA: {len(sa)}, Colombia: {len(col)}")

    groups = {
        "Colombia Primera A (2024-2026)": (col, True),
        "Europe Top 5 Combined (22/23-26/27)": (eu, True),
        "Argentina + Brazil (2022-2026, 1X2/DC only)": (sa, False),
    }

    # Also test each Top-5 European league individually for consistency
    for lg_code in ["E0", "SP1", "I1", "D1", "F1"]:
        sub = [m for m in eu if m.league == lg_code]
        groups[f"League {lg_code}"] = (sub, True)

    all_results = {}
    for gname, (ms, allow_tg) in groups.items():
        if not ms:
            print(f"\n=== {gname}: NO DATA ===")
            continue
        res = run_league_backtest(ms, gname, allow_team_goals=allow_tg)
        all_results[gname] = res
        print(f"\n=== {gname} ({len(ms)} matches) ===")
        print(f"{'Strategy':<30} {'Bets':>6} {'Win%':>7} {'Odds':>6} {'ROI%':>7} {'Profit(u)':>10} {'Bank(100)':>10} {'MaxDD%':>8} {'Z':>6}")
        for sname, st in res.items():
            print(
                f"{sname:<30} {st['bets']:>6} {st['win_rate']:>6.1f}% {st['avg_odds']:>6.3f} "
                f"{st['roi']:>+6.2f}% {st['profit_u']:>+10.2f} {st.get('final_bank_100', 100):>10.2f} "
                f"{st['max_dd_pct']:>7.1f}% {st['z_score']:>+6.2f}"
            )

    out_json = os.path.join(BASE_DIR, "backtest_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved full summary to {out_json}")


if __name__ == "__main__":
    main()
