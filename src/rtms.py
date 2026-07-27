"""국토교통부 아파트 매매 실거래가 → 서울 전역 스캔 (8억 레이더 ①).

서비스: 국토교통부_아파트 매매 실거래가 자료 (data.go.kr 15126469)
        http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev
        (구버전 경로도 자동 폴백)

⚠️ 이 API는 secret_key.txt 의 키로 **따로 '활용신청'** 을 해야 열립니다(즉시 승인).
   신청 전에는 HTTP 403 이 떨어지고, radar.py 가 그 사실을 안내합니다.

하는 일
  1) 서울 25개 자치구 × 최근 N개월의 아파트 매매 체결 건을 전부 받아온다
  2) (자치구, 법정동, 아파트명, 건축년도) 로 묶어 단지별로 집계한다
  3) '건축 N년 이내 + 예산 안에 실제로 팔린 적 있는' 단지만 남긴다

즉 결과는 "서울에서 8억대에 **실제로 거래된** 10년 내외 아파트 단지" 목록이다.
(호가가 아니라 체결가 기준 → 헛물 켤 일이 없다. 현재 호가는 네이버 링크로 확인.)
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from statistics import median

import requests

# 서울 25개 자치구 법정동코드 앞 5자리 (LAWD_CD)
SEOUL_LAWD = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구", "11290": "성북구",
    "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
    "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구",
    "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
    "11740": "강동구",
}

# 같은 데이터에 '기본'과 '상세' 두 서비스가 따로 있고, 활용신청도 따로다.
# 어느 쪽을 신청했든 동작하도록 순서대로 시도하고, 성공한 주소를 이후 재사용한다.
#   기본: 15126469  RTMSDataSvcAptTrade      (필요한 필드 전부 있음 — 이걸 우선)
#   상세: 15126468  RTMSDataSvcAptTradeDev   (등기일자 등 추가 필드)
ENDPOINTS = (
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
)

# 응답 태그명이 신/구 버전에서 다르다 → 둘 다 받는다.
FIELD_ALIASES = {
    "name":       ("aptNm", "아파트"),
    "build_year": ("buildYear", "건축년도"),
    "amount":     ("dealAmount", "거래금액"),
    "year":       ("dealYear", "년"),
    "month":      ("dealMonth", "월"),
    "day":        ("dealDay", "일"),
    "area":       ("excluUseAr", "전용면적"),
    "floor":      ("floor", "층"),
    "dong":       ("umdNm", "법정동"),
    "jibun":      ("jibun", "지번"),
    "canceled":   ("cdealType", "해제여부"),
}


class NotSubscribed(RuntimeError):
    """키는 유효하나 이 API에 '활용신청'이 안 된 상태(403)."""


def _pick(item: ET.Element, key: str) -> str | None:
    for tag in FIELD_ALIASES[key]:
        el = item.find(tag)
        if el is not None and el.text is not None:
            return el.text.strip()
    return None


def _to_int(txt: str | None) -> int | None:
    if not txt:
        return None
    try:
        return int(txt.replace(",", "").strip())
    except ValueError:
        return None


def fetch_month(lawd_cd: str, ym: str, key: str, session: requests.Session,
                endpoint: str | None = None) -> tuple[list[dict], str]:
    """자치구 1곳 × 1개월치 체결 건. 반환: (거래목록, 성공한 endpoint)"""
    last_err: Exception | None = None
    tried = [endpoint] if endpoint else list(ENDPOINTS)
    denied = 0
    for ep in tried:
        url = (f"{ep}?serviceKey={key}&LAWD_CD={lawd_cd}&DEAL_YMD={ym}"
               f"&numOfRows=1000&pageNo=1")
        try:
            r = session.get(url, timeout=30)
        except requests.RequestException as e:
            last_err = e
            continue
        # 403 = 키는 유효하나 '그 서비스'에 활용신청이 안 된 상태.
        # 기본/상세 중 신청한 쪽이 있을 수 있으니 다음 주소를 마저 시도한다.
        if r.status_code == 403:
            denied += 1
            last_err = RuntimeError("HTTP 403")
            continue
        if r.status_code != 200:
            last_err = RuntimeError(f"HTTP {r.status_code}")
            continue
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            last_err = e
            continue
        code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
        if code and code not in ("00", "000"):
            msg = root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or ""
            last_err = RuntimeError(f"{code} {msg}")
            continue

        out = []
        for it in root.iter("item"):
            if (_pick(it, "canceled") or "").upper() == "O":   # 계약 해제 건 제외
                continue
            amount = _to_int(_pick(it, "amount"))               # 만원
            name = _pick(it, "name")
            if not amount or not name:
                continue
            y, m, d = _pick(it, "year"), _pick(it, "month"), _pick(it, "day")
            try:
                area = float(_pick(it, "area") or 0) or None
            except ValueError:
                area = None
            out.append({
                "gu": SEOUL_LAWD.get(lawd_cd, lawd_cd),
                "lawd_cd": lawd_cd,
                "dong": _pick(it, "dong") or "",
                "name": name,
                "build_year": _to_int(_pick(it, "build_year")),
                "amount": amount,                                # 만원
                "date": f"{y}-{int(m):02d}-{int(d):02d}" if y and m and d else "",
                "area": area,                                    # 전용 m2
                "floor": _to_int(_pick(it, "floor")),
                "jibun": _pick(it, "jibun") or "",
            })
        return out, ep
    if denied == len(tried):
        raise NotSubscribed(
            "실거래가 API 403 — data.go.kr 에서 '국토교통부_아파트 매매 실거래가 자료'"
            "(15126469) 활용신청이 필요합니다. 신청 후 반영까지 시간이 걸릴 수 있습니다.")
    raise RuntimeError(f"실거래가 조회 실패: {last_err}")


def scan(months: list[str], key: str, delay: float = 0.12, log=print) -> list[dict]:
    """서울 25개 구 × months 전체 체결 건."""
    session = requests.Session()
    deals: list[dict] = []
    endpoint = None
    for i, (lawd, gu) in enumerate(SEOUL_LAWD.items(), 1):
        got = 0
        for ym in months:
            rows, endpoint = fetch_month(lawd, ym, key, session, endpoint)
            deals += rows
            got += len(rows)
            time.sleep(delay)
        log(f"  [실거래] ({i:2d}/25) {gu} {got:,}건")
    log(f"  [실거래] 총 {len(deals):,}건 수집")
    return deals


def aggregate(deals: list[dict], build_min: int, build_max: int,
              price_min: int, price_max: int, area_min: float = 0.0) -> list[dict]:
    """단지별 집계 후 '건축년도 + 예산' 조건에 걸리는 단지만 남긴다.

    price_min/price_max 는 만원 단위(75000 = 7.5억).
    한 건이라도 예산 안에서 팔린 단지를 남기고, 그 단지의 전체 거래도 함께 담는다.
    """
    groups: dict[tuple, dict] = {}
    for d in deals:
        by = d["build_year"]
        if by is None or not (build_min <= by <= build_max):
            continue
        if area_min and (d["area"] or 0) < area_min:
            continue
        k = (d["lawd_cd"], d["dong"], d["name"], by)
        g = groups.setdefault(k, {
            "gu": d["gu"], "dong": d["dong"], "name": d["name"],
            "build_year": by, "jibun": d["jibun"], "deals": [],
        })
        g["deals"].append({"date": d["date"], "amount": d["amount"],
                           "area": d["area"], "floor": d["floor"]})

    out = []
    for g in groups.values():
        g["deals"].sort(key=lambda x: x["date"], reverse=True)
        hits = [x for x in g["deals"] if price_min <= x["amount"] <= price_max]
        if not hits:
            continue
        amts = [x["amount"] for x in g["deals"]]
        areas = [x["area"] for x in g["deals"] if x["area"]]
        g.update({
            "deal_count": len(g["deals"]),
            "hit_count": len(hits),
            "price_min": min(amts),
            "price_med": int(median(amts)),
            "price_max": max(amts),
            "last_date": g["deals"][0]["date"],
            "last_price": g["deals"][0]["amount"],
            "area_min": round(min(areas), 1) if areas else None,
            "area_max": round(max(areas), 1) if areas else None,
            # 예산 안에서 팔린 가장 싼 건 (= '이 값이면 들어갈 수 있다'는 기준선)
            "hit_min": min(x["amount"] for x in hits),
            "hit_last": max(hits, key=lambda x: x["date"])["date"],
        })
        out.append(g)

    out.sort(key=lambda g: (g["hit_min"], g["gu"]))
    return out
