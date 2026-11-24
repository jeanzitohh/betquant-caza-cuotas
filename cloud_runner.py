import datetime as dt

from bot_scanner import DEFAULT_LEAGUES, run_scan_pipeline, run_settle_pipeline
from build_static_site import export_static_site
from paper_db import PaperTradingDB
from providers import load_env
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

    # 3. Publicar novedades al Canal de Telegram y responder comandos en cola si hay token
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

    # 4. Generar sitio estático en docs/ para GitHub Pages
    out_dir = export_static_site(scan_res, db.get_summary())
    print(f"Sitio estático actualizado en {out_dir}")


if __name__ == "__main__":
    main()
