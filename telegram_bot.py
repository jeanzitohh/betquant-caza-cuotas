import argparse
import html
import json
import time
import urllib.parse
import urllib.request
import uuid

from bot_scanner import DEFAULT_LEAGUES, run_scan_pipeline, run_settle_pipeline
from paper_db import PaperTradingDB
from providers import load_env

try:
    from card_renderer import literal_market_text, render_match_card, render_parlay_card

    HAS_CARDS = True
except ImportError:
    HAS_CARDS = False

    def literal_market_text(market_name: str, home: str, away: str) -> str:
        return market_name


MAIN_MENU_MARKUP = {
    "inline_keyboard": [
        [
            {"text": "🇨🇴 Colombia Hoy", "callback_data": "/colombia"},
            {"text": "🇪🇺 Europa Top", "callback_data": "/europa"},
        ],
        [
            {"text": "🪜 En Serie (Fibonacci)", "callback_data": "/serie"},
            {"text": "⏱ Próximo por Hora", "callback_data": "/proximo"},
        ],
        [
            {"text": "📊 Efectividad Diaria", "callback_data": "/efectividad"},
            {"text": "📈 Historial ROI", "callback_data": "/historial"},
        ],
    ]
}


def tg_api(token: str, method: str, params: dict | None = None, timeout: int = 20) -> dict | None:
    """Call Telegram Bot API using stdlib urllib."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8") if params else None
    try:
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
            return parsed if parsed.get("ok") else None
    except Exception:
        return None


def send_photo_bytes(token: str, chat_id: str, png_bytes: bytes, caption: str) -> bool:
    """Upload a PNG forecast card to Telegram using multipart/form-data."""
    if not token or not chat_id or not png_bytes:
        return False
    boundary = f"----CazaCuotas{uuid.uuid4().hex}"
    fields = {"chat_id": chat_id, "caption": caption[:1000], "parse_mode": "HTML"}
    body = bytearray()
    for k, v in fields.items():
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
    body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"caza_cuotas_card.png\"\r\nContent-Type: image/png\r\n\r\n".encode("utf-8"))
    body.extend(png_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = urllib.request.Request(url, data=bytes(body), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
            return bool(parsed.get("ok"))
    except Exception:
        return False


def send_html(token: str, chat_id: str, text: str, reply_markup: dict | None = None) -> bool:
    """Send Telegram HTML message safely (splits if exceeding 3900 chars)."""
    if not token or not chat_id or not text.strip():
        return False
    chunks = [text[i : i + 3800] for i in range(0, len(text), 3800)]
    ok_all = True
    for idx, ch in enumerate(chunks):
        payload = {"chat_id": chat_id, "text": ch, "parse_mode": "HTML", "disable_web_page_preview": "true"}
        if reply_markup and idx == len(chunks) - 1:
            payload["reply_markup"] = json.dumps(reply_markup)
        res = tg_api(token, "sendMessage", payload)
        if not res:
            ok_all = False
    return ok_all


def format_match_stats_block(matches: list[dict], title: str) -> str:
    if not matches:
        return f"<b>{html.escape(title)}</b>\n<i>Sin partidos próximos con cuotas en este rango.</i>"
    lines = [f"<b>{html.escape(title)}</b>"]
    for m in matches[:10]:
        hs, as_ = m["h_stat"], m["a_stat"]
        racha_h = "".join(
            "G" if int(s.split("-")[0]) > int(s.split("-")[1]) else ("E" if s.split("-")[0] == s.split("-")[1] else "P")
            for s in m.get("h_recent_scores", [])[-5:]
        ) or "s/d"
        racha_a = "".join(
            "G" if int(s.split("-")[0]) > int(s.split("-")[1]) else ("E" if s.split("-")[0] == s.split("-")[1] else "P")
            for s in m.get("a_recent_scores", [])[-5:]
        ) or "s/d"
        lines.append(
            f"\n<b>{html.escape(m['home'])} vs {html.escape(m['away'])}</b> ({html.escape(m['league'])})\n"
            f"🕒 <code>{m['kickoff_col']} COL</code>\n"
            f"📊 Local: G <b>{hs['win_pct']*100:.0f}%</b> | 1X <b>{hs['unbeaten_pct']*100:.0f}%</b> | GF <b>{hs['gf_avg']:.2f}</b> [{racha_h}]\n"
            f"📊 Visita: G <b>{as_['win_pct']*100:.0f}%</b> | X2 <b>{as_['unbeaten_pct']*100:.0f}%</b> | GF <b>{as_['gf_avg']:.2f}</b> [{racha_a}]\n"
            f"💰 Cuotas 1X2: <code>{m['o1']:.2f} | {m['ox']:.2f} | {m['o2']:.2f}</code>"
            + (f" (O/U {m['ou_line']})" if m.get("ou_line") else "")
        )
    return "\n".join(lines)


def format_picks_block(scan: dict) -> str:
    lines = ["<b>🎯 CAZA CUOTAS • POSIBLES APUESTAS (1.20 - 1.90)</b>"]
    if scan.get("sharp_picks"):
        lines.append("\n<b>✅ Valor +EV vs Pinnacle/Betfair:</b>")
        for s in scan["sharp_picks"][:6]:
            lines.append(
                f"• <b>{html.escape(s['title'])}</b> ({html.escape(s['league'])})\n"
                f"  {html.escape(s['market_name'])} @<code>{s['odds']}</code> ({html.escape(s['bookmaker'])}) | EV: <b>{s['ev_pct']:+.1f}%</b>"
            )

    if scan.get("parlays_a"):
        lines.append("\n<b>📌 Opción A — Combinada de 2 partidos:</b>")
        for p in scan["parlays_a"][:6]:
            tag = "✅ +EV" if p["ev_pct"] > 0 else "⚠️ EV negativo por margen"
            lines.append(
                f"• Cuota <b>@{p['combo_odds']:.2f}</b> ({tag})\n"
                f"  1) 🕒 <code>{p.get('leg1_kickoff', p['kickoff_col'])} COL</code> • {html.escape(p['leg1'])}\n"
                f"  2) 🕒 <code>{p.get('leg2_kickoff', p['kickoff_col'])} COL</code> • {html.escape(p['leg2'])}\n"
                f"  Est: {p['prob_est']}% vs Impl: {p['prob_impl']}% (EV {p['ev_pct']:+.1f}%)"
            )

    if scan.get("opt_b"):
        lines.append("\n<b>📌 Opción B — Mismo partido (Bet Builder):</b>")
        for b in scan["opt_b"][:6]:
            tag = "✅ +EV" if b["ev_pct"] > 0 else "⚠️ EV negativo por margen"
            lines.append(
                f"• 🕒 <code>{b['kickoff_col']} COL</code> • <b>{html.escape(b['title'])}</b> ({html.escape(b['league'])})\n"
                f"  {html.escape(b['market_name'])} @~<code>{b['odds']:.2f}</code> ({tag})\n"
                f"  Est: {b['prob_est']}% vs Impl: {b['prob_impl']}% (EV {b['ev_pct']:+.1f}%)"
            )

    if len(lines) == 1:
        lines.append("\n<i>Ninguna combinada cumplió todos los filtros en este escaneo.</i>")
    return "\n".join(lines)


def format_history_block(rep: dict) -> str:
    acc = rep.get("accuracy_pct", 0.0)
    return (
        "<b>📈 CAZA CUOTAS • PAPER TRADING</b>\n"
        f"• Efectividad global: <b>{rep['won']} de {rep['settled']} ({acc:.1f}%)</b>\n"
        f"• Bankroll: <b>{rep['bankroll_u']:.2f}u</b> (Base 100u)\n"
        f"• ROI acumulado: <b>{rep['roi_pct']:+.2f}%</b> ({rep['total_profit_u']:+.2f}u)\n"
        f"• Pendientes: <b>{rep['pending']}</b>"
    )


def format_daily_effectiveness_block(rep: dict) -> str:
    lines = ["<b>📊 CAZA CUOTAS • EFECTIVIDAD DIARIA Y AUTO-MEJORA</b>"]
    daily = rep.get("daily_stats") or []
    settled_days = [d for d in daily if d["settled"] > 0]
    if settled_days:
        latest = settled_days[0]
        lines.append(
            f"\n🎯 <b>Último día medido ({latest['date']}):</b> "
            f"<b>{latest['won']} de {latest['settled']} efectivos ({latest['accuracy_pct']}%)</b> "
            f"| Neto: <b>{latest['profit_u']:+.2f}u</b>"
        )
        lines.append("\n<b>Desglose reciente por día:</b>")
        for d in daily[:7]:
            if d["settled"] > 0:
                lines.append(
                    f"• <code>{d['date']}</code>: <b>{d['won']}/{d['settled']}</b> ({d['accuracy_pct']}%) "
                    f"| {d['profit_u']:+.2f}u ({d['pending']} pend.)"
                )
            else:
                lines.append(f"• <code>{d['date']}</code>: {d['pending']} pendientes por jugar")
    else:
        lines.append(
            f"\n<i>Aún no hay partidos liquidados hoy. Hay {rep['pending']} pronósticos pendientes en seguimiento.</i>"
        )

    cal = rep.get("calibration") or {}
    if cal:
        lines.append("\n<b>🧠 Auto-Calibración por Mercado:</b>")
        ranked = sorted(cal.items(), key=lambda x: (x[1]["settled"], x[1]["win_rate_pct"]), reverse=True)[:5]
        for mk, info in ranked:
            lines.append(f"• <code>{mk}</code>: {info['won']}/{info['settled']} ({info['win_rate_pct']}%) — {info['status']}")
    return "\n".join(lines)


def format_next_by_hour_block(scan: dict) -> str:
    lines = ["<b>⏱ PRÓXIMOS PARTIDOS POR HORA (RADAR GLOBAL)</b>"]
    g_list = scan.get("next_global") or []
    for m in g_list[:8]:
        lines.append(
            f"\n🕒 <code>{m['kickoff_col']} COL</code> • <b>{html.escape(m['home'])} vs {html.escape(m['away'])}</b>\n"
            f"🏆 {html.escape(m['league_label'])} | 1X2: <code>{m['o1']:.2f} / {m['ox']:.2f} / {m['o2']:.2f}</code>"
        )
    if not g_list:
        lines.append("\n<i>Sin partidos próximos encontrados en este instante.</i>")
    return "\n".join(lines)


def format_serial_ladder_block(scan: dict) -> str:
    lines = [
        "<b>🪜 RUTA EN SERIE • FIBONACCI PASO A PASO</b>",
        "<i>1 partido por turno (≥2h30 entre inicios). Termina uno, miras si ganaste (vuelves a 1) o perdiste (subes escalón) antes del siguiente.</i>",
    ]
    ladder = scan.get("serial_ladder") or []
    for s in ladder[:8]:
        lines.append(
            f"\n<b>Turno #{s['step']}</b> • 🕒 <code>{s['kickoff_col']} COL</code> <i>({s['gap_label']})</i>\n"
            f"⚽ <b>{html.escape(s['title'])}</b> ({html.escape(s['league_label'])})\n"
            f"👉 <b>{html.escape(s['market_name'])}</b> @<code>{s['odds']:.2f}</code> | Prob: <b>{s['prob']}%</b> (EV {s['ev_pct']:+.1f}%)"
        )
    if not ladder:
        lines.append("\n<i>Sin partidos disponibles para armar la escalera en serie.</i>")
    return "\n".join(lines)


def _build_detailed_match_caption(m: dict) -> str:
    """Build explicit Spanish breakdown caption for Telegram photo/text posts."""
    hs, as_ = m["h_stat"], m["a_stat"]
    ps = m.get("probs_summary") or {}
    s_inv = 1.0 / m["o1"] + 1.0 / m["ox"] + 1.0 / m["o2"]
    p1 = (1.0 / m["o1"]) / s_inv * 100.0
    px = (1.0 / m["ox"]) / s_inv * 100.0
    p2 = (1.0 / m["o2"]) / s_inv * 100.0

    if p1 >= 52:
        fav_txt = f"Favorito: <b>{html.escape(m['home'])}</b> ({p1:.0f}% ganar | {p1+px:.0f}% 1X)"
    elif p2 >= 52:
        fav_txt = f"Favorito: <b>{html.escape(m['away'])}</b> ({p2:.0f}% ganar | {p2+px:.0f}% X2)"
    else:
        fav_txt = f"Partido parejo (ligero fav. {html.escape(m['home'] if p1 >= p2 else m['away'])} {max(p1, p2):.0f}%)"

    pick_line = "<i>Sin combinada 1.20–1.90 en filtros actuales.</i>"
    if m.get("opt_b_pick"):
        pb = m["opt_b_pick"]
        lit = literal_market_text(pb["market_name"], m["home"], m["away"])
        pick_line = f"👉 <b>{html.escape(lit)}</b> @~<code>{pb['odds']:.2f}</code> (Prob {pb['prob']}% | EV {pb['ev_pct']:+.1f}%)"
    elif m.get("opt_a_leg"):
        pa = m["opt_a_leg"]
        lit = literal_market_text(pa["market_name"], m["home"], m["away"])
        pick_line = f"👉 <b>{html.escape(lit)}</b> @<code>{pa['odds']:.2f}</code> (Prob {pa['prob']}% | EV {pa['ev_pct']:+.1f}%)"

    return (
        f"⚽ <b>{html.escape(m['home'])} vs {html.escape(m['away'])}</b>\n"
        f"🏆 {html.escape(m.get('league_label', m['league']))} • 🕒 <code>{m['kickoff_col']} COL</code>\n\n"
        f"📌 <b>GANADOR:</b> {fav_txt}\n"
        f"• {html.escape(m['home'])}: <b>{p1:.0f}%</b> (<code>@{m['o1']:.2f}</code>) | Empate: <b>{px:.0f}%</b> (<code>@{m['ox']:.2f}</code>) | {html.escape(m['away'])}: <b>{p2:.0f}%</b> (<code>@{m['o2']:.2f}</code>)\n\n"
        f"⚽ <b>GOLES ESPERADOS Y PORCENTAJES:</b>\n"
        f"• Promedio esperado: {html.escape(m['home'])} <b>~{m.get('lam_h', 1.3):.2f}</b> vs {html.escape(m['away'])} <b>~{m.get('lam_a', 1.1):.2f}</b>\n"
        f"• {html.escape(m['home'])} anota +0.5: <b>{ps.get('h_o05', hs['o05_pct']*100):.0f}%</b> (+1.5: <b>{ps.get('h_o15', hs['o15_pct']*100):.0f}%</b>)\n"
        f"• {html.escape(m['away'])} anota +0.5: <b>{ps.get('a_o05', as_['o05_pct']*100):.0f}%</b> (+1.5: <b>{ps.get('a_o15', as_['o15_pct']*100):.0f}%</b>)\n"
        f"• Partido +1.5 goles: <b>{ps.get('o15', 70):.0f}%</b> | +2.5: <b>{ps.get('o25', 45):.0f}%</b> | Ambos marcan: <b>{ps.get('btts', 45):.0f}%</b>\n\n"
        f"🎯 <b>APUESTA LITERAL:</b>\n{pick_line}"
    )


def publish_channel_updates(scan: dict, db: PaperTradingDB, token: str, channel_id: str) -> int:
    """Publish graphical forecast PNG cards and settled results to the Caza Cuotas Channel."""
    if not token or not channel_id:
        return 0
    sent_count = 0

    # 1. Graphical Match Cards: ALWAYS include today's Colombia matches + top European picks (cap 6 total per run)
    new_cards = []
    for m in scan.get("matches", []):
        if m["league"] != "col.1" and not (m.get("opt_a_leg") or m.get("opt_b_pick")):
            continue
        key = f"match_card_detailed_v1:{m['event_id']}"
        if not db.was_alert_sent(key):
            new_cards.append((key, m))

    # Prioritize Colombia matches first (so both Millonarios and América always go out) then Europe
    new_cards.sort(key=lambda item: (item[1]["league"] != "col.1", item[1]["kickoff_col"]))
    for key, m in new_cards[:6]:
        cap = _build_detailed_match_caption(m)
        if HAS_CARDS:
            png = render_match_card(m)
            if send_photo_bytes(token, channel_id, png, cap):
                db.mark_alert_sent(key)
                sent_count += 1
        else:
            if send_html(token, channel_id, cap):
                db.mark_alert_sent(key)
                sent_count += 1

    # 2. Graphical Parlay Cards for new Option A picks (deduped by event_ids, not fluctuating odds)
    for p in scan.get("parlays_a", [])[:4]:
        leg_ids = "+".join(leg["event_id"] + ":" + leg["market"] for leg in (p.get("legs") or [])) or (p["leg1"] + "+" + p["leg2"])
        key = f"pick_a_v3:{leg_ids}"
        if db.was_alert_sent(key):
            continue
        if HAS_CARDS:
            png = render_parlay_card(p)
            cap = (
                f"🎯 <b>CAZA CUOTAS • COMBINADA DEL MISMO DÍA (@{p['combo_odds']:.2f})</b>\n"
                f"1️⃣ 🕒 <code>{p.get('leg1_kickoff', p['kickoff_col'])} COL</code> • {html.escape(p['leg1'])}\n"
                f"2️⃣ 🕒 <code>{p.get('leg2_kickoff', p['kickoff_col'])} COL</code> • {html.escape(p['leg2'])}\n"
                f"📊 Probabilidad real conjunta: <b>{p['prob_est']}%</b> (EV {p['ev_pct']:+.1f}%)"
            )
            if send_photo_bytes(token, channel_id, png, cap):
                db.mark_alert_sent(key)
                sent_count += 1
        else:
            if send_html(token, channel_id, format_picks_block({"parlays_a": [p]})):
                db.mark_alert_sent(key)
                sent_count += 1

    # 3. Newly settled trades
    settled_msgs = []
    for tr in db.get_recent_settled(limit=25):
        key = f"settled:{tr['id']}:{tr['status']}"
        if not db.was_alert_sent(key):
            icon = "✅ GANADA" if tr["status"] == "WON" else "❌ PERDIDA"
            settled_msgs.append(
                f"{icon} | <b>{html.escape(tr['title'])}</b>\n"
                f"  {html.escape(tr['market'])} @<code>{tr['odds']}</code> → <b>{tr['profit_u']:+.2f}u</b> ({html.escape(tr.get('result_note') or '')})"
            )
            db.mark_alert_sent(key)
    if settled_msgs:
        rep = db.get_summary()
        body = "<b>🏁 CAZA CUOTAS • RESULTADOS LIQUIDADOS</b>\n\n" + "\n\n".join(settled_msgs) + "\n\n" + format_daily_effectiveness_block(rep)
        if send_html(token, channel_id, body):
            sent_count += 1
    else:
        rep = db.get_summary()
        settled_days = [d for d in (rep.get("daily_stats") or []) if d["settled"] > 0]
        if settled_days:
            d0 = settled_days[0]
            eff_key = f"daily_eff_v1:{d0['date']}:{d0['won']}/{d0['settled']}"
            if not db.was_alert_sent(eff_key):
                if send_html(token, channel_id, format_daily_effectiveness_block(rep)):
                    db.mark_alert_sent(eff_key)
                    sent_count += 1

    # 4. Daily Serial Fibonacci Ladder (1 pick every ~2h30-3h so users bet in series)
    ladder = scan.get("serial_ladder") or []
    if ladder:
        l_key = f"serial_ladder_v1:{ladder[0]['kickoff_col'][:10]}:{ladder[0]['event_id']}"
        if not db.was_alert_sent(l_key):
            if send_html(token, channel_id, format_serial_ladder_block(scan)):
                db.mark_alert_sent(l_key)
                sent_count += 1

    return sent_count


def handle_command(text: str, chat_id: str = "") -> str:
    cmd = (text or "").strip().split()[0].lower().split("@")[0]
    if cmd == "/id":
        return f"Tu Chat ID es: <code>{html.escape(chat_id)}</code>"
    if cmd in ("/start", "/ayuda", "/help"):
        return (
            "<b>🦝 Caza Cuotas Bot — Menú Principal</b>\n\n"
            "Usa los botones de abajo o escribe un comando:\n"
            "• /colombia — Liga BetPlay (rachas y cuotas)\n"
            "• /europa — Top 5 Europa + Champions\n"
            "• /serie — Ruta en serie cada ~3h para Fibonacci (1 por vez)\n"
            "• /apuestas — Combinadas del mismo día y Bet Builder\n"
            "• /proximo — Próximos partidos por hora (radar mundial)\n"
            "• /efectividad — Efectividad diaria (X de Y) y auto-calibración\n"
            "• /historial — Rendimiento Paper Trading\n"
            "• /liquidar — Actualizar marcadores finales\n\n"
            "<i>Modo simulación estadística (sin dinero real).</i>"
        )
    if cmd == "/colombia":
        scan = run_scan_pipeline(leagues=["col.1"], days=5, save=False)
        return format_match_stats_block(scan["matches"], "🇨🇴 CAZA CUOTAS • LIGA BETPLAY")
    if cmd == "/europa":
        eu = [l for l in DEFAULT_LEAGUES if l != "col.1"]
        scan = run_scan_pipeline(leagues=eu, days=3, save=False)
        return format_match_stats_block(scan["matches"], "🇪🇺 CAZA CUOTAS • EUROPA")
    if cmd == "/serie":
        scan = run_scan_pipeline(leagues=DEFAULT_LEAGUES, days=3, save=False)
        return format_serial_ladder_block(scan)
    if cmd == "/apuestas":
        scan = run_scan_pipeline(leagues=DEFAULT_LEAGUES, days=4, save=False)
        return format_picks_block(scan)
    if cmd == "/proximo":
        scan = run_scan_pipeline(leagues=DEFAULT_LEAGUES, days=2, save=False)
        return format_next_by_hour_block(scan)
    if cmd == "/efectividad":
        return format_daily_effectiveness_block(PaperTradingDB().get_summary())
    if cmd == "/historial":
        return format_history_block(PaperTradingDB().get_summary())
    if cmd == "/liquidar":
        st = run_settle_pipeline()
        rep = PaperTradingDB().get_summary()
        return f"Liquidación ejecutada: <b>{st['settled_now']}</b> actualizadas, {st['still_pending']} pendientes.\n\n{format_daily_effectiveness_block(rep)}"
    return "Comando no reconocido. Toca un botón o usa /ayuda."


def poll_updates(token: str, db: PaperTradingDB, timeout_s: int = 0) -> int:
    """Process incoming Telegram bot commands and inline button callbacks."""
    if not token:
        return 0
    offset_str = db.get_state("tg_offset", "0")
    offset = int(offset_str) if offset_str.isdigit() else 0
    res = tg_api(token, "getUpdates", {"offset": offset, "timeout": timeout_s}, timeout=timeout_s + 10)
    if not res:
        return 0
    handled = 0
    max_uid = offset
    for upd in res.get("result", []):
        uid = upd.get("update_id", 0)
        if uid >= max_uid:
            max_uid = uid + 1
        cb = upd.get("callback_query")
        if cb:
            cb_id = cb.get("id")
            chat_id = str(((cb.get("message") or {}).get("chat") or {}).get("id") or "")
            data = cb.get("data", "")
            if cb_id:
                tg_api(token, "answerCallbackQuery", {"callback_query_id": cb_id})
            if chat_id and data.startswith("/"):
                send_html(token, chat_id, handle_command(data, chat_id=chat_id), reply_markup=MAIN_MENU_MARKUP)
                handled += 1
            continue

        msg = upd.get("message") or {}
        txt = msg.get("text", "")
        chat_id = str((msg.get("chat") or {}).get("id") or "")
        if chat_id and txt.startswith("/"):
            reply = handle_command(txt, chat_id=chat_id)
            send_html(token, chat_id, reply, reply_markup=MAIN_MENU_MARKUP)
            handled += 1
    if max_uid > offset:
        db.set_state("tg_offset", str(max_uid))
    return handled


def run_polling_24_7() -> None:
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Configura TELEGRAM_BOT_TOKEN en .env o variables de entorno para iniciar el bot 24/7.")
    db = PaperTradingDB()
    print("Caza Cuotas Telegram Bot conectado 24/7 (Ctrl+C para detener)...")
    while True:
        try:
            poll_updates(token, db, timeout_s=25)
        except KeyboardInterrupt:
            print("Bot detenido.")
            break
        except Exception as exc:
            print("Error temporal en polling:", exc)
            time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot y publicador gráfico del Canal Caza Cuotas")
    parser.add_argument("mode", choices=["poll", "once", "test-channel"], help="poll (24/7), once (cola), test-channel (enviar tarjetas al canal)")
    args = parser.parse_args()

    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    channel = env.get("TELEGRAM_CHANNEL_ID", "").strip()

    if args.mode == "poll":
        run_polling_24_7()
    elif args.mode == "once":
        n = poll_updates(token, PaperTradingDB(), timeout_s=0)
        print(f"Comandos pendientes atendidos: {n}")
    elif args.mode == "test-channel":
        if not token or not channel:
            raise SystemExit("Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHANNEL_ID en .env")
        scan = run_scan_pipeline(leagues=DEFAULT_LEAGUES, days=4, save=True)
        n = publish_channel_updates(scan, PaperTradingDB(), token, channel)
        print(f"Tarjetas/mensajes publicados al canal: {n}")


if __name__ == "__main__":
    main()
