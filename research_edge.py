import csv
import datetime as dt
import glob
import json
import math
import os
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def parse_date(s: str) -> dt.date:
    s = s.strip()
    if len(s) >= 10 and s[4] == "-":
        return dt.date.fromisoformat(s[:10])
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(s)


def sf(v: str | None) -> float | None:
    if not v:
        return None
    try:
        x = float(v)
        return x if x > 1.01 else None
    except ValueError:
        return None


def summarize(bets: list[tuple[float, bool]]) -> str:
    n = len(bets)
    if n == 0:
        return "bets=   0"
    wins = sum(1 for _, w in bets if w)
    avg_o = sum(o for o, _ in bets) / n
    profits = [(o - 1.0) if w else -1.0 for o, w in bets]
    tot = sum(profits)
    roi = tot / n * 100.0
    mean_p = tot / n
    var_p = sum((p - mean_p) ** 2 for p in profits) / max(n - 1, 1)
    z = mean_p / math.sqrt(var_p / n) if var_p > 0 else 0.0
    return f"bets={n:>4}  win%={wins/n*100:>5.1f}%  avg_odds={avg_o:>5.3f}  ROI={roi:>+6.2f}%  profit={tot:>+7.2f}u  Z={z:>+5.2f}"


def devig_3(o1: float, ox: float, o2: float) -> tuple[float, float, float]:
    s = 1.0 / o1 + 1.0 / ox + 1.0 / o2
    return (1.0 / o1) / s, (1.0 / ox) / s, (1.0 / o2) / s


def devig_2(oa: float, ob: float) -> tuple[float, float]:
    s = 1.0 / oa + 1.0 / ob
    return (1.0 / oa) / s, (1.0 / ob) / s


def test_europe_sharp_and_xg():
    rows = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*_*.csv"))):
        lg = os.path.basename(path).split("_")[0]
        with open(path, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if not r.get("HomeTeam") or not r.get("FTHG"):
                    continue
                try:
                    d = parse_date(r["Date"])
                    hg, ag = int(r["FTHG"]), int(r["FTAG"])
                except Exception:
                    continue
                rows.append((d, lg, r, hg, ag))
    rows.sort(key=lambda x: (x[0], x[1], x[2]["HomeTeam"]))

    # 1. Sharp (Pinnacle / Betfair) vs Soft (B365 / Max) opening & closing
    strats = defaultdict(list)
    parlay_legs = defaultdict(list)  # name -> list of (date, odds, won)

    # 2. xG-proxy (Shots on target + Goals) rolling model
    team_xg_h = defaultdict(list)  # (gf, ga, hst, ast, hs, as)
    team_xg_a = defaultdict(list)
    lg_stats = defaultdict(list)   # (hg, ag, hst, ast)

    for d, lg, r, hg, ag in rows:
        # Sharp Opening: PSH/PSD/PSA (or BFEH/BFED/BFEA)
        psh, psd, psa = sf(r.get("PSH")), sf(r.get("PSD")), sf(r.get("PSA"))
        b365h, b365d, b365a = sf(r.get("B365H")), sf(r.get("B365D")), sf(r.get("B365A"))
        maxh, maxd, maxa = sf(r.get("MaxH")), sf(r.get("MaxD")), sf(r.get("MaxA"))
        bfeh, bfed, bfea = sf(r.get("BFEH")), sf(r.get("BFED")), sf(r.get("BFEA"))

        # Closing sharp vs Max/B365
        psch, pscd, psca = sf(r.get("PSCH")), sf(r.get("PSCD")), sf(r.get("PSCA"))
        maxch, maxcd, maxca = sf(r.get("MaxCH")), sf(r.get("MaxCD")), sf(r.get("MaxCA"))
        b365ch, b365cd, b365ca = sf(r.get("B365CH")), sf(r.get("B365CD")), sf(r.get("B365CA"))

        # Over/Under 2.5 sharp vs Max/B365
        po25, pu25 = sf(r.get("P>2.5")), sf(r.get("P<2.5"))
        bo25, bu25 = sf(r.get("B365>2.5")), sf(r.get("B365<2.5"))
        mo25, mu25 = sf(r.get("Max>2.5")), sf(r.get("Max<2.5"))

        outcomes = {"1": hg > ag, "X": hg == ag, "2": ag > hg}

        # Test Opening Pinnacle fair prob vs B365 & Max
        if psh and psd and psa:
            p1, px, p2 = devig_3(psh, psd, psa)
            sharp = {"1": p1, "X": px, "2": p2}
            if b365h and b365d and b365a:
                b_map = {"1": b365h, "X": b365d, "2": b365a}
                for k in ("1", "X", "2"):
                    ev = sharp[k] * b_map[k] - 1.0
                    if ev >= 0.01 and b_map[k] <= 3.0:
                        strats["E_Open_B365_vs_Pin_EV>=1%"].append((b_map[k], outcomes[k]))
                    if ev >= 0.03 and b_map[k] <= 3.0:
                        strats["E_Open_B365_vs_Pin_EV>=3%"].append((b_map[k], outcomes[k]))
            if maxh and maxd and maxa:
                m_map = {"1": maxh, "X": maxd, "2": maxa}
                for k in ("1", "X", "2"):
                    ev = sharp[k] * m_map[k] - 1.0
                    if ev >= 0.02 and m_map[k] <= 2.5:
                        strats["E_Open_Max_vs_Pin_EV>=2%"].append((m_map[k], outcomes[k]))
                    if ev >= 0.04 and m_map[k] <= 2.5:
                        strats["E_Open_Max_vs_Pin_EV>=4%"].append((m_map[k], outcomes[k]))
                    if ev >= 0.015 and 1.12 <= m_map[k] <= 1.65:
                        parlay_legs["P_Open_Max_vs_Pin"].append((d, m_map[k], outcomes[k]))

        # Test Opening Betfair Exchange (with 2% comm net odds check) vs Max/B365
        if bfeh and bfed and bfea and maxh and maxd and maxa:
            p1, px, p2 = devig_3(bfeh, bfed, bfea)
            sharp = {"1": p1, "X": px, "2": p2}
            m_map = {"1": maxh, "X": maxd, "2": maxa}
            for k in ("1", "X", "2"):
                ev = sharp[k] * m_map[k] - 1.0
                if ev >= 0.02 and m_map[k] <= 2.5:
                    strats["E_Open_Max_vs_BFE_EV>=2%"].append((m_map[k], outcomes[k]))

        # Test Closing Max vs Closing Pinnacle
        if psch and pscd and psca and maxch and maxcd and maxca:
            p1, px, p2 = devig_3(psch, pscd, psca)
            sharp = {"1": p1, "X": px, "2": p2}
            m_map = {"1": maxch, "X": maxcd, "2": maxca}
            for k in ("1", "X", "2"):
                ev = sharp[k] * m_map[k] - 1.0
                if ev >= 0.02 and m_map[k] <= 2.5:
                    strats["E_Close_Max_vs_Pin_EV>=2%"].append((m_map[k], outcomes[k]))
                if ev >= 0.04 and m_map[k] <= 2.5:
                    strats["E_Close_Max_vs_Pin_EV>=4%"].append((m_map[k], outcomes[k]))

        # Test O/U 2.5 Opening Max vs Pinnacle
        if po25 and pu25 and mo25 and mu25:
            po, pu = devig_2(po25, pu25)
            if po * mo25 - 1.0 >= 0.02:
                strats["E_Open_Max_OU25_vs_Pin_EV>=2%"].append((mo25, (hg + ag) >= 3))
            if pu * mu25 - 1.0 >= 0.02:
                strats["E_Open_Max_OU25_vs_Pin_EV>=2%"].append((mu25, (hg + ag) <= 2))

        # Test xG-proxy Poisson (Shots on Target + Goals) against Opening B365
        hst, ast = sf(r.get("HST")), sf(r.get("AST"))
        hs, as_ = sf(r.get("HS")), sf(r.get("AS"))
        hm_name, aw_name = r["HomeTeam"].strip(), r["AwayTeam"].strip()

        if len(team_xg_h[(lg, hm_name)]) >= 4 and len(team_xg_a[(lg, aw_name)]) >= 4 and len(lg_stats[lg]) >= 30 and b365h and b365d and b365a:
            hist_h = team_xg_h[(lg, hm_name)][-10:]
            hist_a = team_xg_a[(lg, aw_name)][-10:]
            lgh = lg_stats[lg][-200:]
            avg_hg = sum(x[0] for x in lgh) / len(lgh)
            avg_ag = sum(x[1] for x in lgh) / len(lgh)
            avg_hst = sum(x[2] for x in lgh) / len(lgh)
            avg_ast = sum(x[3] for x in lgh) / len(lgh)

            # Blend 50% goals + 50% shots-on-target proxy with Bayesian shrinkage (prior=5)
            w = 5.0
            h_gf_rate = (sum(x[0] for x in hist_h) + w * avg_hg) / (len(hist_h) + w) / avg_hg
            h_sot_rate = (sum(x[2] for x in hist_h) + w * avg_hst) / (len(hist_h) + w) / avg_hst
            h_att = 0.45 * h_gf_rate + 0.55 * h_sot_rate

            h_ga_rate = (sum(x[1] for x in hist_h) + w * avg_ag) / (len(hist_h) + w) / avg_ag
            h_sot_con_rate = (sum(x[3] for x in hist_h) + w * avg_ast) / (len(hist_h) + w) / avg_ast
            h_def = 0.45 * h_ga_rate + 0.55 * h_sot_con_rate

            a_gf_rate = (sum(x[0] for x in hist_a) + w * avg_ag) / (len(hist_a) + w) / avg_ag
            a_sot_rate = (sum(x[2] for x in hist_a) + w * avg_ast) / (len(hist_a) + w) / avg_ast
            a_att = 0.45 * a_gf_rate + 0.55 * a_sot_rate

            a_ga_rate = (sum(x[1] for x in hist_a) + w * avg_hg) / (len(hist_a) + w) / avg_hg
            a_sot_con_rate = (sum(x[3] for x in hist_a) + w * avg_hst) / (len(hist_a) + w) / avg_hst
            a_def = 0.45 * a_ga_rate + 0.55 * a_sot_con_rate

            lam_h = max(0.3, min(3.2, avg_hg * h_att * a_def))
            lam_a = max(0.3, min(3.2, avg_ag * a_att * h_def))

            # Poisson 1X2
            ph = [math.exp(-lam_h) * (lam_h ** i) / math.factorial(i) for i in range(9)]
            pa = [math.exp(-lam_a) * (lam_a ** j) / math.factorial(j) for j in range(9)]
            p1_m = sum(ph[i] * pa[j] for i in range(9) for j in range(9) if i > j)
            p2_m = sum(ph[i] * pa[j] for i in range(9) for j in range(9) if j > i)
            if p1_m * b365h - 1.0 >= 0.05 and 1.25 <= b365h <= 2.30:
                strats["E_SoT_xGProxy_vs_B365_EV>=5%"].append((b365h, hg > ag))
            if p2_m * b365a - 1.0 >= 0.05 and 1.25 <= b365a <= 2.30:
                strats["E_SoT_xGProxy_vs_B365_EV>=5%"].append((b365a, ag > hg))

        if hst is not None and ast is not None:
            team_xg_h[(lg, hm_name)].append((hg, ag, hst, ast))
            team_xg_a[(lg, aw_name)].append((ag, hg, ast, hst))
            lg_stats[lg].append((hg, ag, hst, ast))

    # Build 2-match parlays for Sharp Line Shopping
    for pname, legs in parlay_legs.items():
        used = set()
        for i in range(len(legs)):
            if i in used:
                continue
            d1, o1, w1 = legs[i]
            for j in range(i + 1, len(legs)):
                if j in used:
                    continue
                d2, o2, w2 = legs[j]
                if (d2 - d1).days > 3:
                    break
                combo = o1 * o2
                if 1.20 <= combo <= 1.95:
                    used.add(i)
                    used.add(j)
                    strats[pname + "_Parlay_2"].append((combo, w1 and w2))
                    break

    print("=== EUROPE TOP 5: SHARP VS SOFT & SOT-XG PROXY (7,630 matches) ===")
    for k in sorted(strats):
        print(f"  {k:<35} {summarize(strats[k])}")


def test_colombia_altitude_and_providers():
    ALT = {
        "Boyacá Chicó FC": 2820,
        "Patriotas": 2820,
        "Millonarios": 2640,
        "Independiente Santa Fe": 2640,
        "Fortaleza CEIF": 2640,
        "Internacional de Bogotá": 2640,
        "Deportivo Pasto": 2527,
        "Once Caldas": 2160,
        "Águilas Doradas": 2125,
        "Envigado FC": 1575,
        "Atlético Nacional": 1495,
        "Independiente Medellín": 1495,
        "Deportivo Pereira": 1411,
        "Deportes Tolima": 1285,
        "América de Cali": 1000,
        "Deportivo Cali": 1000,
        "Atlético Bucaramanga": 959,
        "Llaneros FC": 467,
        "Cúcuta Deportivo": 320,
        "Alianza FC": 169,
        "Atlético Junior": 18,
        "Jaguares de Córdoba": 18,
        "Unión Magdalena": 6,
    }
    with open(os.path.join(DATA_DIR, "colombia_espn.json"), encoding="utf-8") as f:
        col = json.load(f)

    strats = defaultdict(list)
    for ev in col:
        ol = ev.get("odds_list") or []
        if not ol:
            continue
        chosen = next((o for o in ol if o.get("h_close") and o.get("d_close") and o.get("a_close")), None)
        if not chosen:
            continue
        h, a = ev["home"], ev["away"]
        hg, ag = int(ev["hg"]), int(ev["ag"])
        o1, ox, o2 = chosen["h_close"], chosen["d_close"], chosen["a_close"]
        p1, px, p2 = devig_3(o1, ox, o2)
        dc_1x = 1.0 / ((p1 + px) * 1.055)

        alt_diff = ALT.get(h, 1000) - ALT.get(a, 1000)
        if alt_diff >= 1500:
            strats["COL_Home_Alt>=1500m_vs_Low_1"].append((o1, hg > ag))
            strats["COL_Home_Alt>=1500m_vs_Low_1X"].append((dc_1x, hg >= ag))
        if ALT.get(h, 1000) >= 2500 and ALT.get(a, 1000) <= 500:
            strats["COL_BogotaTunjaPasto_vs_Costa_1"].append((o1, hg > ag))
            strats["COL_BogotaTunjaPasto_vs_Costa_1X"].append((dc_1x, hg >= ag))

        # Check steam: closing odds shortened >= 10% vs opening odds (smart money)
        h_open = chosen.get("h_open")
        if h_open and h_open > 1.01 and o1 <= h_open * 0.90:
            strats["COL_Home_Steam_Drop>=10%"].append((o1, hg > ag))

        # Check multi-provider best odds vs first provider fair prob
        if len(ol) >= 2:
            o_base = ol[0]
            p_b1, p_bx, p_b2 = devig_3(o_base["h_close"], o_base["d_close"], o_base["a_close"])
            best_h = max(o["h_close"] for o in ol if o.get("h_close"))
            best_a = max(o["a_close"] for o in ol if o.get("a_close"))
            if p_b1 * best_h - 1.0 >= 0.01:
                strats["COL_MultiProvider_BestLine_EV>=1%"].append((best_h, hg > ag))
            if p_b2 * best_a - 1.0 >= 0.01:
                strats["COL_MultiProvider_BestLine_EV>=1%"].append((best_a, ag > hg))

    print("\n=== COLOMBIA PRIMERA A: ALTITUDE, STEAM & LINE SHOPPING (1,210 matches) ===")
    for k in sorted(strats):
        print(f"  {k:<38} {summarize(strats[k])}")


if __name__ == "__main__":
    test_europe_sharp_and_xg()
    test_colombia_altitude_and_providers()
