#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
1단계 수집기: 서울 입주예정 단지 목록 -> docs/data.json

실행:
    python collect.py

동작:
  1) 청약홈 '입주예정정보'에서 서울 + 지정 기간(기본 2026-08~12) 단지 수집
  2) 각 단지에 네이버 부동산 모바일 검색 링크 부착(휴대폰에서 바로 현재 매물 확인용)
  3) docs/data.json 으로 저장  ->  docs/index.html 이 읽어 화면에 뿌림

분양가/입주전세가 자동 매칭(2·3단계)은 이후 확장 지점(TODO)으로 비워둠.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from cheongyak import collect_seoul  # noqa: E402
from bunyang import enrich_complexes  # noqa: E402  (2단계: 분양정보 보강)
from naver import enrich_naver        # noqa: E402  (3단계: 네이버 딥링크 + 전세가율)

# ---- 설정 -----------------------------------------------------------------
TARGET_MONTHS = ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]
# '분양'만 보고 싶으면 ("분양",), 임대까지 포함하려면 ("분양", "임대")
INCLUDE_TYPES = ("분양", "임대")
OUT_PATH = Path(__file__).parent / "docs" / "data.json"
KST = timezone(timedelta(hours=9))
# ---------------------------------------------------------------------------


def naver_search_url(name: str) -> str:
    """네이버 부동산 모바일 검색 링크(단지명으로 현재 매물 조회)."""
    return "https://m.land.naver.com/search/result/" + urllib.parse.quote(name)


def enrich(rows: list[dict]) -> list[dict]:
    for i, r in enumerate(rows):
        r["id"] = i + 1
        r["naver_url"] = naver_search_url(r["name"])
        # 2단계에서 청약홈 분양정보 API로 채울 자리
        r["bunyang_price"] = None      # 평형별 분양가(만원)
        # 3단계에서 네이버 매물 스크래핑으로 채울 자리
        r["jeonse_low"] = None         # 현재 최저 전세 호가(만원)
        r["listings_count"] = None     # 현재 매물 수
    return rows


def main() -> int:
    print(f"[수집 시작] 서울 입주예정 {TARGET_MONTHS[0]} ~ {TARGET_MONTHS[-1]}")
    rows = collect_seoul(TARGET_MONTHS, include_types=INCLUDE_TYPES)
    rows = enrich(rows)

    # 2단계: 분양 단지 분양정보/분양가 보강 (키 없거나 미활성화면 자동 skip)
    try:
        rows = enrich_complexes(rows)
    except Exception as e:  # noqa: BLE001  파이프라인은 절대 깨지지 않게
        print(f"  [분양정보] 보강 생략: {e}")

    # 3단계: 네이버 단지번호 딥링크 + (전세 시트 있으면) 전세가율
    try:
        rows = enrich_naver(rows)
    except Exception as e:  # noqa: BLE001
        print(f"  [네이버] 보강 생략: {e}")

    payload = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "source": "청약홈(한국부동산원) 입주(예정)정보",
        "region": "서울특별시",
        "months": TARGET_MONTHS,
        "count": len(rows),
        "complexes": rows,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    private = sum(1 for r in rows if r["supply_type"] == "분양")
    print(f"[완료] {len(rows)}개 단지 (분양 {private} / 임대 {len(rows) - private})")
    print(f"[저장] {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
