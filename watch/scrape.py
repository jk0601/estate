#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
힐스테이트 메디알레(186117) '34평 이하 전세' 매물 일별 동향 수집기.

방식: Playwright로 네이버 부동산(new.land) 단지 페이지를 실제 브라우저로 열어
      SPA가 쓰는 인증 토큰을 확보한 뒤, '페이지 내부 fetch'로 전 페이지를 수집.
      (직접 요청은 429로 막히지만, 페이지 컨텍스트 fetch는 통과)

⚠️ 네이버 이용약관상 자동수집은 회색지대입니다. 개인이 관심단지 1곳을
   하루 1회 조회하는 저빈도 용도로만 사용하세요.

출력: docs/watch_data.json 에 날짜별 스냅샷 누적.
실행: python watch/scrape.py   (매일 1회, Windows 작업 스케줄러 권장)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

# ---- 설정 ----
COMPLEX_NO = "186117"
COMPLEX_NAME = "힐스테이트 메디알레"
MAX_PYEONG = 34.9          # 34평 이하
TRADE = "B1"               # B1=전세
OUT = Path(__file__).resolve().parent.parent / "docs" / "watch_data.json"
KST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def parse_price(txt: str | None) -> int | None:
    """'6억', '6억 5,000', '9,500' -> 만원(int)"""
    if not txt:
        return None
    t = txt.replace(" ", "")
    m = re.match(r"(?:(\d+)억)?(?:(\d[\d,]*))?$", t)
    if not m:
        return None
    return (int(m.group(1)) if m.group(1) else 0) * 10000 + \
           (int(m.group(2).replace(",", "")) if m.group(2) else 0)


def fetch_articles() -> list[dict]:
    auth, first = {}, {}

    def on_request(req):
        if "api/articles/complex" in req.url:
            h = {k.lower(): v for k, v in req.headers.items()}
            if h.get("authorization"):
                auth["t"] = h["authorization"]
                first["url"] = req.url

    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        ctx = br.new_context(user_agent=UA, locale="ko-KR",
                             viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("request", on_request)
        page.goto(f"https://new.land.naver.com/complexes/{COMPLEX_NO}?tradeType={TRADE}",
                  wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)
        base = re.sub(r"[?&]page=\d+", "", first.get("url", ""))
        token = auth.get("t", "")
        if not base or not token:
            br.close()
            raise RuntimeError("네이버 토큰/URL 확보 실패 (구조 변경 또는 차단 가능)")
        result = page.evaluate(
            """async ({base, token}) => {
                const out=[];
                for(let pg=1; pg<=10; pg++){
                    const sep = base.includes('?') ? '&' : '?';
                    const r = await fetch(base+sep+'page='+pg, {headers:{authorization:token}});
                    if(!r.ok){ out.push({__err:r.status}); break; }
                    const d = await r.json();
                    out.push(d);
                    if(!d.isMoreData) break;
                }
                return out;
            }""", {"base": base, "token": token})
        br.close()

    arts = []
    for d in result:
        if d.get("__err"):
            raise RuntimeError(f"매물 조회 실패 HTTP {d['__err']}")
        arts += (d.get("articleList") or [])
    return arts


def to_listing(a: dict) -> dict | None:
    a1 = a.get("area1")
    pyeong = round(a1 / 3.3058, 1) if a1 else None
    if a.get("tradeTypeName") != "전세" or pyeong is None or pyeong > MAX_PYEONG:
        return None
    price = parse_price(a.get("dealOrWarrantPrc"))
    return {
        "articleNo": a.get("articleNo"),
        "dong": a.get("buildingName"),
        "pyeong": pyeong,
        "area_supply": a1,
        "area_exclusive": a.get("area2"),
        "price": price,                       # 만원
        "price_text": a.get("dealOrWarrantPrc"),
        "floor": a.get("floorInfo"),
        "direction": a.get("direction"),
        "realtor": a.get("realtorName") or a.get("cpName"),
        "feature": a.get("articleFeatureDesc"),
        "confirm": a.get("articleConfirmYmd"),
        "naver_change": a.get("priceChangeState"),   # SAME/INCREASE/DECREASE
    }


def stats(listings: list[dict]) -> dict:
    prices = [x["price"] for x in listings if x["price"]]
    return {
        "count": len(listings),
        "min": min(prices) if prices else None,
        "avg": round(sum(prices) / len(prices)) if prices else None,
        "max": max(prices) if prices else None,
    }


def main() -> int:
    print(f"[수집] {COMPLEX_NAME} {MAX_PYEONG}평 이하 전세 …")
    arts = fetch_articles()
    listings = [x for x in (to_listing(a) for a in arts) if x]
    listings.sort(key=lambda x: (x["price"] or 9_9999_9999, x["dong"] or ""))
    today = datetime.now(KST).strftime("%Y-%m-%d")

    data = {"complex": COMPLEX_NAME, "complex_no": COMPLEX_NO,
            "filter": f"{int(MAX_PYEONG)}평 이하 전세", "history": {}}
    if OUT.exists():
        data = json.loads(OUT.read_text(encoding="utf-8"))
        data.setdefault("history", {})

    data["updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    data["history"][today] = {"listings": listings, "stats": stats(listings)}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    s = data["history"][today]["stats"]
    lo = f"{s['min']//10000}억{s['min']%10000 or ''}" if s["min"] else "-"
    print(f"[완료] {today}: {s['count']}건, 최저 {lo}  →  {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
