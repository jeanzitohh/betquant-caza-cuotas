import math


def american_to_decimal(odds: float | str | None) -> float | None:
    """Convert American odds (e.g. -200, '+150') to decimal odds."""
    if odds is None:
        return None
    try:
        val = float(str(odds).replace("+", "").strip())
    except ValueError:
        return None
    if val == 0:
        return None
    if val > 0:
        return round(1.0 + val / 100.0, 4)
    return round(1.0 + 100.0 / abs(val), 4)


def devig_3(o1: float, ox: float, o2: float) -> tuple[float, float, float]:
    """Remove proportional bookmaker margin from 1X2 decimal odds."""
    s = 1.0 / o1 + 1.0 / ox + 1.0 / o2
    return (1.0 / o1) / s, (1.0 / ox) / s, (1.0 / o2) / s


def devig_2(oa: float, ob: float) -> tuple[float, float]:
    """Remove proportional bookmaker margin from 2-way decimal odds."""
    s = 1.0 / oa + 1.0 / ob
    return (1.0 / oa) / s, (1.0 / ob) / s


def overround_3(o1: float, ox: float, o2: float) -> float:
    """Return bookmaker overround (e.g. 1.06 means ~6% margin)."""
    return 1.0 / o1 + 1.0 / ox + 1.0 / o2


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_probs(lam_h: float, lam_a: float, max_g: int = 9) -> dict[str, float]:
    """Compute single, double-chance, team-goal, and Bet Builder joint probabilities."""
    ph = [poisson_pmf(i, lam_h) for i in range(max_g + 1)]
    pa = [poisson_pmf(j, lam_a) for j in range(max_g + 1)]

    p_h_win = p_draw = p_a_win = 0.0
    p_over15 = p_over25 = 0.0
    p_h_o05_1 = p_h_o15_1 = p_h_o05_1x = p_h_o15_1x = 0.0
    p_a_o05_2 = p_a_o15_2 = p_a_o05_x2 = p_a_o15_x2 = 0.0
    p_h_t15_1 = p_h_t15_1x = p_a_t15_2 = p_a_t15_x2 = 0.0

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
                    p_h_o05_1 += p
                    p_h_o05_1x += p
                if i >= 2:
                    p_h_o15_1 += p
                    p_h_o15_1x += p
                if tot >= 2:
                    p_h_t15_1 += p
                    p_h_t15_1x += p
            elif i == j:
                p_draw += p
                if i >= 1:
                    p_h_o05_1x += p
                if i >= 2:
                    p_h_o15_1x += p
                if j >= 1:
                    p_a_o05_x2 += p
                if j >= 2:
                    p_a_o15_x2 += p
                if tot >= 2:
                    p_h_t15_1x += p
                    p_a_t15_x2 += p
            else:
                p_a_win += p
                if j >= 1:
                    p_a_o05_2 += p
                    p_a_o05_x2 += p
                if j >= 2:
                    p_a_o15_2 += p
                    p_a_o15_x2 += p
                if tot >= 2:
                    p_a_t15_2 += p
                    p_a_t15_x2 += p

    return {
        "1": p_h_win,
        "X": p_draw,
        "2": p_a_win,
        "1X": p_h_win + p_draw,
        "X2": p_a_win + p_draw,
        "O15": p_over15,
        "O25": p_over25,
        "H_O05": 1.0 - ph[0],
        "H_O15": 1.0 - ph[0] - ph[1],
        "A_O05": 1.0 - pa[0],
        "A_O15": 1.0 - pa[0] - pa[1],
        "BB_H_1_O05": p_h_o05_1,
        "BB_H_1_O15": p_h_o15_1,
        "BB_H_1X_O05": p_h_o05_1x,
        "BB_H_1X_O15": p_h_o15_1x,
        "BB_H_1_T15": p_h_t15_1,
        "BB_H_1X_T15": p_h_t15_1x,
        "BB_A_2_O05": p_a_o05_2,
        "BB_A_2_O15": p_a_o15_2,
        "BB_A_X2_O05": p_a_o05_x2,
        "BB_A_X2_O15": p_a_o15_x2,
        "BB_A_2_T15": p_a_t15_2,
        "BB_A_X2_T15": p_a_t15_x2,
    }


def calibrate_market_lambdas(
    o1: float,
    ox: float,
    o2: float,
    ou_line: float | None = None,
    o_over: float | None = None,
    o_under: float | None = None,
    default_tot: float = 2.55,
) -> tuple[float, float]:
    """Invert fair 1X2 and Over/Under odds into market-implied team scoring rates."""
    p1_mkt, _, p2_mkt = devig_3(o1, ox, o2)
    p_over_mkt = None
    if ou_line in (1.5, 2.5) and o_over and o_under and o_over > 1.01 and o_under > 1.01:
        p_over_mkt, _ = devig_2(o_over, o_under)

    tot = default_tot
    share = max(0.15, min(0.85, p1_mkt / max(p1_mkt + p2_mkt, 1e-6)))
    ou_key = "O15" if ou_line == 1.5 else "O25"

    def fit_total(cur_share: float) -> float:
        lo, hi = 1.0, 5.2
        for _ in range(14):
            mid = 0.5 * (lo + hi)
            if poisson_probs(mid * cur_share, mid * (1.0 - cur_share))[ou_key] < p_over_mkt:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    if p_over_mkt is not None:
        tot = fit_total(share)

    target_diff = p1_mkt - p2_mkt
    lo_s, hi_s = 0.12, 0.88
    for _ in range(14):
        mid_s = 0.5 * (lo_s + hi_s)
        pr = poisson_probs(tot * mid_s, tot * (1.0 - mid_s))
        if (pr["1"] - pr["2"]) < target_diff:
            lo_s = mid_s
        else:
            hi_s = mid_s
    share = 0.5 * (lo_s + hi_s)

    if p_over_mkt is not None:
        tot = fit_total(share)

    return tot * share, tot * (1.0 - share)


def estimate_team_lambdas(
    home_split: list[tuple[int, int]],
    away_split: list[tuple[int, int]],
    lg_avg_h: float,
    lg_avg_a: float,
    prior_w: float = 4.0,
) -> tuple[float, float]:
    """Compute Bayesian-shrunk Poisson attack/defense expected goals."""
    h_sub = home_split[-12:]
    a_sub = away_split[-12:]
    h_att = (sum(gf for gf, _ in h_sub) + prior_w * lg_avg_h) / (len(h_sub) + prior_w) / lg_avg_h
    h_def = (sum(ga for _, ga in h_sub) + prior_w * lg_avg_a) / (len(h_sub) + prior_w) / lg_avg_a
    a_att = (sum(gf for gf, _ in a_sub) + prior_w * lg_avg_a) / (len(a_sub) + prior_w) / lg_avg_a
    a_def = (sum(ga for _, ga in a_sub) + prior_w * lg_avg_h) / (len(a_sub) + prior_w) / lg_avg_h

    lam_h = max(0.25, min(3.5, lg_avg_h * h_att * a_def))
    lam_a = max(0.25, min(3.5, lg_avg_a * a_att * h_def))
    return lam_h, lam_a


def rolling_team_summary(hist: list[tuple[int, int]], window: int = 10) -> dict[str, float]:
    """Compute win%, unbeaten%, +0.5%, +1.5%, total +1.5%, GF avg, GA avg over recent matches."""
    sub = hist[-window:]
    n = len(sub)
    if n == 0:
        return {"n": 0, "win_pct": 0.0, "unbeaten_pct": 0.0, "o05_pct": 0.0, "o15_pct": 0.0, "tot_o15_pct": 0.0, "gf_avg": 0.0, "ga_avg": 0.0}
    return {
        "n": n,
        "win_pct": sum(1 for gf, ga in sub if gf > ga) / n,
        "unbeaten_pct": sum(1 for gf, ga in sub if gf >= ga) / n,
        "o05_pct": sum(1 for gf, _ in sub if gf >= 1) / n,
        "o15_pct": sum(1 for gf, _ in sub if gf >= 2) / n,
        "tot_o15_pct": sum(1 for gf, ga in sub if (gf + ga) >= 2) / n,
        "gf_avg": sum(gf for gf, _ in sub) / n,
        "ga_avg": sum(ga for _, ga in sub) / n,
    }


def half_time_breakdown(
    lam_h: float,
    lam_a: float,
    h_1h_ratio: float = 0.44,
    a_1h_ratio: float = 0.44,
) -> dict:
    """
    Model 1st Half (1T) and 2nd Half (2T) scoring intensities and market probabilities.
    Soccer empirical benchmark: ~44% of match goals occur in 1H, ~56% in 2H.
    """
    r_h1 = max(0.30, min(0.60, float(h_1h_ratio)))
    r_a1 = max(0.30, min(0.60, float(a_1h_ratio)))
    r_h2 = 1.0 - r_h1
    r_a2 = 1.0 - r_a1

    lam_h1 = max(0.05, lam_h * r_h1)
    lam_a1 = max(0.05, lam_a * r_a1)
    lam_tot1 = lam_h1 + lam_a1

    lam_h2 = max(0.05, lam_h * r_h2)
    lam_a2 = max(0.05, lam_a * r_a2)
    lam_tot2 = lam_h2 + lam_a2

    # 1H Poisson probabilities
    p_1h_o05 = 1.0 - math.exp(-lam_tot1)
    p_1h_o15 = max(0.0, 1.0 - math.exp(-lam_tot1) * (1.0 + lam_tot1))
    p_1h_h_o05 = 1.0 - math.exp(-lam_h1)
    p_1h_a_o05 = 1.0 - math.exp(-lam_a1)

    # 2H Poisson probabilities
    p_2h_o05 = 1.0 - math.exp(-lam_tot2)
    p_2h_o15 = max(0.0, 1.0 - math.exp(-lam_tot2) * (1.0 + lam_tot2))
    p_2h_h_o05 = 1.0 - math.exp(-lam_h2)
    p_2h_a_o05 = 1.0 - math.exp(-lam_a2)

    # Most goals half: Convolve P(Goals 2H > Goals 1H)
    ph1 = [poisson_pmf(k, lam_tot1) for k in range(7)]
    ph2 = [poisson_pmf(k, lam_tot2) for k in range(7)]
    p_most_2h = 0.0
    p_equal_halves = 0.0
    p_most_1h = 0.0
    for g1 in range(7):
        for g2 in range(7):
            p = ph1[g1] * ph2[g2]
            if g2 > g1:
                p_most_2h += p
            elif g2 == g1:
                p_equal_halves += p
            else:
                p_most_1h += p

    return {
        "lam_h_1h": round(lam_h1, 2),
        "lam_a_1h": round(lam_a1, 2),
        "lam_tot_1h": round(lam_tot1, 2),
        "lam_h_2h": round(lam_h2, 2),
        "lam_a_2h": round(lam_a2, 2),
        "lam_tot_2h": round(lam_tot2, 2),
        "ratio_1h": round((lam_tot1 / max(0.01, lam_tot1 + lam_tot2)) * 100, 1),
        "ratio_2h": round((lam_tot2 / max(0.01, lam_tot1 + lam_tot2)) * 100, 1),
        "probs": {
            "1H_O05": round(p_1h_o05, 4),
            "1H_O15": round(p_1h_o15, 4),
            "1H_H_O05": round(p_1h_h_o05, 4),
            "1H_A_O05": round(p_1h_a_o05, 4),
            "2H_O05": round(p_2h_o05, 4),
            "2H_O15": round(p_2h_o15, 4),
            "2H_H_O05": round(p_2h_h_o05, 4),
            "2H_A_O05": round(p_2h_a_o05, 4),
            "MOST_GOALS_2H": round(p_most_2h, 4),
            "MOST_GOALS_1H": round(p_most_1h, 4),
            "EQUAL_HALVES": round(p_equal_halves, 4),
        },
    }
