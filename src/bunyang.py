"""
2단계: 청약홈 분양정보 조회(공공데이터포털 odcloud API)로 분양 단지 정보 보강.

서비스: 한국부동산원_청약홈 분양정보 조회 서비스 (data.go.kr 15098547)
엔드포인트(검증된 오퍼레이션):
    GET https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail
      - APT 분양 '공고' 단위 메타데이터 (공급위치, 총공급세대, 청약기간, 공고 홈페이지 등)
      - 공고 고유키: PBLANC_NO
      - 조건검색(cond) 지원: cond[HOUSE_NM::LIKE]=..., cond[SUBSCRPT_AREA_CODE_NM::EQ]=서울

⚠️ 분양가 관련:
    평형별 '공급금액(분양최고금액)'은 이 공고 API가 아니라 '주택형별 분양정보'
    (data.go.kr 15101047, 파일데이터/CSV)에 있습니다. 따라서 분양가는
    getAPTLttotPblancDetail 응답에 없을 수 있습니다. 이 모듈은 응답에 가격 후보
    필드가 있으면 채우고, 없으면 None으로 두고 '공고 링크'만 붙입니다.
    (첫 호출 시 dump_schema=True 로 실제 필드명을 확인하세요.)

키: 환경변수 DATA_GO_KR_KEY 또는 저장소 루트 secret_key.txt (둘 다 gitignore 대상)
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests

BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
OP_APT = "getAPTLttotPblancDetail"

# 응답에서 분양가로 쓸 수 있는 후보 필드명(있으면 사용). 실제 확인 후 조정.
PRICE_FIELD_CANDIDATES = (
    "LTTOT_TOP_AMOUNT", "SUPLY_AMOUNT", "SPSPLY_AMOUNT", "TOP_AMOUNT",
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
    """odcloud GET. serviceKey는 이미 URL-encoded 형태를 그대로 붙인다."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}/{op}?{qs}&serviceKey={key}"
    r = session.get(url, timeout=25)
    r.raise_for_status()
    return r.json()


def _norm(s: str) -> str:
    """단지명 비교용 정규화: 공백/괄호내용 제거."""
    s = re.sub(r"\(.*?\)", "", s or "")
    return re.sub(r"\s+", "", s)


def lookup_apt(name: str, key: str, session: requests.Session,
               dump_schema: bool = False) -> dict | None:
    """주택명으로 서울 APT 분양공고 1건을 찾아 요약 dict 반환. 없으면 None."""
    # 괄호/별칭 제거한 핵심 토큰으로 LIKE 검색
    q = _norm(name)[:10]
    data = _get(
        session, OP_APT, key,
        page=1, perPage=30,
        **{"cond[SUBSCRPT_AREA_CODE_NM::EQ]": "서울",
           "cond[HOUSE_NM::LIKE]": q},
    )
    items = data.get("data") or []
    if dump_schema and items:
        print("  [schema] getAPTLttotPblancDetail 필드:", sorted(items[0].keys()))
    if not items:
        return None

    # 정규화 이름이 가장 잘 겹치는 후보 선택
    target = _norm(name)
    best = None
    for it in items:
        hn = _norm(it.get("HOUSE_NM", ""))
        if hn and (hn in target or target in hn or hn[:6] == target[:6]):
            best = it
            break
    best = best or items[0]

    price = None
    for fld in PRICE_FIELD_CANDIDATES:
        if best.get(fld):
            price = best[fld]
            break

    return {
        "pblanc_no": best.get("PBLANC_NO"),
        "house_nm": best.get("HOUSE_NM"),
        "supply_addr": best.get("HSSPLY_ADRES"),
        "tot_households": best.get("TOT_SUPLY_HSHLDCO"),
        "notice_date": best.get("RCRIT_PBLANC_DE"),
        "move_in_expect": best.get("MVN_PREARNGE_YM"),
        "homepage": best.get("HMPG_ADRES") or best.get("PBLANC_URL"),
        "bunyang_price": price,      # 없으면 None (주택형별 CSV 필요)
        "_matched_by": "name-like",
    }


def enrich_complexes(rows: list[dict], key: str | None = None,
                     delay: float = 0.3, log=print) -> list[dict]:
    """분양(supply_type=='분양') 단지에 한해 공고 메타/분양가 보강."""
    key = key or load_key()
    if not key:
        log("  [분양정보] 키 없음 — 건너뜀 (secret_key.txt 또는 DATA_GO_KR_KEY)")
        return rows

    session = requests.Session()
    dump = True
    ok, miss = 0, 0
    for r in rows:
        if r.get("supply_type") != "분양":
            continue
        try:
            info = lookup_apt(r["name"], key, session, dump_schema=dump)
            dump = False
        except requests.HTTPError as e:
            log(f"  [분양정보] API 오류({e.response.status_code}) — 중단. 키 활성화 확인 필요")
            break
        except Exception as e:  # noqa: BLE001
            log(f"  [분양정보] '{r['name']}' 조회 실패: {e}")
            info = None
        if info:
            r["pblanc"] = info
            if info.get("bunyang_price"):
                r["bunyang_price"] = info["bunyang_price"]
            ok += 1
            log(f"  [분양정보] O {r['name']} <- {info['house_nm']} (공고 {info['pblanc_no']})")
        else:
            miss += 1
            log(f"  [분양정보] X {r['name']} (공고 매칭 실패)")
        time.sleep(delay)
    log(f"  [분양정보] 매칭 {ok} / 실패 {miss}")
    return rows


if __name__ == "__main__":
    # 단독 진단: 키 유효성 + 실제 응답 스키마 확인
    k = load_key()
    if not k:
        raise SystemExit("secret_key.txt 없음")
    s = requests.Session()
    print("샘플 조회: '반포 래미안 트리니원'")
    info = lookup_apt("반포 래미안 트리니원", k, s, dump_schema=True)
    print(info)
