import json
import math
import os
from datetime import datetime, date, timedelta
from calendar import monthrange
from urllib.parse import urlencode
import requests

import db
from config import DEFAULT_TARASSUL_BASE_URL


def _build_url() -> str:
    base = (os.environ.get("TARASSUL_BASE_URL") or "").strip() or DEFAULT_TARASSUL_BASE_URL
    fid = (os.environ.get("TARASSUL_FID") or "3").strip()
    user = (os.environ.get("TARASSUL_USERNAME") or "").strip()
    psw = (os.environ.get("TARASSUL_PASSWORD") or "").strip()
    lang = (os.environ.get("TARASSUL_LANG") or "1").strip()
    qs = urlencode({"F_ID": fid, "userName": user, "userPswd": psw, "LangCo": lang})
    return f"{base.rstrip('/')}?{qs}"


def _compute_usage_and_exceed(product: dict) -> tuple[float | None, int | None, str, str]:
    accu = product.get("AccumulateInfo") or {}
    max_mb = product.get("MaxServiceUsage")
    if max_mb is None or max_mb < 0:
        return None, None, "", ""
    month_vol_kb = accu.get("MonthAccuVolume")
    if month_vol_kb is None:
        return None, None, "", ""
    used_bytes = month_vol_kb * 1024
    limit_bytes = max_mb * 1024 * 1024
    usage_percent = min(100.0, (used_bytes / limit_bytes) * 100)

    begin_str = (accu.get("MonthAccuBeginTime") or "")[:8]
    end_str = (accu.get("MonthAccuEndTime") or "")[:8]
    if len(begin_str) < 8 or len(end_str) < 8:
        return usage_percent, None, "", ""

    limit_gb = limit_bytes / (1024 ** 3)
    usage_gb = used_bytes / (1024 ** 3)
    start = date(int(begin_str[:4]), int(begin_str[4:6]), int(begin_str[6:8]))
    end = date(int(end_str[:4]), int(end_str[4:6]), int(end_str[6:8]))
    end = end - timedelta(days=1)  # last day of period
    today = date.today()
    if today < start:
        today = start
    elif today > end:
        today = end
    current_day = today.day
    days_in_month = monthrange(start.year, start.month)[1]
    if usage_gb <= 0 or usage_percent >= 100:
        exceed_day = None
    else:
        exceed_day = min(days_in_month, math.ceil(current_day * limit_gb / usage_gb))
    month_begin = f"{begin_str[:4]}-{begin_str[4:6]}-{begin_str[6:8]}"
    month_end = f"{end_str[:4]}-{end_str[4:6]}-{end_str[6:8]}"
    return usage_percent, exceed_day, month_begin, month_end


def _ntfy_headers() -> dict:
    token = (os.environ.get("NTFY_TOKEN") or "").strip()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _send_ntfy(message: str) -> None:
    url = (os.environ.get("NTFY_URL") or "").strip()
    if not url:
        return
    try:
        requests.post(url, data=message.encode("utf-8"), headers=_ntfy_headers(), timeout=10)
    except Exception:
        pass


def send_ntfy_test(url: str, token: str = "") -> dict:
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "ntfy URL is empty"}
    headers = {}
    if (token or "").strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    try:
        r = requests.post(
            url,
            data="Netmon test notification".encode("utf-8"),
            headers=headers,
            timeout=10,
        )
        if not r.ok:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return {"ok": True}
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)}


def check_and_notify(
    usage_percent: float,
    exceed_day: int | None,
    month: str,
    limit_gb: float,
    usage_gb: float,
) -> None:
    thresholds = [25, 50, 75, 90, 100]
    sent_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    for t in thresholds:
        if usage_percent < t:
            continue
        if db.notification_already_sent(month, t):
            continue
        db.record_notification_sent(month, t, sent_at)
        if t == 100:
            msg = "Limit reached. Your internet package has hit 100% usage."
        else:
            ex = f" Expected to exceed limit on day {exceed_day}." if exceed_day else ""
            msg = f"Usage at {t}% ({usage_gb:.2f} GB / {limit_gb:.1f} GB).{ex}"
        _send_ntfy(msg)


def run_fetch(is_baseline: bool = False) -> dict:
    url = _build_url()
    base = (os.environ.get("TARASSUL_BASE_URL") or "").strip() or DEFAULT_TARASSUL_BASE_URL
    user = (os.environ.get("TARASSUL_USERNAME") or "").strip()
    if not base:
        return {"ok": False, "error": "Tarassul URL not configured (set TARASSUL_BASE_URL in data/netmon.conf)"}
    if not user:
        return {"ok": False, "error": "Tarassul username not configured (set TARASSUL_USERNAME in data/netmon.conf)"}

    try:
        r = requests.get(
            url,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            },
            timeout=15,
        )
        r.raise_for_status()
        raw = r.text
        data = r.json()
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)}
    except (ValueError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"Invalid response: {e}"}

    if isinstance(data, list):
        products = data
    elif isinstance(data, dict):
        for key in ("data", "result", "products", "items"):
            if isinstance(data.get(key), list):
                products = data[key]
                break
        else:
            return {
                "ok": False,
                "error": "Response is not an array (got object with keys: {})".format(
                    ", ".join(data.keys()) if data else "empty"
                ),
            }
    elif isinstance(data, (int, float)):
        idx = raw.find("[")
        if idx >= 0:
            try:
                products = json.loads(raw[idx:])
                if not isinstance(products, list):
                    products = None
            except (ValueError, json.JSONDecodeError):
                products = None
        else:
            products = None
        if not products:
            return {
                "ok": False,
                "error": "API returned a number ({}). Often means login failed or session invalid — check username and password in data/netmon.conf.".format(data),
            }
    else:
        return {"ok": False, "error": "Response is not an array (got {})".format(type(data).__name__)}

    filtered = [
        p for p in products
        if p.get("ProductID") != "1024" and p.get("ProductName") != "Default1M"
    ]
    if not filtered:
        return {"ok": False, "error": "No product data after filtering"}

    fetched_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    for product in filtered:
        usage_percent, exceed_day, month_begin, month_end = _compute_usage_and_exceed(product)
        if usage_percent is None:
            continue
        accu = product.get("AccumulateInfo") or {}
        month_vol_kb = accu.get("MonthAccuVolume") or 0
        max_mb = product.get("MaxServiceUsage") or 0
        limit_gb = (max_mb * 1024 * 1024) / (1024 ** 3)
        usage_gb = (month_vol_kb * 1024) / (1024 ** 3)
        month_key = month_begin[:7] if month_begin else ""

        if is_baseline:
            db.insert_baseline_fetch(
                fetched_at=fetched_at,
                product_id=str(product.get("ProductID", "")),
                product_name=str(product.get("ProductName", "")),
                month_accu_volume_kb=int(month_vol_kb),
                max_service_usage_mb=int(max_mb),
                usage_percent=round(usage_percent, 2),
                exceed_day=exceed_day,
                month_begin=month_begin,
                month_end=month_end,
                raw_json=json.dumps(product),
            )
        else:
            db.insert_fetch(
                fetched_at=fetched_at,
                product_id=str(product.get("ProductID", "")),
                product_name=str(product.get("ProductName", "")),
                month_accu_volume_kb=int(month_vol_kb),
                max_service_usage_mb=int(max_mb),
                usage_percent=round(usage_percent, 2),
                exceed_day=exceed_day,
                month_begin=month_begin,
                month_end=month_end,
                raw_json=json.dumps(product),
                is_midnight=False,
            )
            check_and_notify(usage_percent, exceed_day, month_key, limit_gb, usage_gb)

    return {"ok": True, "message": "Fetched and stored successfully"}
