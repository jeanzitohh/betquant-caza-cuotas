import io
import os
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES_BOLD = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
FONT_CANDIDATES_REG = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = FONT_CANDIDATES_BOLD if bold else FONT_CANDIDATES_REG
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _create_backdrop(w: int = 1200, h: int = 675) -> Image.Image:
    """Create Caza Cuotas dark violet-orange ambient gradient backdrop."""
    img = Image.new("RGBA", (w, h), (10, 11, 24, 255))
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    # Soft ambient violet & orange orbs
    for r, col in [
        ((-120, -140, 620, 520), (124, 58, 237, 95)),
        ((680, -100, 1340, 540), (249, 115, 22, 80)),
        ((320, 260, 1020, 860), (59, 130, 246, 55)),
    ]:
        od.ellipse(r, fill=col)
    from PIL import ImageFilter

    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=95))
    img = Image.alpha_composite(img, overlay)
    return img


def _glass_panel(img: Image.Image, box: tuple[int, int, int, int], radius: int = 24, fill=(255, 255, 255, 22), border=(255, 255, 255, 58)) -> None:
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=border, width=2)


def _draw_progress_bar(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, pct: float, fill_col: tuple) -> None:
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=(255, 255, 255, 28))
    fw = max(h, int(w * max(0.0, min(1.0, pct))))
    d.rounded_rectangle((x, y, x + fw, y + h), radius=h // 2, fill=fill_col)


def _draw_brand_header(img: Image.Image, tag_text: str, right_text: str) -> None:
    d = ImageDraw.Draw(img)
    f_brand = _load_font(26, bold=True)
    f_tag = _load_font(18, bold=True)
    f_right = _load_font(20, bold=False)

    # Caza Cuotas purple-orange badge
    d.rounded_rectangle((48, 34, 96, 82), radius=14, fill=(124, 58, 237, 255), outline=(249, 115, 22, 230), width=2)
    d.text((61, 43), "CC", font=_load_font(24, bold=True), fill=(255, 255, 255, 255))
    d.text((112, 34), "CAZA CUOTAS", font=f_brand, fill=(255, 255, 255, 255))
    d.text((112, 64), tag_text, font=f_tag, fill=(251, 146, 60, 255))

    rw = d.textlength(right_text, font=f_right)
    d.rounded_rectangle((1152 - rw - 32, 38, 1152, 78), radius=20, fill=(255, 255, 255, 26), outline=(255, 255, 255, 55), width=1)
    d.text((1152 - rw - 16, 46), right_text, font=f_right, fill=(226, 232, 240, 255))


def _form_dots(d: ImageDraw.ImageDraw, x: int, y: int, scores: list[str]) -> None:
    f_dot = _load_font(15, bold=True)
    for idx, s in enumerate(scores[-5:]):
        try:
            gf, ga = map(int, s.split("-"))
        except Exception:
            continue
        col = (34, 197, 94, 240) if gf > ga else ((100, 116, 139, 230) if gf == ga else (239, 68, 68, 240))
        lbl = "G" if gf > ga else ("E" if gf == ga else "P")
        bx = x + idx * 34
        d.rounded_rectangle((bx, y, bx + 28, y + 28), radius=8, fill=col)
        d.text((bx + 8, y + 4), lbl, font=f_dot, fill=(255, 255, 255, 255))


def render_match_card(m: dict) -> bytes:
    """Render a graphical 1200x675 PNG card for a match with probabilities, form, and odds."""
    img = _create_backdrop()
    _draw_brand_header(img, f"RADAR • {m.get('league_label', m['league']).upper()}", f"{m['kickoff_col']} COL")
    _glass_panel(img, (48, 108, 1152, 632), radius=28)

    d = ImageDraw.Draw(img)
    f_team = _load_font(34, bold=True)
    f_sub = _load_font(19, bold=False)
    f_lbl = _load_font(18, bold=True)
    f_big = _load_font(28, bold=True)

    # Match header
    title = f"{m['home']}   vs   {m['away']}"
    tw = d.textlength(title, font=f_team)
    if tw > 1040:
        f_team = _load_font(27, bold=True)
        tw = d.textlength(title, font=f_team)
    d.text(((1200 - tw) / 2, 134), title, font=f_team, fill=(255, 255, 255, 255))

    # Stacked market-implied 1 / X / 2 probability bar
    s_inv = 1.0 / m["o1"] + 1.0 / m["ox"] + 1.0 / m["o2"]
    p1 = (1.0 / m["o1"]) / s_inv
    px = (1.0 / m["ox"]) / s_inv
    p2 = (1.0 / m["o2"]) / s_inv

    bar_x, bar_y, bar_w, bar_h = 96, 198, 1008, 26
    w1 = int(bar_w * p1)
    wx = int(bar_w * px)
    w2 = bar_w - w1 - wx
    d.rounded_rectangle((bar_x, bar_y, bar_x + w1, bar_y + bar_h), radius=10, fill=(139, 92, 246, 255))
    d.rectangle((bar_x + w1 + 2, bar_y, bar_x + w1 + wx - 2, bar_y + bar_h), fill=(148, 163, 184, 220))
    d.rounded_rectangle((bar_x + w1 + wx, bar_y, bar_x + bar_w, bar_y + bar_h), radius=10, fill=(249, 115, 22, 255))

    d.text((bar_x, 232), f"Local {p1*100:.0f}% (@{m['o1']:.2f})", font=f_lbl, fill=(196, 181, 253, 255))
    mid_txt = f"Empate {px*100:.0f}% (@{m['ox']:.2f})"
    mw = d.textlength(mid_txt, font=f_lbl)
    d.text((600 - mw / 2, 232), mid_txt, font=f_lbl, fill=(203, 213, 225, 255))
    r_txt = f"Visita {p2*100:.0f}% (@{m['o2']:.2f})"
    rw = d.textlength(r_txt, font=f_lbl)
    d.text((bar_x + bar_w - rw, 232), r_txt, font=f_lbl, fill=(253, 186, 116, 255))

    # Left & Right team glass boxes
    _glass_panel(img, (84, 276, 584, 520), radius=20, fill=(255, 255, 255, 16))
    _glass_panel(img, (616, 276, 1116, 520), radius=20, fill=(255, 255, 255, 16))
    d = ImageDraw.Draw(img)

    hs, as_ = m["h_stat"], m["a_stat"]
    for bx, name, st, scores, col in [
        (110, f"LOCAL: {m['home'][:22]}", hs, m.get("h_recent_scores", []), (139, 92, 246, 255)),
        (642, f"VISITA: {m['away'][:22]}", as_, m.get("a_recent_scores", []), (249, 115, 22, 255)),
    ]:
        d.text((bx, 294), name, font=f_lbl, fill=(255, 255, 255, 255))
        d.text((bx, 330), f"Victorias: {st['win_pct']*100:.0f}%", font=f_sub, fill=(226, 232, 240, 255))
        _draw_progress_bar(d, bx + 175, 336, 270, 12, st["win_pct"], col)

        d.text((bx, 366), f"No pierde: {st['unbeaten_pct']*100:.0f}%", font=f_sub, fill=(226, 232, 240, 255))
        _draw_progress_bar(d, bx + 175, 372, 270, 12, st["unbeaten_pct"], (34, 197, 94, 235))

        d.text((bx, 402), f"+0.5 goles: {st['o05_pct']*100:.0f}%", font=f_sub, fill=(226, 232, 240, 255))
        _draw_progress_bar(d, bx + 175, 408, 270, 12, st["o05_pct"], (56, 189, 248, 235))

        d.text((bx, 440), f"Prom. Goles: {st['gf_avg']:.2f} GF / {st['ga_avg']:.2f} GA", font=f_sub, fill=(203, 213, 225, 255))
        _form_dots(d, bx, 474, scores)

    # Bottom pick highlight bar
    pick_txt = "Sin señal 1.20–1.90 en filtros actuales"
    ev_txt = "Solo radar estadístico"
    ev_col = (148, 163, 184, 255)
    if m.get("opt_b_pick"):
        pb = m["opt_b_pick"]
        pick_txt = f"Opción B: {pb['market_name']}  @~{pb['odds']:.2f}  (Prob {pb['prob']}%)"
        ev_txt = f"EV {pb['ev_pct']:+.1f}%"
        ev_col = (74, 222, 128, 255) if pb["ev_pct"] > 0 else (251, 191, 36, 255)
    elif m.get("opt_a_leg"):
        pa = m["opt_a_leg"]
        pick_txt = f"Pata Opción A: {pa['market_name']}  @{pa['odds']:.2f}  (Prob {pa['prob']}%)"
        ev_txt = f"EV {pa['ev_pct']:+.1f}%"
        ev_col = (74, 222, 128, 255) if pa["ev_pct"] > 0 else (251, 191, 36, 255)

    _glass_panel(img, (84, 540, 1116, 610), radius=18, fill=(124, 58, 237, 55), border=(167, 139, 250, 110))
    d = ImageDraw.Draw(img)
    d.text((108, 560), pick_txt, font=_load_font(22, bold=True), fill=(255, 255, 255, 255))
    ew = d.textlength(ev_txt, font=f_big)
    d.text((1092 - ew, 556), ev_txt, font=f_big, fill=ev_col)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_parlay_card(parlay: dict) -> bytes:
    """Render a graphical 1200x675 PNG ticket card for a 2-match parlay (Option A)."""
    img = _create_backdrop()
    _draw_brand_header(img, "POSIBLE COMBINADA • OPCIÓN A (1.20–1.90)", f"{parlay['kickoff_col']} COL")
    _glass_panel(img, (48, 108, 1152, 632), radius=28)

    d = ImageDraw.Draw(img)
    f_leg = _load_font(25, bold=True)
    f_sub = _load_font(20, bold=False)

    # Leg 1 & Leg 2 glass cards
    for idx, leg_txt in enumerate([parlay["leg1"], parlay["leg2"]]):
        y0 = 148 + idx * 146
        _glass_panel(img, (88, y0, 1112, y0 + 118), radius=20, fill=(255, 255, 255, 18))
        d = ImageDraw.Draw(img)
        parts = leg_txt.split(":", 1)
        match_part = parts[0].strip()
        pick_part = parts[1].strip() if len(parts) > 1 else ""
        d.text((118, y0 + 20), f"SELECCIÓN {idx + 1} • {match_part}", font=f_sub, fill=(196, 181, 253, 255))
        d.text((118, y0 + 54), pick_part, font=f_leg, fill=(255, 255, 255, 255))

    # Bottom odds & probability gauge
    _glass_panel(img, (88, 456, 1112, 598), radius=22, fill=(249, 115, 22, 38), border=(251, 146, 60, 130))
    d = ImageDraw.Draw(img)
    d.text((120, 478), "CUOTA FINAL", font=_load_font(18, bold=True), fill=(253, 186, 116, 255))
    d.text((120, 506), f"@{parlay['combo_odds']:.2f}", font=_load_font(48, bold=True), fill=(255, 255, 255, 255))

    d.text((380, 480), f"Probabilidad Estimada: {parlay['prob_est']}%   |   Implícita Casa: {parlay['prob_impl']}%", font=f_sub, fill=(241, 245, 249, 255))
    _draw_progress_bar(d, 380, 520, 460, 18, parlay["prob_est"] / 100.0, (74, 222, 128, 255) if parlay["ev_pct"] > 0 else (251, 191, 36, 255))

    ev_col = (74, 222, 128, 255) if parlay["ev_pct"] > 0 else (251, 191, 36, 255)
    ev_lbl = f"EV {parlay['ev_pct']:+.1f}%"
    d.text((880, 496), ev_lbl, font=_load_font(34, bold=True), fill=ev_col)
    d.text((880, 542), "Ventaja +EV" if parlay["ev_pct"] > 0 else "Ojo: margen casa", font=_load_font(17, bold=False), fill=ev_col)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
