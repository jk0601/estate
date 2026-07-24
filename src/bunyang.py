"""
2단계: 청약홈 분양정보 조회 API로 분양 단지의 공고정보 + 평형별 분양가 보강.

서비스: 한국부동산원_청약홈 분양정보 조회 서비스 (data.go.kr 15098547 / odcloud)
사용 오퍼레이션(실측 확인):
  1) getAPTLttotPblancDetail : APT 분양 '공고' 메타데이터
       주요 필드: PBLANC_NO(공고번호), HOUSE_NM(주택명), HSSPLY_ADRES(공급위치),
                  MVN_PREARNGE_YM(입주예정 YYYYMM), TOT_SUPLY_HSHLDCO(총공급세대),
                  RCRIT_PBLANC_DE(모집공고일), CNSTRCT_ENTRPS_NM(시공사),
                  HMPG_ADRES/PBLANC_URL(공고 홈페이지)
  2) getAPTLttotPblancMdl : APT '주택형별' 분양정보 (PBLANC_NO로 연결)
       주요 필드: HOUSE_TY(주택형), SUPLY_AR(공급면적 m2),
                  LTTOT_TOP_AMOUNT(분양최고금액, 만원), SUPLY_HSHLDCO(공급세대)

매칭 전략: 주택명 토큰으로 LIKE 검색 후, 입주월(YYYYMM)이 일치하는 공고를 선택.
          (동명·유사명 오매칭 방지의 핵심)

키: 환경변수 DATA_GO_KR_KEY 또는 저장소 루트 secret_key.txt (둘 다 gitignore)
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests

BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
OP_APT = "getAPTLttotPblancDetail"
OP_MDL = "getAPTLttotPblancMdl"

_GENERIC = {"서울", "아파트", "주상복합", "1단지", "2단지", "3단지"}
# 브랜드/일반 접미어 — 이것만 겹치는 오매칭(예: 서로 다른 '힐스테이트') 방지용.
# _distinctive()에서 제거해 '고유명'만 비교한다.
_BRANDS = (
    "힐스테이트", "래미안", "아이파크", "푸르지오", "e편한세상", "이편한세상",
    "디에이치", "롯데캐슬", "센트레빌", "리비에르", "트레지움", "센트럴",
    "시그니처", "시그니쳐", "해모로", "자이", "위브", "더샵", "역",
)


def load_key() -> str | None:
    key = os.environ.get("DATA_GO_KR_KEY")
    if key:
        return key.strip()
    f = Path(__file__).resolve().parent.parent / "secret_key.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    return None


def _get(session: requests.Session, op: str, key: str, **params) -> dict:
    """odcloud GET. serviceKey(URL-encoded)는 그대로 붙인다. cond[...]는 requests가 인코딩."""
    r = session.get(f"{BASE}/{op}", params={**params, "serviceKey": key},
                    timeout=25)
    # requests가 serviceKey의 %2B 등을 재인코딩하면 401 → 직접 조립으로 폴백
    if r.status_code == 401 and "%" in key:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        r = session.get(f"{BASE}/{op}?{qs}&serviceKey={key}", timeout=25)
    r.raise_for_status()
    return r.json()


def _norm(s: str) -> str:
    s = re.sub(r"\(.*?\)", "", s or "")          # 괄호 내용 제거
    return re.sub(r"[\s\-·]", "", s)              # 공백/하이픈/가운뎃점 제거


def _tokens(name: str) -> list[str]:
    """LIKE 검색용 후보 토큰(길이순, 일반어 제외)."""
    base = re.sub(r"\(.*?\)", "", name or "")
    words = [w for w in base.split() if len(w) >= 2 and w not in _GENERIC]
    words = sorted(set(words), key=len, reverse=True)
    whole = _norm(name)
    out = words + ([whole] if whole and whole not in words else [])
    return out or [whole]


def _distinctive(name: str, gu: str = "") -> str:
    """브랜드·자치구명·일반어를 제거한 '고유명' 정규화 문자열."""
    s = _norm(name)
    for b in _BRANDS:
        s = s.replace(b, "")
    if gu:
        s = s.replace(gu.replace("구", ""), "")   # '동작구' -> '동작' 제거
    return s


def _overlap(a: str, b: str) -> int:
    """두 정규화 문자열의 최장 공통 substring 길이(간이 유사도)."""
    best = 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = max(best, j - i)
            else:
                break
    return best


def find_pblanc(name: str, gu: str, move_in_ym: str, key: str,
                session: requests.Session) -> dict | None:
    """주택명(고유명)+입주월로 서울 APT 분양공고 1건을 찾는다.

    오매칭 방지: 브랜드·자치구명을 뺀 '고유명'이 실제로 겹칠 때만 채택하고,
    입주월(MVN_PREARNGE_YM)이 일치하는 후보를 우선한다. 확신이 없으면 None.
    """
    cands: dict[str, dict] = {}
    for tok in _tokens(name):
        try:
            d = _get(session, OP_APT, key, page=1, perPage=20,
                     **{"cond[SUBSCRPT_AREA_CODE_NM::EQ]": "서울",
                        "cond[HOUSE_NM::LIKE]": tok})
        except requests.HTTPError:
            raise
        except Exception:
            continue
        for it in d.get("data") or []:
            cands[it["PBLANC_NO"]] = it
        if any((it.get("MVN_PREARNGE_YM") or "") == move_in_ym
               for it in cands.values()):
            break  # 입주월까지 맞는 후보 확보 → 조기 종료

    target = _distinctive(name, gu)
    if not target:            # 고유명이 없으면(브랜드+지역명뿐) 신뢰 매칭 불가
        return None

    scored = []
    for it in cands.values():
        ov = _overlap(_distinctive(it.get("HOUSE_NM", ""), gu), target)
        month = (it.get("MVN_PREARNGE_YM") or "") == move_in_ym
        if ov >= 2 and (month or ov >= 4):   # 입주월 일치 or 고유명이 충분히 겹침
            scored.append((month, ov, it))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)  # 월일치 > 유사도
    return scored[0][2]


def fetch_prices(pblanc_no: str, key: str, session: requests.Session) -> list[dict]:
    """주택형별 분양가 목록."""
    d = _get(session, OP_MDL, key, page=1, perPage=50,
             **{"cond[PBLANC_NO::EQ]": pblanc_no})
    out = []
    for it in d.get("data") or []:
        amt = it.get("LTTOT_TOP_AMOUNT")
        try:
            price = int(str(amt).replace(",", "")) if amt else None
        except ValueError:
            price = None
        out.append({
            "type": it.get("HOUSE_TY"),          # 주택형 (예: 084.9800)
            "area": it.get("SUPLY_AR"),          # 공급면적 m2
            "price": price,                      # 분양최고금액(만원)
            "households": it.get("SUPLY_HSHLDCO"),
        })
    return out


def enrich_complexes(rows: list[dict], key: str | None = None,
                     delay: float = 0.25, log=print) -> list[dict]:
    key = key or load_key()
    if not key:
        log("  [분양정보] 키 없음 — 건너뜀")
        return rows

    session = requests.Session()
    ok = miss = 0
    for r in rows:
        if r.get("supply_type") != "분양":
            continue
        move_in_ym = r["move_in"].replace("-", "")
        try:
            pb = find_pblanc(r["name"], r.get("gu", ""), move_in_ym, key, session)
        except requests.HTTPError as e:
            log(f"  [분양정보] API 오류({e.response.status_code}) — 중단(키 확인 필요)")
            break
        if not pb:
            miss += 1
            log(f"  [분양정보] X {r['name']} (공고 매칭 실패)")
            time.sleep(delay)
            continue

        prices = []
        try:
            prices = fetch_prices(pb["PBLANC_NO"], key, session)
        except Exception as e:  # noqa: BLE001
            log(f"    (주택형별 조회 실패: {e})")
        valid = [p["price"] for p in prices if p["price"]]

        r["pblanc"] = {
            "pblanc_no": pb.get("PBLANC_NO"),
            "house_nm": pb.get("HOUSE_NM"),
            "supply_addr": pb.get("HSSPLY_ADRES"),
            "notice_date": pb.get("RCRIT_PBLANC_DE"),
            "builder": pb.get("CNSTRCT_ENTRPS_NM"),
            "homepage": pb.get("HMPG_ADRES") or pb.get("PBLANC_URL"),
        }
        r["price_by_type"] = prices
        r["bunyang_price_min"] = min(valid) if valid else None
        r["bunyang_price_max"] = max(valid) if valid else None
        r["bunyang_price"] = r["bunyang_price_min"]  # 대표값(최저)
        ok += 1
        rng = (f"{min(valid):,}~{max(valid):,}만원" if valid else "가격없음")
        log(f"  [분양정보] O {r['name']} <- {pb['HOUSE_NM']} ({rng})")
        time.sleep(delay)

    log(f"  [분양정보] 매칭 {ok} / 실패 {miss}")
    return rows


if __name__ == "__main__":
    k = load_key()
    if not k:
        raise SystemExit("secret_key.txt 없음")
    s = requests.Session()
    for nm, gu, ym in [("반포 래미안 트리니원", "서초구", "202608"),
                       ("디에이치 방배", "서초구", "202609"),
                       ("힐스테이트 동작 시그니쳐", "동작구", "202611"),
                       ("성동자이리버뷰", "성동구", "202612")]:
        pb = find_pblanc(nm, gu, ym, k, s)
        if pb:
            ps = fetch_prices(pb["PBLANC_NO"], k, s)
            v = [p["price"] for p in ps if p["price"]]
            print(f"{nm} -> {pb['HOUSE_NM']} | {min(v):,}~{max(v):,}만원 ({len(ps)}개 타입)")
        else:
            print(f"{nm} -> 매칭 실패")
