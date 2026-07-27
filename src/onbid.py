"""온비드(캠코) 부동산 공매물건 → 서울 아파트만 추려내기 (8억 레이더 ③).

서비스: 한국자산관리공사_차세대 온비드 부동산 물건목록 조회서비스
        data.go.kr 15157207
        https://apis.data.go.kr/B010003/OnbidRlstListSrvc2/getRlstCltrList2

경매(법원) ≠ 공매(캠코). 공매는 세금 체납으로 압류된 재산 등을 캠코가 온비드에서 파는 것으로,
물건 수는 경매보다 훨씬 적지만 명도·권리분석 부담이 가벼운 편이다. 둘 다 봐야 놓치지 않는다.

⚠️ secret_key.txt 의 키로 이 서비스에 **따로 '활용신청'** 이 필요하다(즉시 승인).
   (구 API `openapi.onbid.co.kr/.../getKamcoPbctCltrList`(15000837)는 폐지됐다.)

필수 파라미터는 prptDivCd(재산유형)와 pvctTrgtYn(수의계약가능여부)이다.
pvctTrgtYn 은 Y/N 둘 중 하나만 받으므로 **두 번 호출해 합친다**(안 그러면 절반이 빠진다).
"""

from __future__ import annotations

import re
import time
import urllib.parse

import requests

URL = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2/getRlstCltrList2"

# 재산유형: 아파트가 나올 수 있는 유형 전부 (0004 불용품=동산 제외)
PRPT_DIV = "0007,0010,0005,0002,0003,0006,0008,0011,0013"
DSPS_SALE = "0001"          # 처분방식: 매각 (임대 제외)
SIDO = "서울특별시"
PAGE_ROWS = 300
MAX_PAGES = 40


class OnbidUnavailable(RuntimeError):
    """활용신청 전(403)이거나 온비드 API에 닿지 않는 상태."""


def _num(v) -> int | None:
    """'1,234,000원' / 1234000 -> 1234000. '비공개' 등은 None."""
    if v is None:
        return None
    digits = re.sub(r"[^\d]", "", str(v))
    return int(digits) if digits else None


def _man(v) -> int | None:
    """원 -> 만원."""
    n = _num(v)
    return n // 10000 if n is not None else None


def _ymd(v) -> str:
    """'202608031000' -> '2026-08-03'"""
    s = re.sub(r"[^\d]", "", str(v or ""))
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else ""


def _fetch_page(session: requests.Session, key: str, pvct: str, page: int) -> dict:
    # secret_key.txt 에는 URL 인코딩된 키(%2B, %3D 포함)가 들어있다.
    # params= 로 그대로 넘기면 '%'가 다시 인코딩돼 401 → 디코딩해서 넘긴다.
    params = {
        "serviceKey": urllib.parse.unquote(key), "resultType": "json",
        "pageNo": page, "numOfRows": PAGE_ROWS,
        "prptDivCd": PRPT_DIV, "pvctTrgtYn": pvct,
        "dspsMthodCd": DSPS_SALE, "lctnSdnm": SIDO,
    }
    try:
        r = session.get(URL, params=params, timeout=30)
    except requests.RequestException as e:
        raise OnbidUnavailable(f"온비드 접속 실패: {type(e).__name__}") from e
    if r.status_code == 403:
        raise OnbidUnavailable(
            "온비드 API 403 — data.go.kr 에서 '한국자산관리공사_차세대 온비드 부동산"
            " 물건목록 조회서비스(15157207)' 활용신청이 필요합니다.")
    if r.status_code != 200:
        raise OnbidUnavailable(f"온비드 HTTP {r.status_code}")
    try:
        d = r.json()
    except ValueError:
        raise OnbidUnavailable(f"온비드 응답이 JSON이 아님: {r.text[:200]}") from None

    head = (d.get("header") or d.get("response", {}).get("header") or {})
    code = str(head.get("resultCode") or "")
    if code and code not in ("00", "000", "0"):
        raise OnbidUnavailable(f"온비드 오류 {code} {head.get('resultMsg') or ''}")
    return d.get("body") or d.get("response", {}).get("body") or {}


def _items(body: dict) -> list[dict]:
    """items.item 이 단건이면 dict, 여러 건이면 list 로 오는 경우를 모두 흡수."""
    items = body.get("items")
    if isinstance(items, dict):
        items = items.get("item")
    if items is None:
        return []
    return items if isinstance(items, list) else [items]


def fetch_all(key: str, delay: float = 0.25, log=print) -> list[dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    rows: list[dict] = []
    for pvct in ("N", "Y"):          # 수의계약 불가/가능 둘 다
        for page in range(1, MAX_PAGES + 1):
            body = _fetch_page(session, key, pvct, page)
            got = _items(body)
            rows += got
            total = _num(body.get("totalCount")) or 0
            if len(rows) >= total or not got or len(got) < PAGE_ROWS:
                break
            time.sleep(delay)
    log(f"  [공매] 서울 부동산 매각물건 {len(rows):,}건 수신")
    return rows


def normalize(it: dict) -> dict:
    usage = " > ".join(x for x in (it.get("cltrUsgLclsCtgrNm"),
                                   it.get("cltrUsgMclsCtgrNm"),
                                   it.get("cltrUsgSclsCtgrNm")) if x)
    addr = " ".join(x for x in (it.get("lctnSdnm"), it.get("lctnSggnm"),
                                it.get("lctnEmdNm")) if x)
    notes = []
    if str(it.get("alcYn") or "").upper() == "Y":
        notes.append("지분물건")
    if str(it.get("batcBidYn") or "").upper() == "Y":
        notes.append("일괄입찰")
    if str(it.get("pvctTrgtYn") or "").upper() == "Y":
        notes.append("수의계약 가능")
    if str(it.get("crtnYn") or "").upper() == "Y":
        notes.append("정정내역 있음")

    return {
        "id": f"{it.get('cltrMngNo')}-{it.get('pbctCdtnNo')}",
        "cltr_mng_no": it.get("cltrMngNo"),
        "name": it.get("onbidCltrNm") or "",
        "usage": usage,
        "usage_scls": it.get("cltrUsgSclsCtgrNm") or "",
        "address": addr,
        "gu": it.get("lctnSggnm") or "",
        "dong": it.get("lctnEmdNm") or "",
        "prpt_type": it.get("prptDivNm") or "",       # 압류재산 / 국유재산 …
        "org": it.get("rqstOrgNm") or it.get("orgNm") or "",
        "min_bid": _man(it.get("lowstBidPrcIndctCont")),   # 최저입찰가(만원, 비공개면 None)
        "appraisal": _man(it.get("apslEvlAmt")),           # 감정가(만원)
        "rate": (round(float(it["apslPrcCtrsLowstBidRto"]))
                 if it.get("apslPrcCtrsLowstBidRto") not in (None, "") else None),
        "area": (float(it["bldSqms"]) if it.get("bldSqms") not in (None, "", 0) else None),
        "land_area": (float(it["landSqms"]) if it.get("landSqms") not in (None, "", 0) else None),
        "bid_from": _ymd(it.get("cltrBidBgngDt")),
        "bid_to": _ymd(it.get("cltrBidEndDt")),
        "status": it.get("pbctStatNm") or "",
        "fail_count": _num(it.get("usbdNft")) or 0,
        "note": ", ".join(notes),
    }


def _is_apt(row: dict) -> bool:
    """용도 '소분류'로만 판정. 물건명에 '아파트'가 들어간 근린생활시설(아파트 단지 내
    상가 등)이 섞여 들어오는 걸 막는다."""
    return row["usage_scls"] == "아파트"


def collect(key: str, log=print) -> list[dict]:
    """서울 소재 아파트 공매물건만."""
    rows = [normalize(x) for x in fetch_all(key, log=log)]
    out = [x for x in rows if _is_apt(x)]
    out.sort(key=lambda x: (x["min_bid"] if x["min_bid"] is not None else 10**9,
                            x["bid_to"]))
    log(f"  [공매] 서울 아파트 {len(out)}건")
    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from bunyang import load_key
    for x in collect(load_key())[:20]:
        print(f"  {x['bid_from']}~{x['bid_to']} {x['gu']:6} {x['name'][:34]:36} "
              f"최저 {(x['min_bid'] or 0)/10000:5.1f}억 "
              f"(감정 {(x['appraisal'] or 0)/10000:5.1f}억, {x['prpt_type']}) {x['note']}")
