import base64
import io
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE_DIR, "fonts")

FONT_CANDIDATES_BOLD = [
    os.path.join(FONTS_DIR, "Poppins-Bold.ttf"),
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_CANDIDATES_SEMI = [
    os.path.join(FONTS_DIR, "Poppins-SemiBold.ttf"),
    os.path.join(FONTS_DIR, "Poppins-Bold.ttf"),
    r"C:\Windows\Fonts\seguisb.ttf",
]
FONT_CANDIDATES_REG = [
    os.path.join(FONTS_DIR, "Poppins-Regular.ttf"),
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(size: int, weight: str = "reg") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = FONT_CANDIDATES_BOLD if weight == "bold" else (FONT_CANDIDATES_SEMI if weight == "semi" else FONT_CANDIDATES_REG)
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def literal_market_text(market_name: str, home: str, away: str) -> str:
    """Turn generic Local/Visita labels into explicit team names in Spanish."""
    return (
        market_name.replace("BetBuilder: ", "")
        .replace("Mismo partido: ", "")
        .replace("Local o Empate (1X)", f"{home} Gana o Empata (1X)")
        .replace("Visitante o Empate (X2)", f"{away} Gana o Empata (X2)")
        .replace("Gana Local (1)", f"{home} Gana directo (1)")
        .replace("Gana Visitante (2)", f"{away} Gana directo (2)")
        .replace("Local 1X", f"{home} Gana o Empata (1X)")
        .replace("Visita X2", f"{away} Gana o Empata (X2)")
        .replace("Local Gana", f"{home} Gana")
        .replace("Visita Gana", f"{away} Gana")
        .replace("Local +0.5 goles", f"{home} anota +0.5 goles (mín. 1)")
        .replace("Local +1.5 goles", f"{home} anota +1.5 goles (mín. 2)")
        .replace("Visitante +0.5 goles", f"{away} anota +0.5 goles (mín. 1)")
        .replace("Visitante +1.5 goles", f"{away} anota +1.5 goles (mín. 2)")
        .replace("Visita +0.5 goles", f"{away} anota +0.5 goles (mín. 1)")
        .replace("Visita +1.5 goles", f"{away} anota +1.5 goles (mín. 2)")
        .replace("+1.5 goles en el partido", "+1.5 goles totales en el partido")
    )


def _create_backdrop(w: int = 1200, h: int = 780) -> Image.Image:
    img = Image.new("RGBA", (w, h), (10, 11, 24, 255))
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for r, col in [
        ((-120, -140, 640, 560), (124, 58, 237, 95)),
        ((660, -100, 1340, 560), (249, 115, 22, 80)),
        ((300, 320, 1020, 920), (59, 130, 246, 55)),
    ]:
        od.ellipse(r, fill=col)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=95))
    return Image.alpha_composite(img, overlay)


def _composite_rect(img: Image.Image, box: tuple[int, int, int, int], radius: int, fill: tuple, outline: tuple | None = None, width: int = 1) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
    img.paste(Image.alpha_composite(img, layer))


def _glass_panel(img: Image.Image, box: tuple[int, int, int, int], radius: int = 24, fill=(255, 255, 255, 22), border=(255, 255, 255, 64)) -> None:
    _composite_rect(img, box, radius=radius, fill=fill, outline=border, width=2)


def _draw_progress_bar(img: Image.Image, x: int, y: int, w: int, h: int, pct: float, fill_col: tuple) -> None:
    _composite_rect(img, (x, y, x + w, y + h), radius=h // 2, fill=(255, 255, 255, 32))
    fw = max(h, int(w * max(0.0, min(1.0, pct))))
    _composite_rect(img, (x, y, x + fw, y + h), radius=h // 2, fill=fill_col)


def _draw_brand_header(img: Image.Image, tag_text: str, right_text: str) -> None:
    f_brand = _load_font(25, "bold")
    f_tag = _load_font(17, "semi")
    f_right = _load_font(19, "semi")

    _composite_rect(img, (48, 30, 100, 82), radius=15, fill=(124, 58, 237, 255), outline=(249, 115, 22, 240), width=2)
    d = ImageDraw.Draw(img)
    cc_font = _load_font(22, "bold")
    cc_w = d.textlength("CC", font=cc_font)
    d.text((74 - cc_w / 2, 42), "CC", font=cc_font, fill=(255, 255, 255, 255))
    d.text((116, 30), "CAZA CUOTAS", font=f_brand, fill=(255, 255, 255, 255))
    d.text((116, 61), tag_text, font=f_tag, fill=(251, 146, 60, 255))

    rw = d.textlength(right_text, font=f_right)
    _composite_rect(img, (int(1152 - rw - 34), 34, 1152, 76), radius=21, fill=(255, 255, 255, 28), outline=(255, 255, 255, 70), width=1)
    d = ImageDraw.Draw(img)
    d.text((1152 - rw - 17, 42), right_text, font=f_right, fill=(248, 250, 252, 255))


def _form_dots(d: ImageDraw.ImageDraw, x: int, y: int, scores: list[str]) -> None:
    f_dot = _load_font(14, "bold")
    for idx, s in enumerate(scores[-5:]):
        try:
            gf, ga = map(int, s.split("-"))
        except Exception:
            continue
        col = (34, 197, 94, 240) if gf > ga else ((100, 116, 139, 230) if gf == ga else (239, 68, 68, 240))
        lbl = "G" if gf > ga else ("E" if gf == ga else "P")
        bx = x + idx * 34
        d.rounded_rectangle((bx, y, bx + 28, y + 26), radius=7, fill=col)
        lw = d.textlength(lbl, font=f_dot)
        d.text((bx + 14 - lw / 2, y + 4), lbl, font=f_dot, fill=(255, 255, 255, 255))


def render_match_card(m: dict) -> bytes:
    """Render an explicit, detailed 1200x780 PNG card with winner forecast, goal percentages, and literal bet."""
    img = _create_backdrop(1200, 780)
    _draw_brand_header(img, m.get("league_label", m["league"]).upper(), f"{m['kickoff_col']} COL")
    _glass_panel(img, (48, 102, 1152, 742), radius=28)

    d = ImageDraw.Draw(img)
    f_team = _load_font(32, "bold")
    f_sub = _load_font(17, "reg")
    f_lbl = _load_font(17, "semi")

    title = f"{m['home']}   vs   {m['away']}"
    tw = d.textlength(title, font=f_team)
    if tw > 1040:
        f_team = _load_font(25, "bold")
        tw = d.textlength(title, font=f_team)
    d.text(((1200 - tw) / 2, 120), title, font=f_team, fill=(255, 255, 255, 255))

    # Winner probabilities (market implied + model)
    s_inv = 1.0 / m["o1"] + 1.0 / m["ox"] + 1.0 / m["o2"]
    p1 = (1.0 / m["o1"]) / s_inv
    px = (1.0 / m["ox"]) / s_inv
    p2 = (1.0 / m["o2"]) / s_inv

    bar_x, bar_y, bar_w, bar_h = 84, 174, 1032, 24
    w1 = int(bar_w * p1)
    wx = int(bar_w * px)
    d.rounded_rectangle((bar_x, bar_y, bar_x + w1, bar_y + bar_h), radius=10, fill=(139, 92, 246, 255))
    d.rectangle((bar_x + w1 + 2, bar_y, bar_x + w1 + wx - 2, bar_y + bar_h), fill=(148, 163, 184, 220))
    d.rounded_rectangle((bar_x + w1 + wx, bar_y, bar_x + bar_w, bar_y + bar_h), radius=10, fill=(249, 115, 22, 255))

    d.text((bar_x, 204), f"{m['home'][:18]} Gana: {p1*100:.0f}% (@{m['o1']:.2f})", font=f_lbl, fill=(196, 181, 253, 255))
    mid_txt = f"Empate: {px*100:.0f}% (@{m['ox']:.2f})"
    mw = d.textlength(mid_txt, font=f_lbl)
    d.text((600 - mw / 2, 204), mid_txt, font=f_lbl, fill=(203, 213, 225, 255))
    r_txt = f"{m['away'][:18]} Gana: {p2*100:.0f}% (@{m['o2']:.2f})"
    rw = d.textlength(r_txt, font=f_lbl)
    d.text((bar_x + bar_w - rw, 204), r_txt, font=f_lbl, fill=(253, 186, 116, 255))

    # Left & Right team stats
    _glass_panel(img, (84, 242, 584, 466), radius=20, fill=(255, 255, 255, 16))
    _glass_panel(img, (616, 242, 1116, 466), radius=20, fill=(255, 255, 255, 16))
    d = ImageDraw.Draw(img)

    hs, as_ = m["h_stat"], m["a_stat"]
    for bx, name, st, scores, col in [
        (108, f"LOCAL: {m['home'][:22]}", hs, m.get("h_recent_scores", []), (139, 92, 246, 255)),
        (640, f"VISITA: {m['away'][:22]}", as_, m.get("a_recent_scores", []), (249, 115, 22, 255)),
    ]:
        d.text((bx, 256), name, font=f_lbl, fill=(255, 255, 255, 255))
        d.text((bx, 288), f"Victorias: {st['win_pct']*100:.0f}%", font=f_sub, fill=(226, 232, 240, 255))
        _draw_progress_bar(img, bx + 175, 294, 270, 11, st["win_pct"], col)

        d = ImageDraw.Draw(img)
        d.text((bx, 320), f"No pierde: {st['unbeaten_pct']*100:.0f}%", font=f_sub, fill=(226, 232, 240, 255))
        _draw_progress_bar(img, bx + 175, 326, 270, 11, st["unbeaten_pct"], (34, 197, 94, 235))

        d = ImageDraw.Draw(img)
        d.text((bx, 352), f"Anota +0.5: {st['o05_pct']*100:.0f}%", font=f_sub, fill=(226, 232, 240, 255))
        _draw_progress_bar(img, bx + 175, 358, 270, 11, st["o05_pct"], (56, 189, 248, 235))

        d = ImageDraw.Draw(img)
        d.text((bx, 386), f"Prom. último 10: {st['gf_avg']:.2f} GF / {st['ga_avg']:.2f} GA", font=f_sub, fill=(203, 213, 225, 255))
        _form_dots(d, bx, 420, scores)

    # Dedicated Goal Forecast Breakdown Panel
    _glass_panel(img, (84, 482, 1116, 616), radius=20, fill=(255, 255, 255, 18), border=(255, 255, 255, 55))
    d = ImageDraw.Draw(img)
    ps = m.get("probs_summary") or {}
    lam_h = m.get("lam_h", 1.3)
    lam_a = m.get("lam_a", 1.1)
    h_o05 = ps.get("h_o05", round(hs["o05_pct"] * 100, 0))
    h_o15 = ps.get("h_o15", round(hs["o15_pct"] * 100, 0))
    a_o05 = ps.get("a_o05", round(as_["o05_pct"] * 100, 0))
    a_o15 = ps.get("a_o15", round(as_["o15_pct"] * 100, 0))
    tot_o15 = ps.get("o15", 72)
    tot_o25 = ps.get("o25", 48)
    btts = ps.get("btts", 45)

    if p1 >= 0.52:
        fav_line = f"PRONÓSTICO: Favorito {m['home']} ({p1*100:.0f}% de ganar | {(p1+px)*100:.0f}% Gana o Empata)"
    elif p2 >= 0.52:
        fav_line = f"PRONÓSTICO: Favorito {m['away']} ({p2*100:.0f}% de ganar | {(p2+px)*100:.0f}% Gana o Empata)"
    else:
        fav_line = f"PRONÓSTICO: Partido parejo — Ligero favorito {m['home'] if p1>=p2 else m['away']} ({max(p1,p2)*100:.0f}%)"

    d.text((108, 496), fav_line, font=_load_font(19, "bold"), fill=(253, 224, 71, 255))
    d.text(
        (108, 530),
        f"Goles esperados: {m['home'][:16]} ~{lam_h:.2f}  |  {m['away'][:16]} ~{lam_a:.2f}  |  Partido +1.5: {tot_o15:.0f}%  •  +2.5: {tot_o25:.0f}%  •  Ambos marcan: {btts:.0f}%",
        font=f_sub,
        fill=(241, 245, 249, 255),
    )
    d.text(
        (108, 564),
        f"{m['home'][:18]} anota +0.5: {h_o05:.0f}%  (+1.5: {h_o15:.0f}%)    |    {m['away'][:18]} anota +0.5: {a_o05:.0f}%  (+1.5: {a_o15:.0f}%)",
        font=f_lbl,
        fill=(186, 230, 253, 255),
    )

    # Bottom Literal Bet Box
    pick_odds = None
    if m.get("opt_b_pick"):
        pb = m["opt_b_pick"]
        pick_odds = float(pb["odds"])
        lit = literal_market_text(pb["market_name"], m["home"], m["away"])
        pick_txt = f"PRONÓSTICO SUGERIDO: {lit}  @~{pb['odds']:.2f}"
        ev_txt = f"Prob. {pb['prob']}% • {'Cuota con valor' if pb['ev_pct'] > 0 else 'Cuota estándar'}"
        ev_col = (74, 222, 128, 255) if pb["ev_pct"] > 0 else (251, 191, 36, 255)
    elif m.get("opt_a_leg"):
        pa = m["opt_a_leg"]
        pick_odds = float(pa["odds"])
        lit = literal_market_text(pa["market_name"], m["home"], m["away"])
        pick_txt = f"SELECCIÓN SUGERIDA: {lit}  @{pa['odds']:.2f}"
        ev_txt = f"Prob. {pa['prob']}% • {'Cuota con valor' if pa['ev_pct'] > 0 else 'Cuota estándar'}"
        ev_col = (74, 222, 128, 255) if pa["ev_pct"] > 0 else (251, 191, 36, 255)
    else:
        win_side = f"{m['home']} Gana o Empata (1X)" if p1 >= p2 else f"{m['away']} Gana o Empata (X2)"
        pick_txt = f"LECTURA DEL PARTIDO: {win_side} • Partido +1.5 goles ({tot_o15:.0f}%)"
        ev_txt = "Mercado estándar"
        ev_col = (203, 213, 225, 255)

    _glass_panel(img, (84, 632, 1116, 718), radius=18, fill=(124, 58, 237, 65), border=(167, 139, 250, 130))
    d = ImageDraw.Draw(img)
    f_ev = _load_font(18, "bold")
    ew = d.textlength(ev_txt, font=f_ev)
    max_pick_w = (1092 - ew - 28) - 108
    f_pk = _load_font(19, "bold")
    for sz in (19, 17, 15, 14, 13):
        cand_f = _load_font(sz, "bold")
        if d.textlength(pick_txt, font=cand_f) <= max_pick_w:
            f_pk = cand_f
            break
        f_pk = cand_f
    d.text((108, 648), pick_txt, font=f_pk, fill=(255, 255, 255, 255))
    d.text((1092 - ew, 648), ev_txt, font=f_ev, fill=ev_col)
    sub_footer = "Caza Cuotas • Pronóstico Deportivo"
    ph = m.get("pair_hint")
    if ph and (pick_odds is None or pick_odds < 1.50):
        sub_footer = f"Para cuota 1.50+: combinar con {ph['partner_title'][:32]} ({ph['partner_pick'][:30]}) -> @{ph['combo_odds']:.2f}"
    d.text((108, 684), sub_footer[:98], font=_load_font(14, "reg"), fill=(226, 232, 240, 255))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_daily_summary_card(rep: dict) -> bytes:
    """Render a crisp 1200x720 PNG card for the daily closing accuracy report."""
    daily = rep.get("daily_stats") or []
    settled_days = [d for d in daily if d["settled"] > 0]
    latest = settled_days[0] if settled_days else {"date": "Hoy", "won": rep.get("won", 0), "settled": rep.get("settled", 0), "accuracy_pct": rep.get("accuracy_pct", 0.0), "profit_u": rep.get("total_profit_u", 0.0)}

    img = _create_backdrop(1200, 720)
    _draw_brand_header(img, "CIERRE DEL DÍA • EFECTIVIDAD DE PRONÓSTICOS", f"{latest['date']}")
    _glass_panel(img, (48, 102, 1152, 678), radius=28)

    # Top hero metrics
    _glass_panel(img, (84, 134, 650, 300), radius=22, fill=(124, 58, 237, 50), border=(167, 139, 250, 130))
    _glass_panel(img, (676, 134, 1116, 300), radius=22, fill=(34, 197, 94, 34), border=(74, 222, 128, 115))
    d = ImageDraw.Draw(img)
    acc = float(latest.get("accuracy_pct") or 0.0)
    d.text((116, 154), "EFECTIVIDAD DE LA JORNADA", font=_load_font(16, "bold"), fill=(221, 214, 254, 255))
    d.text((116, 182), f"{latest['won']} de {latest['settled']} acertados  ({acc:.1f}%)", font=_load_font(34, "bold"), fill=(255, 255, 255, 255))
    _draw_progress_bar(img, 116, 250, 500, 18, acc / 100.0, (74, 222, 128, 255) if acc >= 65 else (251, 191, 36, 255))

    d = ImageDraw.Draw(img)
    glob_acc = float(rep.get("accuracy_pct") or 0.0)
    d.text((708, 154), "BALANCE ACUMULADO", font=_load_font(16, "bold"), fill=(187, 247, 208, 255))
    d.text((708, 186), f"{rep.get('won', 0)}G / {rep.get('lost', 0)}P ({glob_acc:.1f}%)", font=_load_font(34, "bold"), fill=(255, 255, 255, 255))
    d.text((708, 244), f"Rendimiento: {rep.get('total_profit_u', 0.0):+.2f}u  |  Pendientes: {rep.get('pending', 0)}", font=_load_font(17, "semi"), fill=(226, 232, 240, 255))

    # Recent days list
    d.text((88, 326), "HISTORIAL RECIENTE POR JORNADA", font=_load_font(16, "bold"), fill=(196, 181, 253, 255))
    for i, day in enumerate(daily[:5]):
        y0 = 362 + i * 56
        _glass_panel(img, (84, y0, 1116, y0 + 46), radius=14, fill=(255, 255, 255, 16))
        d = ImageDraw.Draw(img)
        d.text((112, y0 + 12), str(day["date"]), font=_load_font(18, "bold"), fill=(255, 255, 255, 255))
        if day["settled"] > 0:
            pct = float(day["accuracy_pct"] or 0.0)
            _draw_progress_bar(img, 300, y0 + 15, 420, 14, pct / 100.0, (74, 222, 128, 255) if pct >= 60 else (249, 115, 22, 255))
            d = ImageDraw.Draw(img)
            d.text((748, y0 + 11), f"{day['won']} de {day['settled']} ({pct:.1f}%)", font=_load_font(18, "bold"), fill=(241, 245, 249, 255))
            pcol = (74, 222, 128, 255) if day["profit_u"] >= 0 else (248, 113, 113, 255)
            d.text((970, y0 + 11), f"{day['profit_u']:+.2f}u", font=_load_font(18, "bold"), fill=pcol)
        else:
            pm = day.get("pending_matches") or day["pending"]
            d.text((300, y0 + 12), f"{day['pending']} selecciones en {pm} partidos (por jugar)", font=_load_font(17, "reg"), fill=(148, 163, 184, 255))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_settled_card(settled_items: list[dict], rep: dict) -> bytes:
    """Render a crisp PNG card showing newly settled match results."""
    shown = settled_items[:5]
    h = 280 + max(1, len(shown)) * 102
    img = _create_backdrop(1200, h)
    _draw_brand_header(img, "RESULTADOS LIQUIDADOS • CAZA CUOTAS", f"Acumulado: {rep.get('won',0)}/{rep.get('settled',0)} ({rep.get('accuracy_pct',0):.1f}%)")
    _glass_panel(img, (48, 102, 1152, h - 38), radius=28)

    for idx, tr in enumerate(shown):
        y0 = 132 + idx * 100
        won = tr["status"] == "WON"
        fill_c = (34, 197, 94, 30) if won else (239, 68, 68, 30)
        brd_c = (74, 222, 128, 110) if won else (248, 113, 113, 110)
        _glass_panel(img, (84, y0, 1116, y0 + 84), radius=18, fill=fill_c, border=brd_c)
        d = ImageDraw.Draw(img)
        badge = "GANADA" if won else "PERDIDA"
        bcol = (74, 222, 128, 255) if won else (248, 113, 113, 255)
        d.text((112, y0 + 14), badge, font=_load_font(17, "bold"), fill=bcol)
        d.text((228, y0 + 12), str(tr["title"])[:52], font=_load_font(20, "bold"), fill=(255, 255, 255, 255))
        raw_note = str(tr.get("result_note") or "")
        # Clean internal market keys (e.g. "BB_H_1X_O05:2-1(W)") into clean final scores
        scores = [part.split(":")[-1].replace("(W)", " ✓").replace("(L)", " ✗").strip() for part in raw_note.split("|") if part.strip()]
        clean_note = "Marcador: " + " | ".join(scores) if scores else "Resultado confirmado"
        d.text((112, y0 + 46), f"Cuota @{float(tr['odds']):.2f}   •   {clean_note[:54]}", font=_load_font(16, "reg"), fill=(203, 213, 225, 255))
        ptxt = f"{float(tr['profit_u']):+.2f}u"
        pw = d.textlength(ptxt, font=_load_font(26, "bold"))
        d.text((1086 - pw, y0 + 24), ptxt, font=_load_font(26, "bold"), fill=bcol)

    _glass_panel(img, (84, h - 126, 1116, h - 62), radius=16, fill=(124, 58, 237, 50))
    d = ImageDraw.Draw(img)
    d.text((116, h - 106), f"Efectividad global: {rep.get('won',0)} de {rep.get('settled',0)} acertados ({rep.get('accuracy_pct',0):.1f}%)   |   Neto: {rep.get('total_profit_u',0):+.2f}u", font=_load_font(20, "bold"), fill=(255, 255, 255, 255))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_serial_ladder_card(ladder: list[dict], chunk_label: str = "") -> bytes:
    """Render a chronological 1-by-1 turn schedule card with goal breakdown and zero internal jargon."""
    shown = ladder[:5]
    h = 260 + max(1, len(shown)) * 136
    img = _create_backdrop(1200, h)
    hdr_sub = "Horarios Colombia (UTC-5)" if not chunk_label else f"{chunk_label} • Hora Colombia"
    _draw_brand_header(img, "EN SERIE • FILA CRONOLÓGICA POR HORA", hdr_sub)
    _glass_panel(img, (48, 102, 1152, h - 38), radius=28)

    d = ImageDraw.Draw(img)
    d.text((88, 126), "Una sola fila por hora de inicio: elige tus jugadas viendo los próximos partidos en camino.", font=_load_font(16, "reg"), fill=(203, 213, 225, 255))

    for idx, s in enumerate(shown):
        y0 = 164 + idx * 132
        _glass_panel(img, (84, y0, 1116, y0 + 118), radius=18, fill=(255, 255, 255, 18))
        d = ImageDraw.Draw(img)
        lg_txt = "" if s["league_label"] in ("group-stage", "regular-season", "league-stage") else f" • {s['league_label']}"
        d.text((112, y0 + 12), f"TURNO #{s['step']}  •  {s['kickoff_col']} COL  ({s['gap_label']}){lg_txt}", font=_load_font(14, "bold"), fill=(253, 186, 116, 255))
        d.text((112, y0 + 34), str(s["title"])[:54], font=_load_font(20, "bold"), fill=(255, 255, 255, 255))
        hm, aw = ([x.strip() for x in s["title"].split(" vs ", 1)] if " vs " in s["title"] else (s["title"], "Visita"))
        m_name = literal_market_text(s["market_name"], hm, aw)
        alt_txt = ""
        if s.get("alt_market_name"):
            alt_lit = literal_market_text(s["alt_market_name"], hm, aw)
            alt_txt = f"   |   Alt: {alt_lit[:32]} @{float(s['alt_odds']):.2f}"
        d.text((112, y0 + 62), (m_name + alt_txt)[:86], font=_load_font(14, "bold"), fill=(196, 181, 253, 255))

        ps = s.get("probs_summary") or {}
        if ps:
            meta_txt = (
                f"1X2: {ps.get('p1',0):.0f}% / {ps.get('px',0):.0f}% / {ps.get('p2',0):.0f}%   •   "
                f"Goles est: {s.get('lam_h',1.4):.2f} vs {s.get('lam_a',1.0):.2f}   •   "
                f"+1.5 Partido: {ps.get('o15',0):.0f}%   •   Ambos marcan: {ps.get('btts',0):.0f}%"
            )
            d.text((112, y0 + 88), meta_txt, font=_load_font(13, "reg"), fill=(186, 230, 253, 255))

        odd_txt = f"@{float(s['odds']):.2f}"
        prob_txt = f"Prob. {s['prob']}%"
        ow = d.textlength(odd_txt, font=_load_font(28, "bold"))
        prw = d.textlength(prob_txt, font=_load_font(15, "semi"))
        d.text((1086 - ow, y0 + 20), odd_txt, font=_load_font(28, "bold"), fill=(255, 255, 255, 255))
        d.text((1086 - prw, y0 + 56), prob_txt, font=_load_font(15, "semi"), fill=(74, 222, 128, 255))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_parlay_card(parlay: dict) -> bytes:
    """Render an explicit 1200x675 PNG ticket card for a 2-match parlay."""
    img = _create_backdrop(1200, 675)
    _draw_brand_header(img, "COMBINADA DE 2 SELECCIONES • CUOTA 1.50–1.95", f"{parlay['kickoff_col']} COL")
    _glass_panel(img, (48, 102, 1152, 636), radius=28)

    d = ImageDraw.Draw(img)
    f_leg = _load_font(23, "bold")
    f_sub = _load_font(18, "reg")

    leg_times = [
        parlay.get("leg1_kickoff") or ((parlay.get("legs") or [{}])[0].get("kickoff_col") if parlay.get("legs") else "") or parlay.get("kickoff_col", ""),
        parlay.get("leg2_kickoff") or ((parlay.get("legs") or [{}, {}])[1].get("kickoff_col") if len(parlay.get("legs") or []) > 1 else "") or parlay.get("kickoff_col", ""),
    ]
    for idx, leg_txt in enumerate([parlay["leg1"], parlay["leg2"]]):
        y0 = 138 + idx * 144
        _glass_panel(img, (88, y0, 1112, y0 + 118), radius=20, fill=(255, 255, 255, 18))
        d = ImageDraw.Draw(img)
        parts = leg_txt.split(":", 1)
        match_part = parts[0].strip()
        pick_part = parts[1].strip() if len(parts) > 1 else ""
        # Extract home vs away to make pick literal
        clean_match = match_part.split(")", 1)[-1].strip() if ")" in match_part else match_part
        if " vs " in clean_match:
            hm, aw = [x.strip() for x in clean_match.split(" vs ", 1)]
            pick_part = literal_market_text(pick_part, hm, aw)
        d.text((118, y0 + 16), f"APUESTA {idx + 1} • {leg_times[idx]} COL • {match_part}", font=f_sub, fill=(196, 181, 253, 255))
        d.text((118, y0 + 52), pick_part, font=f_leg, fill=(255, 255, 255, 255))

    _glass_panel(img, (88, 448, 1112, 598), radius=22, fill=(249, 115, 22, 42), border=(251, 146, 60, 130))
    d = ImageDraw.Draw(img)
    d.text((120, 470), "CUOTA FINAL", font=_load_font(17, "bold"), fill=(253, 186, 116, 255))
    d.text((120, 498), f"@{parlay['combo_odds']:.2f}", font=_load_font(46, "bold"), fill=(255, 255, 255, 255))

    d.text((370, 474), f"Probabilidad Real: {parlay['prob_est']}%   |   Exigida por cuota: {parlay['prob_impl']}%", font=f_sub, fill=(241, 245, 249, 255))
    _draw_progress_bar(img, 370, 514, 460, 18, parlay["prob_est"] / 100.0, (74, 222, 128, 255) if parlay["ev_pct"] > 0 else (251, 191, 36, 255))
    d = ImageDraw.Draw(img)

    ev_col = (74, 222, 128, 255) if parlay["ev_pct"] > 0 else (251, 191, 36, 255)
    d.text((865, 488), f"Prob. {parlay['prob_est']}%", font=_load_font(30, "bold"), fill=ev_col)
    d.text((865, 536), "Cuota con valor" if parlay["ev_pct"] > 0 else "Cuota ajustada", font=_load_font(16, "reg"), fill=ev_col)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_daily_summary_card(rep: dict) -> bytes:
    """Render a crisp 1200x720 PNG card for the daily closing accuracy report."""
    daily = rep.get("daily_stats") or []
    settled_days = [d for d in daily if d["settled"] > 0]
    latest = settled_days[0] if settled_days else {"date": "Hoy", "won": rep.get("won", 0), "settled": rep.get("settled", 0), "accuracy_pct": rep.get("accuracy_pct", 0.0), "profit_u": rep.get("total_profit_u", 0.0)}

    img = _create_backdrop(1200, 720)
    _draw_brand_header(img, "CIERRE DEL DÍA • EFECTIVIDAD DE PRONÓSTICOS", f"{latest['date']}")
    _glass_panel(img, (48, 102, 1152, 678), radius=28)

    # Top hero metrics
    _glass_panel(img, (84, 134, 650, 300), radius=22, fill=(124, 58, 237, 50), border=(167, 139, 250, 130))
    _glass_panel(img, (676, 134, 1116, 300), radius=22, fill=(34, 197, 94, 34), border=(74, 222, 128, 115))
    d = ImageDraw.Draw(img)
    acc = float(latest.get("accuracy_pct") or 0.0)
    d.text((116, 154), "EFECTIVIDAD DE LA JORNADA", font=_load_font(16, "bold"), fill=(221, 214, 254, 255))
    d.text((116, 182), f"{latest['won']} de {latest['settled']} acertados  ({acc:.1f}%)", font=_load_font(34, "bold"), fill=(255, 255, 255, 255))
    _draw_progress_bar(img, 116, 250, 500, 18, acc / 100.0, (74, 222, 128, 255) if acc >= 65 else (251, 191, 36, 255))

    d = ImageDraw.Draw(img)
    glob_acc = float(rep.get("accuracy_pct") or 0.0)
    d.text((708, 154), "BALANCE ACUMULADO", font=_load_font(16, "bold"), fill=(187, 247, 208, 255))
    d.text((708, 186), f"{rep.get('won', 0)}G / {rep.get('lost', 0)}P ({glob_acc:.1f}%)", font=_load_font(34, "bold"), fill=(255, 255, 255, 255))
    d.text((708, 244), f"Rendimiento: {rep.get('total_profit_u', 0.0):+.2f}u  |  Pendientes: {rep.get('pending', 0)}", font=_load_font(17, "semi"), fill=(226, 232, 240, 255))

    # Recent days list
    d.text((88, 326), "HISTORIAL RECIENTE POR JORNADA", font=_load_font(16, "bold"), fill=(196, 181, 253, 255))
    for i, day in enumerate(daily[:5]):
        y0 = 362 + i * 56
        _glass_panel(img, (84, y0, 1116, y0 + 46), radius=14, fill=(255, 255, 255, 16))
        d = ImageDraw.Draw(img)
        d.text((112, y0 + 12), str(day["date"]), font=_load_font(18, "bold"), fill=(255, 255, 255, 255))
        if day["settled"] > 0:
            pct = float(day["accuracy_pct"] or 0.0)
            _draw_progress_bar(img, 300, y0 + 15, 420, 14, pct / 100.0, (74, 222, 128, 255) if pct >= 60 else (249, 115, 22, 255))
            d = ImageDraw.Draw(img)
            d.text((748, y0 + 11), f"{day['won']} de {day['settled']} ({pct:.1f}%)", font=_load_font(18, "bold"), fill=(241, 245, 249, 255))
            pcol = (74, 222, 128, 255) if day["profit_u"] >= 0 else (248, 113, 113, 255)
            d.text((970, y0 + 11), f"{day['profit_u']:+.2f}u", font=_load_font(18, "bold"), fill=pcol)
        else:
            pm = day.get("pending_matches") or day["pending"]
            d.text((300, y0 + 12), f"{day['pending']} selecciones en {pm} partidos (por jugar)", font=_load_font(17, "reg"), fill=(148, 163, 184, 255))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_settled_card(settled_items: list[dict], rep: dict) -> bytes:
    """Render a crisp PNG card showing newly settled match results."""
    shown = settled_items[:5]
    h = 280 + max(1, len(shown)) * 102
    img = _create_backdrop(1200, h)
    _draw_brand_header(img, "RESULTADOS LIQUIDADOS • CAZA CUOTAS", f"Acumulado: {rep.get('won',0)}/{rep.get('settled',0)} ({rep.get('accuracy_pct',0):.1f}%)")
    _glass_panel(img, (48, 102, 1152, h - 38), radius=28)

    for idx, tr in enumerate(shown):
        y0 = 132 + idx * 100
        won = tr["status"] == "WON"
        fill_c = (34, 197, 94, 30) if won else (239, 68, 68, 30)
        brd_c = (74, 222, 128, 110) if won else (248, 113, 113, 110)
        _glass_panel(img, (84, y0, 1116, y0 + 84), radius=18, fill=fill_c, border=brd_c)
        d = ImageDraw.Draw(img)
        badge = "GANADA" if won else "PERDIDA"
        bcol = (74, 222, 128, 255) if won else (248, 113, 113, 255)
        d.text((112, y0 + 14), badge, font=_load_font(17, "bold"), fill=bcol)
        d.text((228, y0 + 12), str(tr["title"])[:52], font=_load_font(20, "bold"), fill=(255, 255, 255, 255))
        raw_note = str(tr.get("result_note") or "")
        # Clean internal market keys (e.g. "BB_H_1X_O05:2-1(W)") into clean final scores
        scores = [part.split(":")[-1].replace("(W)", " ✓").replace("(L)", " ✗").strip() for part in raw_note.split("|") if part.strip()]
        clean_note = "Marcador: " + " | ".join(scores) if scores else "Resultado confirmado"
        d.text((112, y0 + 46), f"Cuota @{float(tr['odds']):.2f}   •   {clean_note[:54]}", font=_load_font(16, "reg"), fill=(203, 213, 225, 255))
        ptxt = f"{float(tr['profit_u']):+.2f}u"
        pw = d.textlength(ptxt, font=_load_font(26, "bold"))
        d.text((1086 - pw, y0 + 24), ptxt, font=_load_font(26, "bold"), fill=bcol)

    _glass_panel(img, (84, h - 126, 1116, h - 62), radius=16, fill=(124, 58, 237, 50))
    d = ImageDraw.Draw(img)
    d.text((116, h - 106), f"Efectividad global: {rep.get('won',0)} de {rep.get('settled',0)} acertados ({rep.get('accuracy_pct',0):.1f}%)   |   Neto: {rep.get('total_profit_u',0):+.2f}u", font=_load_font(20, "bold"), fill=(255, 255, 255, 255))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_serial_ladder_card(ladder: list[dict], chunk_label: str = "") -> bytes:
    """Render a chronological 1-by-1 turn schedule card with goal breakdown and zero internal jargon."""
    shown = ladder[:5]
    h = 260 + max(1, len(shown)) * 136
    img = _create_backdrop(1200, h)
    hdr_sub = "Horarios Colombia (UTC-5)" if not chunk_label else f"{chunk_label} • Hora Colombia"
    _draw_brand_header(img, "EN SERIE • FILA CRONOLÓGICA POR HORA", hdr_sub)
    _glass_panel(img, (48, 102, 1152, h - 38), radius=28)

    d = ImageDraw.Draw(img)
    d.text((88, 126), "Una sola fila por hora de inicio: elige tus jugadas viendo los próximos partidos en camino.", font=_load_font(16, "reg"), fill=(203, 213, 225, 255))

    for idx, s in enumerate(shown):
        y0 = 164 + idx * 132
        _glass_panel(img, (84, y0, 1116, y0 + 118), radius=18, fill=(255, 255, 255, 18))
        d = ImageDraw.Draw(img)
        lg_txt = "" if s["league_label"] in ("group-stage", "regular-season", "league-stage") else f" • {s['league_label']}"
        d.text((112, y0 + 12), f"TURNO #{s['step']}  •  {s['kickoff_col']} COL  ({s['gap_label']}){lg_txt}", font=_load_font(14, "bold"), fill=(253, 186, 116, 255))
        d.text((112, y0 + 34), str(s["title"])[:54], font=_load_font(20, "bold"), fill=(255, 255, 255, 255))
        hm, aw = ([x.strip() for x in s["title"].split(" vs ", 1)] if " vs " in s["title"] else (s["title"], "Visita"))
        m_name = literal_market_text(s["market_name"], hm, aw)
        alt_txt = ""
        if s.get("alt_market_name"):
            alt_lit = literal_market_text(s["alt_market_name"], hm, aw)
            alt_txt = f"   |   Alt: {alt_lit[:32]} @{float(s['alt_odds']):.2f}"
        d.text((112, y0 + 62), (m_name + alt_txt)[:86], font=_load_font(14, "bold"), fill=(196, 181, 253, 255))

        ps = s.get("probs_summary") or {}
        if ps:
            meta_txt = (
                f"1X2: {ps.get('p1',0):.0f}% / {ps.get('px',0):.0f}% / {ps.get('p2',0):.0f}%   •   "
                f"Goles est: {s.get('lam_h',1.4):.2f} vs {s.get('lam_a',1.0):.2f}   •   "
                f"+1.5 Partido: {ps.get('o15',0):.0f}%   •   Ambos marcan: {ps.get('btts',0):.0f}%"
            )
            d.text((112, y0 + 88), meta_txt, font=_load_font(13, "reg"), fill=(186, 230, 253, 255))

        odd_txt = f"@{float(s['odds']):.2f}"
        prob_txt = f"Prob. {s['prob']}%"
        ow = d.textlength(odd_txt, font=_load_font(28, "bold"))
        prw = d.textlength(prob_txt, font=_load_font(15, "semi"))
        d.text((1086 - ow, y0 + 20), odd_txt, font=_load_font(28, "bold"), fill=(255, 255, 255, 255))
        d.text((1086 - prw, y0 + 56), prob_txt, font=_load_font(15, "semi"), fill=(74, 222, 128, 255))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def png_to_webp_data_url(png_bytes: bytes, max_w: int = 1120) -> str:
    """Compress a PNG card into a crisp high-quality WebP data URL for Supabase Realtime feed."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    if img.width > max_w:
        new_h = int(img.height * (max_w / img.width))
        img = img.resize((max_w, new_h), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=92, method=5)
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def render_app_icon(size: int = 512) -> bytes:
    """Generate the official Caza Cuotas squircle PWA icon PNG."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pad = int(size * 0.04)
    rad = int(size * 0.24)
    grad = Image.new("RGBA", (size, size), (124, 58, 237, 255))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(124 + (249 - 124) * t)
        g = int(58 + (115 - 58) * t)
        b = int(237 + (22 - 237) * t)
        gd.line([(0, y), (size, y)], fill=(r, g, b, 255))
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((pad, pad, size - pad, size - pad), radius=rad, fill=255)
    img.paste(grad, (0, 0), mask)

    s = size / 32.0
    d = ImageDraw.Draw(img)
    crown = [(5 * s, 10 * s), (9 * s, 5 * s), (13 * s, 9 * s), (19 * s, 9 * s), (23 * s, 5 * s), (27 * s, 10 * s), (25 * s, 22 * s), (16 * s, 27 * s), (7 * s, 22 * s)]
    d.polygon(crown, fill=(15, 15, 30, 235), outline=(255, 255, 255, 240))
    visor = [(8.5 * s, 13 * s), (14.5 * s, 13 * s), (16 * s, 14.5 * s), (17.5 * s, 13 * s), (23.5 * s, 13 * s), (23.5 * s, 17.5 * s), (17 * s, 18.2 * s), (16 * s, 16.5 * s), (15 * s, 18.2 * s), (8.5 * s, 17.5 * s)]
    d.polygon(visor, fill=(249, 115, 22, 255), outline=(253, 224, 71, 255))
    d.ellipse((14.6 * s, 20.1 * s, 17.4 * s, 22.9 * s), fill=(248, 250, 252, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
