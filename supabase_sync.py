import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request

FIB_SEQ = (1, 2, 3, 5, 8)


def _sb_request(
    supabase_url: str,
    service_key: str,
    path: str,
    method: str = "GET",
    payload: object | None = None,
    prefer: str | None = None,
) -> object:
    base = supabase_url.rstrip("/")
    url = f"{base}/rest/v1/{path.lstrip('/')}"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8").strip()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Supabase REST {method} {path} -> HTTP {exc.code}: {err_body}") from exc


def upsert_radar_snapshot(
    supabase_url: str,
    service_key: str,
    generated_col: str,
    scan_res: dict,
    report_res: dict,
) -> None:
    """Persist the latest radar snapshot in Supabase (accessible only to authenticated users)."""
    row = {
        "id": 1,
        "generated_col": generated_col,
        "scan_json": scan_res,
        "report_json": report_res,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _sb_request(
        supabase_url,
        service_key,
        "radar_snapshots?on_conflict=id",
        method="POST",
        payload=[row],
        prefer="resolution=merge-duplicates,return=minimal",
    )


def settle_supabase_bets(
    supabase_url: str,
    service_key: str,
    fetch_match_result_fn,
    grade_market_fn,
) -> tuple[int, int]:
    """Check pending user_bets in Supabase against ESPN final scores and update status + fib_step."""
    pending = _sb_request(
        supabase_url,
        service_key,
        "user_bets?status=eq.PENDING&select=id,user_id,odds,stake_u,legs_json&order=id.asc",
        method="GET",
    ) or []

    if not pending:
        return 0, 0

    profiles = _sb_request(
        supabase_url,
        service_key,
        "user_profiles?select=user_id,stake_mode,fib_step",
        method="GET",
    ) or []
    prof_map = {p["user_id"]: p for p in profiles}

    settled_now = 0
    still_pending = 0
    score_cache: dict[tuple[str, str, str], tuple[bool, int, int] | None] = {}

    for bet in pending:
        legs = bet.get("legs_json") or []
        if not legs:
            still_pending += 1
            continue

        all_finished = True
        any_lost = False
        notes: list[str] = []

        for leg in legs:
            key = (str(leg.get("league", "")), str(leg.get("match_date", "")), str(leg.get("event_id", "")))
            if key not in score_cache:
                score_cache[key] = fetch_match_result_fn(*key)
            res = score_cache[key]
            if res is None:
                all_finished = False
                continue
            finished, hg, ag = res
            if not finished:
                all_finished = False
                continue
            notes.append(f"{hg}-{ag}")
            if not grade_market_fn(str(leg.get("market", "")), hg, ag):
                any_lost = True

        if not any_lost and not all_finished:
            still_pending += 1
            continue

        won = not any_lost and all_finished
        status = "WON" if won else "LOST"
        stake_u = float(bet["stake_u"])
        odds = float(bet["odds"])
        profit_u = round(stake_u * (odds - 1.0), 3) if won else round(-stake_u, 3)

        bet_id = int(bet["id"])
        _sb_request(
            supabase_url,
            service_key,
            f"user_bets?id=eq.{bet_id}",
            method="PATCH",
            payload={
                "status": status,
                "profit_u": profit_u,
                "settled_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "result_note": ", ".join(notes),
            },
            prefer="return=minimal",
        )

        uid = bet["user_id"]
        prof = prof_map.get(uid)
        mode = (prof or {}).get("stake_mode", "flat")
        if prof and mode in ("fibonacci", "fibonacci_3"):
            cur_step = int(prof.get("fib_step", 0))
            if won:
                next_step = 0
            elif mode == "fibonacci_3":
                next_step = 0 if cur_step >= 2 else cur_step + 1
            else:
                next_step = min(len(FIB_SEQ) - 1, cur_step + 1)
            prof["fib_step"] = next_step
            _sb_request(
                supabase_url,
                service_key,
                f"user_profiles?user_id=eq.{urllib.parse.quote(uid)}",
                method="PATCH",
                payload={"fib_step": next_step},
                prefer="return=minimal",
            )

        settled_now += 1

    return settled_now, still_pending


def send_web_push_broadcast(
    supabase_url: str,
    service_key: str,
    vapid_private_key: str,
    title: str,
    body_text: str,
    url: str = "./#canal",
) -> int:
    """Send Web Push notifications to all subscribed PWA users; prunes expired endpoints."""
    if not vapid_private_key:
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return 0

    subs = _sb_request(
        supabase_url,
        service_key,
        "push_subscriptions?select=endpoint,p256dh,auth",
        method="GET",
    ) or []
    if not subs:
        return 0

    payload = json.dumps({"title": title, "body": body_text[:180], "url": url}, ensure_ascii=False)
    sent = 0
    for s in subs:
        sub_info = {"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}
        try:
            webpush(
                subscription_info=sub_info,
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": "mailto:admin@cazacuotas.app"},
                ttl=3600,
            )
            sent += 1
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (404, 410):
                _sb_request(
                    supabase_url,
                    service_key,
                    f"push_subscriptions?endpoint=eq.{urllib.parse.quote(s['endpoint'], safe='')}",
                    method="DELETE",
                    prefer="return=minimal",
                )
        except Exception:
            pass
    return sent


def publish_supabase_channel(
    supabase_url: str,
    service_key: str,
    vapid_public_key: str,
    vapid_private_key: str,
    scan_res: dict,
    db,
    rep: dict,
) -> tuple[int, int]:
    """Publish rich graphic forecast cards, settled results, and serial turns into Supabase channel_posts."""
    from card_renderer import (
        literal_market_text,
        png_to_webp_data_url,
        render_daily_summary_card,
        render_match_card,
        render_parlay_card,
        render_serial_ladder_card,
        render_settled_card,
    )
    from telegram_bot import (
        _build_detailed_match_caption,
        format_daily_effectiveness_block,
        format_serial_ladder_block,
    )

    existing_rows = _sb_request(
        supabase_url,
        service_key,
        "channel_posts?select=post_key&order=id.desc&limit=150",
        method="GET",
    ) or []
    existing_keys = {r["post_key"] for r in existing_rows}

    new_rows: list[dict] = []
    push_headline = None

    # 1. Individual Match Cards (Colombia + top European matches, max 10)
    match_cands = [
        m
        for m in (scan_res.get("matches") or [])
        if m["league"] == "col.1" or m.get("opt_a_leg") or m.get("opt_b_pick")
    ]
    match_cands.sort(key=lambda m: (m["league"] != "col.1", m["kickoff_col"]))
    for m in match_cands[:10]:
        pkey = f"sb_match:{m['event_id']}"
        if pkey in existing_keys:
            continue
        cap = _build_detailed_match_caption(m)
        img_url = png_to_webp_data_url(render_match_card(m))
        title = f"{m['home']} vs {m['away']}"
        new_rows.append({"post_key": pkey, "kind": "match", "title": title, "body_html": cap, "image_data": img_url})
        push_headline = push_headline or ("Nuevo análisis: " + title, f"{m.get('league_label', '')} • {m['kickoff_col']} COL")

    # 2. Same-day Combinadas
    for p in (scan_res.get("parlays_a") or [])[:4]:
        leg_ids = "+".join(f"{leg['event_id']}:{leg['market']}" for leg in (p.get("legs") or [])) or p["title"]
        pkey = f"sb_combo:{leg_ids}"
        if pkey in existing_keys:
            continue
        cap = (
            f"🎯 <b>COMBINADA DEL DÍA (@{p['combo_odds']:.2f})</b>\n"
            f"1️⃣ 🕒 <code>{p.get('leg1_kickoff', p['kickoff_col'])} COL</code> • {p['leg1']}\n"
            f"2️⃣ 🕒 <code>{p.get('leg2_kickoff', p['kickoff_col'])} COL</code> • {p['leg2']}\n"
            f"📊 Probabilidad estimada: <b>{p['prob_est']}%</b>"
        )
        img_url = png_to_webp_data_url(render_parlay_card(p))
        new_rows.append({"post_key": pkey, "kind": "combo", "title": p["title"], "body_html": cap, "image_data": img_url})
        push_headline = push_headline or (f"Combinada @{p['combo_odds']:.2f}", p["title"])

    # 3. Serial Turn-by-Turn Ladders (Serie 1 & Serie 2, chunked 3 per card so image matches text 1:1)
    for serie_idx, l_key_name in ((1, "serial_ladder"), (2, "serial_ladder_2")):
        ladder = scan_res.get(l_key_name) or []
        if not ladder:
            continue
        chunks = [ladder[i : i + 3] for i in range(0, len(ladder), 3)]
        for c_idx, ch in enumerate(chunks, 1):
            pkey = f"sb_serie{serie_idx}:{ch[0]['kickoff_col'][:10]}:p{c_idx}:{ch[0]['event_id']}"
            if pkey in existing_keys:
                continue
            lbl = f"Serie {serie_idx} ({c_idx}/{len(chunks)})" if len(chunks) > 1 else f"Serie {serie_idx}"
            cap = format_serial_ladder_block(scan_res, items=ch, header_note=lbl)
            img_url = png_to_webp_data_url(render_serial_ladder_card(ch, chunk_label=lbl))
            new_rows.append({"post_key": pkey, "kind": "serie", "title": f"Turnos en Serie {serie_idx}", "body_html": cap, "image_data": img_url})
            push_headline = push_headline or (f"Turnos en Serie {serie_idx}", f"{ch[0]['title']} • {ch[0]['kickoff_col']} COL")

    # 4. Newly settled picks (deduped cleanly in SQLite so batches never repeat)
    recent_settled = db.get_recent_settled(limit=12)
    unposted_settled = [
        tr for tr in recent_settled
        if not db.was_alert_sent(f"sb_ch_settled:{tr['id']}:{tr['status']}")
        and f"sb_settled:{tr['id']}:{tr['status']}" not in existing_keys
    ]
    if unposted_settled:
        lines = ["<b>🏁 RESULTADOS LIQUIDADOS</b>"]
        for tr in unposted_settled[:6]:
            icon = "✅ GANADA" if tr["status"] == "WON" else "❌ PERDIDA"
            kind = "Combinada" if tr.get("strategy") == "FORMULA_OPT_A" else "Individual"
            lines.append(f"{icon} <i>[{kind}]</i> • <b>{tr['title']}</b> @<code>{tr['odds']}</code> ({tr['profit_u']:+.2f}u)")
            db.mark_alert_sent(f"sb_ch_settled:{tr['id']}:{tr['status']}")
        batch_key = f"sb_settled:{unposted_settled[0]['id']}:{unposted_settled[0]['status']}"
        img_url = png_to_webp_data_url(render_settled_card(unposted_settled[:5], rep))
        new_rows.append({
            "post_key": batch_key,
            "kind": "settled",
            "title": f"Resultados Liquidados ({len(unposted_settled)})",
            "body_html": "\n".join(lines),
            "image_data": img_url,
        })
        push_headline = (f"Resultados Liquidados ({rep.get('won',0)}/{rep.get('settled',0)} acertados)", unposted_settled[0]["title"])

    # 5. Daily Effectiveness Closing Card
    settled_days = [d for d in (rep.get("daily_stats") or []) if d["settled"] > 0]
    if settled_days:
        d0 = settled_days[0]
        pkey = f"sb_daily:{d0['date']}:{d0['won']}/{d0['settled']}"
        if pkey not in existing_keys:
            cap = format_daily_effectiveness_block(rep)
            img_url = png_to_webp_data_url(render_daily_summary_card(rep))
            new_rows.append({
                "post_key": pkey,
                "kind": "daily",
                "title": f"Cierre {d0['date']}: {d0['won']}/{d0['settled']} ({d0['accuracy_pct']}%)",
                "body_html": cap,
                "image_data": img_url,
            })
            push_headline = push_headline or (f"Cierre del Día: {d0['won']} de {d0['settled']} ({d0['accuracy_pct']}%)", f"Balance: {rep.get('total_profit_u', 0):+.2f}u")

    if new_rows:
        _sb_request(
            supabase_url,
            service_key,
            "channel_posts?on_conflict=post_key",
            method="POST",
            payload=new_rows,
            prefer="resolution=ignore-duplicates,return=minimal",
        )
        # Keep newest 45 channel posts to keep free-tier DB footprint minimal
        all_ids = _sb_request(supabase_url, service_key, "channel_posts?select=id&order=id.desc", method="GET") or []
        if len(all_ids) > 45:
            cutoff = all_ids[44]["id"]
            _sb_request(supabase_url, service_key, f"channel_posts?id=lt.{cutoff}", method="DELETE", prefer="return=minimal")

    push_sent = 0
    if new_rows and push_headline and vapid_private_key:
        push_sent = send_web_push_broadcast(supabase_url, service_key, vapid_private_key, push_headline[0], push_headline[1])

    return len(new_rows), push_sent
