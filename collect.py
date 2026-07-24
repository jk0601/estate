#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
1단계 수집기: 서울 입주예정 단지 목록 -> docs/data.json

실행:
    python collect.py

동작:
  1) 청약홈 '입주예정정보'에서 서울 + 지정 기간(기본 2026-08~12) 단지 수집
  2) 청약홈 분양정보 API로 분양 단지의 평형별 분양가 보강
  3) 각 단지에 네이버 단지번호 딥링크 부착 -> docs/data.json 저장
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from cheongyak import collect_regions  # noqa: E402
from bunyang import enrich_complexes    # noqa: E402  (2단계: 분양정보 보강)
from naver import enrich_naver          # noqa: E402  (3단계: 네이버 매물 딥링크)


def month_range(start: str, end: str) -> list[str]:
    """'YYYY-MM' 시작~끝(포함) 월 목록 생성."""
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ---- 설정 -----------------------------------------------------------------
START_MONTH, END_MONTH = "2026-08", "2027-12"   # 앞으로 약 18개월
TARGET_MONTHS = month_range(START_MONTH, END_MONTH)
TARGET_SIDO = ("서울", "경기")                    # 수도권
# '분양'만 보고 싶으면 ("분양",), 임대까지 포함하려면 ("분양", "임대")
INCLUDE_TYPES = ("분양", "임대")
OUT_PATH = Path(__file__).parent / "docs" / "data.json"
KST = timezone(timedelta(hours=9))
# ---------------------------------------------------------------------------


def enrich(rows: list[dict]) -> list[dict]:
    for i, r in enumerate(rows):
        r["id"] = i + 1
        r["bunyang_price"] = None      # 2단계(분양정보 API)에서 채움
    return rows


def main() -> int:
    sido_label = "·".join(TARGET_SIDO)
    print(f"[수집 시작] {sido_label} 입주예정 {TARGET_MONTHS[0]} ~ {TARGET_MONTHS[-1]}")
    rows = collect_regions(TARGET_MONTHS, sidos=TARGET_SIDO, include_types=INCLUDE_TYPES)
    rows = enrich(rows)

    # 2단계: 분양 단지 분양정보/분양가 보강 (키 없거나 미활성화면 자동 skip)
    try:
        rows = enrich_complexes(rows)
    except Exception as e:  # noqa: BLE001  파이프라인은 절대 깨지지 않게
        print(f"  [분양정보] 보강 생략: {e}")

    # 3단계: 네이버 단지번호 딥링크(단지별 매물 바로가기)
    try:
        rows = enrich_naver(rows)
    except Exception as e:  # noqa: BLE001
        print(f"  [네이버] 보강 생략: {e}")

    payload = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "source": "청약홈(한국부동산원) 입주(예정)정보",
        "sido": list(TARGET_SIDO),
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
