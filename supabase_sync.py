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
