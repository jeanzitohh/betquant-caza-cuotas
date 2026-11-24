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
            else:
                p_a_win += p
                if j >= 1:
                    p_a_o05_2 += p
                    p_a_o05_x2 += p
                if j >= 2:
                    p_a_o15_2 += p
                    p_a_o15_x2 += p

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
        "BB_A_2_O05": p_a_o05_2,
        "BB_A_2_O15": p_a_o15_2,
        "BB_A_X2_O05": p_a_o05_x2,
        "BB_A_X2_O15": p_a_o15_x2,
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
    """Compute win%, unbeaten%, +0.5%, +1.5%, GF avg, GA avg over recent matches."""
    sub = hist[-window:]
    n = len(sub)
    if n == 0:
        return {"n": 0, "win_pct": 0.0, "unbeaten_pct": 0.0, "o05_pct": 0.0, "o15_pct": 0.0, "gf_avg": 0.0, "ga_avg": 0.0}
    return {
        "n": n,
        "win_pct": sum(1 for gf, ga in sub if gf > ga) / n,
        "unbeaten_pct": sum(1 for gf, ga in sub if gf >= ga) / n,
        "o05_pct": sum(1 for gf, _ in sub if gf >= 1) / n,
        "o15_pct": sum(1 for gf, _ in sub if gf >= 2) / n,
        "gf_avg": sum(gf for gf, _ in sub) / n,
        "ga_avg": sum(ga for _, ga in sub) / n,
    }
