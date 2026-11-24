import datetime as dt

from bot_scanner import DEFAULT_LEAGUES, grade_market, run_scan_pipeline, run_settle_pipeline
from build_static_site import export_static_site
from paper_db import PaperTradingDB
from providers import fetch_espn_match_result, load_env
from supabase_sync import settle_supabase_bets, upsert_radar_snapshot
from telegram_bot import poll_updates, publish_channel_updates


def main() -> None:
    env = load_env()
    print("=== Cloud Runner iniciado ===", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))

    # 1. Liquidar resultados terminados antes de escanear
    settle_res = run_settle_pipeline()
    print(f"Liquidación: {settle_res['settled_now']} actualizadas, {settle_res['still_pending']} pendientes.")

    # 2. Escanear próximos partidos (Colombia + Europa) y guardar en SQLite
    scan_res = run_scan_pipeline(leagues=DEFAULT_LEAGUES, days=4, save=True)
    print(f"Escaneo: {scan_res['total_matches']} partidos próximos, {scan_res['saved_count']} nuevas jugadas.")

    db = PaperTradingDB()
    summary = db.get_summary()

    # 3. Sincronizar Supabase si hay credenciales configuradas
    sb_url = env.get("SUPABASE_URL", "").strip()
    sb_service = env.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if sb_url and sb_service:
        try:
            sb_settled, sb_pending = settle_supabase_bets(
                sb_url, sb_service, fetch_espn_match_result, grade_market
            )
            now_col = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")
            upsert_radar_snapshot(sb_url, sb_service, now_col, scan_res, summary)
            print(f"Supabase Sync OK: radar actualizado; apuestas usuarios {sb_settled} liquidadas, {sb_pending} pendientes.")
        except Exception as exc:
            print(f"Supabase Sync Error: {exc}")
    else:
        print("Supabase Sync omitido (faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")

    # 4. Publicar novedades al Canal de Telegram y responder comandos en cola si hay token
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = env.get("TELEGRAM_CHANNEL_ID", "").strip()
    if token:
        if channel_id:
            sent = publish_channel_updates(scan_res, db, token, channel_id)
            print(f"Telegram Canal: {sent} bloque(s) nuevos publicados.")
        else:
            print("Telegram Canal omitido (falta TELEGRAM_CHANNEL_ID).")
        handled = poll_updates(token, db, timeout_s=0)
        print(f"Telegram Bot (cola): {handled} comando(s) respondidos.")
    else:
        print("Telegram omitido (falta TELEGRAM_BOT_TOKEN).")

    # 5. Generar sitio estático en docs/ para GitHub Pages
    out_dir = export_static_site(scan_res, summary)
    print(f"Sitio estático actualizado en {out_dir}")


if __name__ == "__main__":
    main()
