#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""8억 레이더: "서울에서 8억대에 살 수 있는 10년 내외 아파트" 매일 확인기.

실행:
    python radar.py            # 전부
    python radar.py --no-deals # 실거래 스캔 건너뛰기(경매/공매만, 몇 초)

세 갈래로 같은 질문을 던진다.
  ① 실거래  — 국토부 공식 체결가. "여기는 실제로 8억대에 팔렸다"는 사실.
  ② 경매    — 대법원 법원경매정보. 최저매각가 기준으로 8억대에 잡을 수 있는 물건.
  ③ 공매    — 온비드(캠코) 압류재산. 경매보다 물건은 적지만 부담이 가볍다.

결과: docs/radar_data.json  →  docs/radar.html 에서 봄.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from bunyang import load_key                       # noqa: E402
import rtms                                        # noqa: E402
import court                                       # noqa: E402
import onbid                                       # noqa: E402
import naver                                       # noqa: E402

# ---- 설정 -----------------------------------------------------------------
SCAN_MONTHS = 12                    # 실거래 몇 개월치를 볼지
BUILD_YEAR_MIN, BUILD_YEAR_MAX = 2014, 2021        # 준공 연도 = '10년 내외'
PRICE_MIN, PRICE_MAX = 75_000, 90_000              # 만원 (7.5억 ~ 9.0억)
AREA_MIN = 40.0                     # 전용 40㎡ 미만(원룸형) 제외
AUCTION_MONTHS_AHEAD = 6            # 경매 매각기일을 몇 개월 앞까지 볼지
# ---------------------------------------------------------------------------

KST = timezone(timedelta(hours=9))
OUT = ROOT / "docs" / "radar_data.json"
NAVER_CACHE = ROOT / "cache" / "naver_no.json"


def recent_months(n: int) -> list[str]:
    """직전 n개월(이번 달 포함)의 'YYYYMM' 목록."""
    t = datetime.now(KST)
    y, m = t.year, t.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def load_prev() -> dict:
    if not OUT.exists():
        return {}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def carry_first_seen(items: list[dict], prev_items: list[dict], today: str) -> list[dict]:
    """직전 실행에 없던 물건에 '신규' 표시.

    '오늘 처음 본 날짜'가 아니라 **직전 결과에 그 id가 있었는지**로 판정한다.
    그래야 같은 날 두 번 돌려도 전부 신규로 뒤집히지 않는다.
    비교 대상이 아예 없는 첫 실행에서는 아무것도 신규로 표시하지 않는다.
    """
    seen = {x.get("id"): x.get("first_seen") for x in prev_items if x.get("id")}
    for x in items:
        x["first_seen"] = seen.get(x["id"]) or today
        x["is_new"] = bool(seen) and x["id"] not in seen
    return items


# ---- ① 실거래 --------------------------------------------------------------

def load_naver_cache() -> dict:
    if NAVER_CACHE.exists():
        try:
            return json.loads(NAVER_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def attach_naver(complexes: list[dict], log=print) -> None:
    """단지별 네이버 매물 딥링크. 한 번 찾은 단지번호는 cache/ 에 재사용."""
    cache = load_naver_cache()
    session = naver._session()
    resolved = 0
    for c in complexes:
        key = f"{c['gu']}|{c['dong']}|{c['name']}"
        if key not in cache:
            row = {"name": f"{c['dong']} {c['name']}", "gu": c["gu"], "dong": c["dong"]}
            try:
                cache[key] = naver.resolve_complex_no(row, session)
            except Exception:            # noqa: BLE001  링크는 없어도 되는 부가정보
                cache[key] = None
            resolved += 1
        no = cache.get(key)
        c["naver_complex_no"] = no
        c["naver_url"] = naver.mobile_url(no, f"{c['dong']} {c['name']}")
    NAVER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    NAVER_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    hit = sum(1 for c in complexes if c["naver_complex_no"])
    log(f"  [실거래] 네이버 딥링크 {hit}/{len(complexes)} (신규 조회 {resolved})")


def run_deals(prev: dict, log=print) -> dict:
    months = recent_months(SCAN_MONTHS)
    key = load_key()
    if not key:
        return {"available": False, "note": "secret_key.txt 없음", "complexes": [],
                "months": months, **_keep_prev(prev, "deals", "complexes")}
    log(f"[① 실거래] 서울 25개구 × {months[0]}~{months[-1]}")
    try:
        deals = rtms.scan(months, key, log=log)
    except rtms.NotSubscribed as e:
        log(f"  {e}")
        return {"available": False, "note": str(e), "complexes": [],
                "months": months, **_keep_prev(prev, "deals", "complexes")}
    except Exception as e:                                   # noqa: BLE001
        log(f"  [실거래] 실패: {e}")
        return {"available": False, "note": f"수집 실패: {e}", "complexes": [],
                "months": months, **_keep_prev(prev, "deals", "complexes")}

    complexes = rtms.aggregate(deals, BUILD_YEAR_MIN, BUILD_YEAR_MAX,
                               PRICE_MIN, PRICE_MAX, AREA_MIN)
    log(f"  [실거래] 조건 통과 단지 {len(complexes)}곳")
    attach_naver(complexes, log=log)
    return {"available": True, "note": "", "months": months,
            "scanned_deals": len(deals), "complexes": complexes}


def _keep_prev(prev: dict, section: str, key: str) -> dict:
    """이번에 못 받았으면 지난번 결과라도 화면에 남긴다(빈 화면 방지)."""
    old = (prev.get(section) or {}).get(key)
    if old:
        return {"stale": True, "stale_from": prev.get("generated_at", ""), key: old}
    return {}


# ---- ② 경매 / ③ 공매 --------------------------------------------------------

def run_auctions(prev: dict, today: str, log=print) -> dict:
    t = datetime.now(KST)
    frm = t.strftime("%Y%m%d")
    to = (t + timedelta(days=31 * AUCTION_MONTHS_AHEAD)).strftime("%Y%m%d")
    log(f"[② 경매] 법원경매정보 · 매각기일 {frm}~{to}")
    try:
        items = court.collect(frm, to, log=log)
    except Exception as e:                                   # noqa: BLE001
        log(f"  [경매] 실패: {e}")
        return {"available": False, "note": f"수집 실패: {e}", "items": [],
                **_keep_prev(prev, "auctions", "items")}
    items = carry_first_seen(items, (prev.get("auctions") or {}).get("items", []), today)
    log(f"  [경매] 오늘 새로 보이는 물건 {sum(1 for x in items if x['is_new'])}건")
    return {"available": True, "note": "", "range": [frm, to], "items": items}


def run_onbid(prev: dict, today: str, log=print) -> dict:
    log("[③ 공매] 온비드(캠코) 압류재산")
    key = load_key()
    if not key:
        return {"available": False, "note": "secret_key.txt 없음", "items": [],
                **_keep_prev(prev, "onbid", "items")}
    try:
        items = onbid.collect(key, log=log)
    except onbid.OnbidUnavailable as e:
        log(f"  {e}")
        return {"available": False, "note": str(e), "items": [],
                **_keep_prev(prev, "onbid", "items")}
    except Exception as e:                                   # noqa: BLE001
        log(f"  [공매] 실패: {e}")
        return {"available": False, "note": f"수집 실패: {e}", "items": [],
                **_keep_prev(prev, "onbid", "items")}
    items = carry_first_seen(items, (prev.get("onbid") or {}).get("items", []), today)
    return {"available": True, "note": "", "items": items}


# ---- 실행 -------------------------------------------------------------------

def main(argv: list[str]) -> int:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    prev = load_prev()

    payload = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "config": {
            "build_year_min": BUILD_YEAR_MIN, "build_year_max": BUILD_YEAR_MAX,
            "price_min": PRICE_MIN, "price_max": PRICE_MAX,
            "area_min": AREA_MIN, "scan_months": SCAN_MONTHS,
        },
        "deals": ({"available": False, "note": "--no-deals 로 건너뜀",
                   "complexes": [], **_keep_prev(prev, "deals", "complexes")}
                  if "--no-deals" in argv else run_deals(prev)),
        "auctions": run_auctions(prev, today),
        "onbid": run_onbid(prev, today),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    d, a, o = payload["deals"], payload["auctions"], payload["onbid"]
    print("\n[완료]",
          f"실거래 단지 {len(d.get('complexes') or [])}곳",
          f"· 경매 {len(a.get('items') or [])}건",
          f"· 공매 {len(o.get('items') or [])}건")
    for name, sec in (("실거래", d), ("경매", a), ("공매", o)):
        if not sec.get("available") and sec.get("note"):
            print(f"  ⚠ {name}: {sec['note']}")
    print(f"[저장] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
