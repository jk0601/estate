#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
관심 단지들의 '34평 이하 매매·전세' 매물 일별 동향 수집기 (COMPLEXES 목록).

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
# 추적할 단지들. 단지번호는 m.land.naver.com 에서 단지 검색 시 주소의 숫자.
COMPLEXES = [
    {"no": "186117", "name": "힐스테이트 메디알레"},
    {"no": "119275", "name": "녹번역 e편한세상 캐슬"},
]
MAX_PYEONG = 34.9          # 34평 이하
WANT_TRADE = {"매매", "전세"}
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


def fetch_articles(complex_no: str) -> list[dict]:
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
        page.goto(f"https://new.land.naver.com/complexes/{complex_no}?tradeType=A1",
                  wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)
        token = auth.get("t", "")
        if not first.get("url") or not token:
            br.close()
            raise RuntimeError("네이버 토큰/URL 확보 실패 (구조 변경 또는 차단 가능)")
        # SPA가 쓰던 realEstateType 유지. tradeType은 A1(매매)/B1(전세) 각각 요청.
        # sameAddressGroup=true: 같은 호실을 여러 중개사가 올린 중복을 묶음(앱과 동일)
        m = re.search(r"realEstateType=([^&]*)", first["url"])
        ret = m.group(1) if m else "APT%3AABYG%3AJGC%3APRE"

        def build(tt):
            return (f"https://new.land.naver.com/api/articles/complex/{complex_no}"
                    f"?realEstateType={ret}&tradeType={tt}&order=prc"
                    f"&complexNo={complex_no}&sameAddressGroup=true")

        arts = []
        for tt in ("A1", "B1"):   # 매매, 전세
            res = page.evaluate(
                """async ({base, token}) => {
                    const out=[];
                    for(let pg=1; pg<=40; pg++){
                        const r = await fetch(base+'&page='+pg, {headers:{authorization:token}});
                        if(!r.ok){ out.push({__err:r.status}); break; }
                        const d = await r.json();
                        out.push(d);
                        if(!d.isMoreData) break;
                    }
                    return out;
                }""", {"base": build(tt), "token": token})
            for d in res:
                if d.get("__err"):
                    br.close()
                    raise RuntimeError(f"매물 조회 실패 HTTP {d['__err']} (tradeType={tt})")
                arts += (d.get("articleList") or [])
        br.close()
    return arts


def to_listing(a: dict) -> dict | None:
    a1 = a.get("area1")
    pyeong = round(a1 / 3.3058, 1) if a1 else None
    trade = a.get("tradeTypeName")
    if trade not in WANT_TRADE or pyeong is None or pyeong > MAX_PYEONG:
        return None
    price = parse_price(a.get("dealOrWarrantPrc"))
    return {
        "trade": trade,                       # 매매 / 전세
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


def load_bunyang_types(complex_no: str) -> list[tuple[float, int]]:
    """메인 프로젝트 docs/data.json에서 이 단지의 평형별 분양가[(공급면적, 분양가만원)]."""
    p = OUT.parent / "data.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    for c in d.get("complexes", []):
        if str(c.get("naver_complex_no")) == complex_no:
            out = []
            for t in c.get("price_by_type") or []:
                try:
                    out.append((float(t["area"]), int(t["price"])))
                except (TypeError, ValueError, KeyError):
                    pass
            return out
    return []


def nearest_bunyang(area_supply, types) -> int | None:
    """공급면적이 가장 가까운 주택형의 분양가(만원)."""
    if not area_supply or not types:
        return None
    return min(types, key=lambda t: abs(t[0] - area_supply))[1]


def stats(listings: list[dict]) -> dict:
    prices = [x["price"] for x in listings if x["price"]]
    return {
        "count": len(listings),
        "min": min(prices) if prices else None,
        "avg": round(sum(prices) / len(prices)) if prices else None,
        "max": max(prices) if prices else None,
    }


def collect_one(complex_no: str, name: str, today: str) -> dict:
    """단지 1곳 수집 -> 오늘치 스냅샷 dict."""
    arts = fetch_articles(complex_no)
    listings = [x for x in (to_listing(a) for a in arts) if x]
    btypes = load_bunyang_types(complex_no)
    for x in listings:
        x["bunyang"] = nearest_bunyang(x.get("area_supply"), btypes)
    listings.sort(key=lambda x: (x["trade"], x["price"] or 9_9999_9999, x["dong"] or ""))
    jeonse = [x for x in listings if x["trade"] == "전세"]
    n_sale = sum(1 for x in listings if x["trade"] == "매매")
    js = stats(jeonse)
    lo = f"{js['min']//10000}억{js['min']%10000 or ''}" if js["min"] else "-"
    prem = " · 분양가매칭O" if btypes else ""
    print(f"  [{name}] 전세 {len(jeonse)} (최저 {lo}) / 매매 {n_sale}{prem}")
    return {"listings": listings, "stats": js}


def load_data() -> dict:
    """기존 watch_data.json 로드 + 구(단일단지) 구조 자동 마이그레이션."""
    data = {"filter": f"{int(MAX_PYEONG)}평 이하 (매매·전세)", "complexes": {}}
    if OUT.exists():
        old = json.loads(OUT.read_text(encoding="utf-8"))
        if "complexes" in old:
            data = old
        elif "history" in old:   # 구 단일단지 포맷 -> 이전
            no = old.get("complex_no")
            data["complexes"] = {no: {"name": old.get("complex"),
                                      "complex_no": no, "history": old["history"]}}
    data.setdefault("complexes", {})
    return data


def main() -> int:
    print(f"[수집] {int(MAX_PYEONG)}평 이하 (매매·전세) · 단지 {len(COMPLEXES)}곳 …")
    today = datetime.now(KST).strftime("%Y-%m-%d")
    data = load_data()
    data["filter"] = f"{int(MAX_PYEONG)}평 이하 (매매·전세)"
    data["updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    for cx in COMPLEXES:
        no, name = cx["no"], cx["name"]
        snap = collect_one(no, name, today)
        entry = data["complexes"].setdefault(no, {"name": name, "complex_no": no, "history": {}})
        entry["name"] = name
        entry.setdefault("history", {})[today] = snap

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[완료] {today} → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
