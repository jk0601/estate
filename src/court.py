"""대법원 법원경매정보(courtauction.go.kr) 서울 아파트 경매물건 수집 (8억 레이더 ②).

사이트가 화면에서 쓰는 검색 API를 그대로 호출한다(로그인·키 불필요).
  POST https://www.courtauction.go.kr/pgj/pgjsearch/searchControllerMain.on

⚠️ 공식 오픈 API가 아니라 **사이트 내부 API**다. 법원이 화면을 개편하면 멈출 수 있다.
   그때는 이 파일의 SEARCH_INFO 기본값을 다시 떠서(브라우저 개발자도구 Network) 맞추면 된다.
   조회는 하루 1회 수준(약 10회 요청)이라 부담이 거의 없다.

관측된 제약
  - pageSize 는 40 이 상한. 그 이상이면 응답이 비어서 온다 → 40씩 페이지 순회.
  - cortOfcCd(관할법원)를 비우면 400. 서울 5개 법원을 각각 돌아야 전 서울이 커버된다.
"""

from __future__ import annotations

import json
import re
import time

import requests

BASE = "https://www.courtauction.go.kr/pgj"
SEARCH_URL = f"{BASE}/pgjsearch/searchControllerMain.on"
ENTRY = f"{BASE}/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml"

# 서울 소재 부동산을 관할하는 5개 지방법원
SEOUL_COURTS = {
    "B000210": "서울중앙지방법원",
    "B000211": "서울동부지방법원",
    "B000215": "서울서부지방법원",
    "B000212": "서울남부지방법원",
    "B000213": "서울북부지방법원",
}

# 용도 코드: 건물(20000) > 주거용건물(20100) > 아파트(20104)
USG_APT = ("20000", "20100", "20104")

PAGE_SIZE = 40          # 사이트 상한
_AREA_RE = re.compile(r"([\d,]+\.?\d*)\s*㎡")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json",
        "Origin": "https://www.courtauction.go.kr",
        "Referer": ENTRY,
        "SC-Userid": "SYSTEM",
    })
    s.get(ENTRY, timeout=20)      # 세션 쿠키 확보
    return s


def _search_info(court: str, bid_from: str, bid_to: str, sido: str = "11") -> dict:
    """화면이 보내는 검색조건 원형. 값을 바꿀 일이 있으면 여기만 손대면 된다."""
    return {
        "rletDspslSpcCondCd": "", "bidDvsCd": "000331", "mvprpRletDvsCd": "00031R",
        "cortAuctnSrchCondCd": "0004601",
        "rprsAdongSdCd": sido, "rprsAdongSggCd": "", "rprsAdongEmdCd": "",
        "rdnmSdCd": "", "rdnmSggCd": "", "rdnmNo": "",
        "mvprpDspslPlcAdongSdCd": "", "mvprpDspslPlcAdongSggCd": "",
        "mvprpDspslPlcAdongEmdCd": "", "rdDspslPlcAdongSdCd": "",
        "rdDspslPlcAdongSggCd": "", "rdDspslPlcAdongEmdCd": "",
        "cortOfcCd": court, "jdbnCd": "", "execrOfcDvsCd": "",
        "lclDspslGdsLstUsgCd": USG_APT[0], "mclDspslGdsLstUsgCd": USG_APT[1],
        "sclDspslGdsLstUsgCd": USG_APT[2],
        "cortAuctnMbrsId": "", "aeeEvlAmtMin": "", "aeeEvlAmtMax": "",
        "lwsDspslPrcRateMin": "", "lwsDspslPrcRateMax": "",
        "flbdNcntMin": "", "flbdNcntMax": "",
        "objctArDtsMin": "", "objctArDtsMax": "",
        "mvprpArtclKndCd": "", "mvprpArtclNm": "", "mvprpAtchmPlcTypCd": "",
        "notifyLoc": "off", "lafjOrderBy": "", "pgmId": "PGJ151F01",
        "csNo": "", "cortStDvs": "1", "statNum": 1,
        "bidBgngYmd": bid_from, "bidEndYmd": bid_to,
        "dspslDxdyYmd": "", "fstDspslHm": "", "scndDspslHm": "",
        "thrdDspslHm": "", "fothDspslHm": "", "dspslPlcNm": "",
        "lwsDspslPrcMin": "", "lwsDspslPrcMax": "",
        "grbxTypCd": "", "gdsVendNm": "", "fuelKndCd": "",
        "carMdyrMax": "", "carMdyrMin": "", "carMdlNm": "", "sideDvsCd": "",
    }


def _post(session: requests.Session, court: str, page: int,
          bid_from: str, bid_to: str) -> dict:
    body = {
        "dma_pageInfo": {"pageNo": page, "pageSize": PAGE_SIZE, "bfPageNo": "",
                         "startRowNo": "", "totalCnt": "", "totalYn": "Y",
                         "groupTotalCount": ""},
        "dma_srchGdsDtlSrchInfo": _search_info(court, bid_from, bid_to),
    }
    r = session.post(SEARCH_URL,
                     data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                     timeout=30)
    r.raise_for_status()
    d = r.json()
    if not d.get("data"):
        raise RuntimeError(f"법원경매 응답 이상: {d.get('message') or d}")
    return d["data"]


def _won_to_man(v) -> int | None:
    try:
        return int(v) // 10000
    except (TypeError, ValueError):
        return None


def _area(row: dict) -> float | None:
    """'철근콘크리트구조 84.97㎡' / convAddr 에서 전용면적(㎡)을 뽑는다."""
    for key in ("areaList", "pjbBuldList", "convAddr"):
        m = _AREA_RE.search(row.get(key) or "")
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def _ymd(v: str | None) -> str:
    v = (v or "").strip()
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if len(v) == 8 else ""


def _complex_name(row: dict) -> str:
    """단지명. buldNm 이 비면 도로명 부가정보 '(도곡동,삼성아파트)'에서 뽑는다."""
    nm = (row.get("buldNm") or "").strip()
    if nm:
        return nm
    m = re.search(r"\(([^)]*)\)", row.get("rdAddrSub") or "")
    if m:
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        if len(parts) >= 2:
            return parts[-1]
    return ""


def normalize(row: dict) -> dict:
    appraisal = _won_to_man(row.get("gamevalAmt"))
    min_bid = _won_to_man(row.get("minmaePrice"))
    return {
        "id": row.get("docid"),
        "court": row.get("jiwonNm") or "",
        "dept": row.get("jpDeptNm") or "",
        "case_no": row.get("srnSaNo") or "",
        "dup_case": re.sub(r"<br/?>", " ", row.get("dupSaNo") or "").strip(),
        "item_no": row.get("maemulSer") or "",
        "address": (row.get("printSt") or "").strip(),
        "gu": row.get("hjguSigu") or "",
        "dong": row.get("hjguDong") or "",
        "complex": _complex_name(row),
        "usage": row.get("dspslUsgNm") or "",
        "area": _area(row),                       # 전용 m2 (등기 표시 기준)
        "appraisal": appraisal,                   # 감정가(만원)
        "min_bid": min_bid,                       # 최저매각가(만원)
        "rate": (int(row["notifyMinmaePriceRate1"])
                 if str(row.get("notifyMinmaePriceRate1") or "").isdigit() else None),
        "fail_count": int(row.get("yuchalCnt") or 0),
        "sale_date": _ymd(row.get("maeGiil")),    # 매각기일
        "place": row.get("maePlace") or "",
        "views": int(row.get("inqCnt") or 0),
        "note": (row.get("mulBigo") or "").strip(),
    }


def collect(bid_from: str, bid_to: str, courts: dict | None = None,
            delay: float = 0.6, log=print) -> list[dict]:
    """서울 5개 법원의 아파트 경매물건 전량. bid_* 는 'YYYYMMDD' 매각기일 범위."""
    courts = courts or SEOUL_COURTS
    session = _session()
    out: list[dict] = []
    for code, name in courts.items():
        page, total = 1, None
        got = 0
        while True:
            data = _post(session, code, page, bid_from, bid_to)
            rows = data.get("dlt_srchResult") or []
            if total is None:
                total = int((data.get("dma_pageInfo") or {}).get("totalCnt") or 0)
            out += [normalize(r) for r in rows]
            got += len(rows)
            if got >= total or not rows:
                break
            page += 1
            time.sleep(delay)
        log(f"  [경매] {name} {got}건")
        time.sleep(delay)

    # 같은 물건이 여러 법원 페이지에 중복될 일은 없지만 방어적으로 dedup
    seen, uniq = set(), []
    for x in out:
        if x["id"] in seen:
            continue
        seen.add(x["id"])
        uniq.append(x)
    uniq.sort(key=lambda x: (x["min_bid"] if x["min_bid"] is not None else 10**9,
                             x["sale_date"]))
    log(f"  [경매] 서울 아파트 총 {len(uniq)}건")
    return uniq


if __name__ == "__main__":
    from datetime import datetime, timedelta, timezone
    kst = timezone(timedelta(hours=9))
    t = datetime.now(kst)
    rows = collect(t.strftime("%Y%m%d"), (t + timedelta(days=180)).strftime("%Y%m%d"))
    for x in rows[:15]:
        print(f"  {x['sale_date']} {x['gu']:5} {(x['complex'] or x['dong'])[:14]:16} "
              f"{(x['area'] or 0):6.1f}㎡ 최저 {(x['min_bid'] or 0)/10000:5.1f}억 "
              f"(감정 {(x['appraisal'] or 0)/10000:5.1f}억, 유찰{x['fail_count']}) {x['case_no']}")
