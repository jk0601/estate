"""
3단계: 네이버 부동산 연동 + 입주장 전세가율.

⚠️ 네이버 현재 매물 API(new.land.naver.com)는 인증 토큰 + 강한 rate-limit로
   보호되어 자동 스크래핑이 불가능하고 이용약관에도 어긋납니다. 그래서 여기서는
   '스크래핑' 대신 다음 두 가지로 실사용 가치를 확보합니다.

   (A) 단지 검색(302 redirect)로 네이버 '단지번호'를 안정적으로 얻어,
       각 단지의 매물 페이지로 바로 가는 딥링크를 만든다. (휴대폰 한 번 탭)
   (B) 가족이 관찰한 전세 호가를 data/jeonse.csv 에 적으면,
       분양가 대비 '전세가율'을 자동 계산해 카드에 표시한다.

단지번호 해결: GET https://m.land.naver.com/search/result/{이름}
  -> 302 Location: /complex/info/{complexNo}?... 에서 번호 추출
"""

from __future__ import annotations

import csv
import re
import time
import urllib.parse
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
SEARCH = "https://m.land.naver.com/search/result/"
_NO_RE = re.compile(r"/complex/info/(\d+)")
JEONSE_CSV = Path(__file__).resolve().parent.parent / "data" / "jeonse.csv"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://m.land.naver.com/"})
    return s


def _name_variants(row: dict) -> list[str]:
    """검색 성공률을 높이기 위한 이름 후보."""
    name = row["name"]
    variants = [name]
    # 앞의 지역 접두어 제거: '동작 보라매역 프리센트' -> '보라매역 프리센트'
    parts = name.split()
    if len(parts) > 1 and (parts[0] == row.get("gu", "").replace("구", "")
                           or parts[0] == row.get("dong", "").replace("동", "")):
        variants.append(" ".join(parts[1:]))
    # 분양 공고명이 다르면 그것도 시도
    pb = (row.get("pblanc") or {}).get("house_nm")
    if pb and pb not in variants:
        variants.append(pb)
    return variants


def resolve_complex_no(row: dict, session: requests.Session) -> str | None:
    for q in _name_variants(row):
        try:
            r = session.get(SEARCH + urllib.parse.quote(q),
                            allow_redirects=False, timeout=20)
        except requests.RequestException:
            continue
        m = _NO_RE.search(r.headers.get("Location", ""))
        if m:
            return m.group(1)
    return None


def mobile_url(complex_no: str | None, fallback_name: str) -> str:
    if complex_no:
        return f"https://m.land.naver.com/complex/info/{complex_no}"
    return SEARCH + urllib.parse.quote(fallback_name)


def load_jeonse() -> dict[str, dict]:
    """data/jeonse.csv (가족이 관찰한 전세 호가) 로드. name -> {low, high, note}."""
    if not JEONSE_CSV.exists():
        return {}
    out = {}
    with open(JEONSE_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            name = (r.get("name") or "").strip()
            if not name:
                continue
            def _num(k):
                v = re.sub(r"[^0-9]", "", r.get(k, "") or "")
                return int(v) if v else None
            out[name] = {"low": _num("jeonse_low_manwon"),
                         "high": _num("jeonse_high_manwon"),
                         "note": (r.get("note") or "").strip(),
                         "updated": (r.get("updated") or "").strip()}
    return out


def enrich_naver(rows: list[dict], resolve_no: bool = True,
                 delay: float = 0.3, log=print) -> list[dict]:
    jeonse = load_jeonse()
    if jeonse:
        log(f"  [네이버] 전세 시트 {len(jeonse)}건 로드")
    session = _session()
    resolved = 0
    for r in rows:
        no = None
        if resolve_no:
            no = resolve_complex_no(r, session)
            if no:
                resolved += 1
            time.sleep(delay)
        r["naver_complex_no"] = no
        r["naver_url"] = mobile_url(no, r["name"])

        # 전세 오버레이 + 전세가율(분양 최저가 대비)
        j = jeonse.get(r["name"])
        if j and j.get("low"):
            r["jeonse_low"] = j["low"]
            r["jeonse_high"] = j.get("high")
            r["jeonse_note"] = j.get("note")
            base = r.get("bunyang_price_min")
            if base:
                r["jeonse_ratio"] = round(j["low"] / base * 100)
    log(f"  [네이버] 단지번호 해결 {resolved}/{len(rows)} (딥링크 연결)")
    return rows


if __name__ == "__main__":
    import json
    d = json.load(open(Path(__file__).parent.parent / "docs" / "data.json",
                       encoding="utf-8"))
    s = _session()
    for r in d["complexes"]:
        if r["supply_type"] == "분양":
            no = resolve_complex_no(r, s)
            print(f"  {r['name'][:24]:26} -> {no}  {mobile_url(no, r['name'])}")
            time.sleep(0.3)
