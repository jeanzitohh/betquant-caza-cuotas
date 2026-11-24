import json
import os
from collections import defaultdict
import backtest_engine as be


def check_colombia_details():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base_dir, "data", "colombia_espn.json"), encoding="utf-8") as f:
        raw = json.load(f)

    # Check market-by-market single leg performance under Naive thresholds in Colombia AND Europe
    for label, matches in [
        ("Colombia (2024-2026)", be.load_colombia_espn()),
        ("Europe Top 5 (22/23-26/27)", be.load_football_data_europe()),
    ]:
        matches = sorted(matches, key=lambda x: (x.date, x.home, x.away))
        team_all = defaultdict(list)
        by_market = defaultdict(list)

        for m in matches:
            h_all = team_all[(m.league, m.home)]
            a_all = team_all[(m.league, m.away)]
            if len(h_all) >= 6 and len(a_all) >= 6:
                mkt = be.market_odds_for_match(m)

                def st(hist):
                    sub = hist[-10:]
                    n = len(sub)
                    return (
                        sum(1 for gf, ga in sub if gf > ga) / n,
                        sum(1 for gf, ga in sub if gf >= ga) / n,
                        sum(1 for gf, _ in sub if gf >= 1) / n,
                        sum(1 for gf, _ in sub if gf >= 2) / n,
                        sum(gf for gf, _ in sub) / n,
                        sum(ga for _, ga in sub) / n,
                    )

                hw, hub, ho05, ho15, hgf, hga = st(h_all)
                aw, aub, ao05, ao15, agf, aga = st(a_all)

                picks = []
                if hw >= 0.50 and hw - aw >= 0.15 and hgf >= 1.3:
                    picks.append("1")
                if hub >= 0.70 and hgf >= 1.0:
                    picks.append("1X")
                if aw >= 0.50 and aw - hw >= 0.15 and agf >= 1.3:
                    picks.append("2")
                if aub >= 0.70 and agf >= 1.0:
                    picks.append("X2")
                if ho05 >= 0.75 and hgf >= 1.2 and aga >= 0.9:
                    picks.append("H_O05")
                if ho15 >= 0.45 and hgf >= 1.5 and aga >= 1.2:
                    picks.append("H_O15")
                if ao05 >= 0.75 and agf >= 1.2 and hga >= 0.9:
                    picks.append("A_O05")
                if ao15 >= 0.45 and agf >= 1.5 and hga >= 1.2:
                    picks.append("A_O15")

                for k in picks:
                    o, w = mkt[k]
                    if 1.08 <= o <= 1.90:
                        by_market[k].append((m.date, o, w))

            team_all[(m.league, m.home)].append((m.hg, m.ag))
            team_all[(m.league, m.away)].append((m.ag, m.hg))

        print(f"\n=== Single-Market Breakdown: {label} ===")
        for k in sorted(by_market.keys()):
            s = be.summarize_bets(by_market[k])
            print(f"  {k:<8} bets={s['bets']:>4}  win%={s['win_rate']:>5.1f}%  avg_odds={s['avg_odds']:>5.3f}  ROI={s['roi']:>+6.2f}%  Z={s['z_score']:>+5.2f}")

    # Also check opening odds count in Colombia
    with_open = sum(1 for e in raw if any(o.get("h_open") and o.get("d_open") and o.get("a_open") for o in e.get("odds_list", [])))
    print(f"\nColombia events with opening 1X2 odds: {with_open} / {len(raw)}")


if __name__ == "__main__":
    check_colombia_details()
