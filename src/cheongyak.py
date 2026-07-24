"""
청약홈(한국부동산원) '입주(예정)정보' 수집 모듈.

공식 페이지: https://www.applyhome.co.kr/ai/aia/selectAPTMvnPrearngeHsHldcoList.do
실제 목록 데이터는 아래 내부 엔드포인트가 페이지네이션된 HTML 표로 내려줍니다.
    POST /ai/aia/selectAPTMvnPrearngeInfoList.do  (pageIndex=N)
표 컬럼: [지역, 분양/임대, 주소, 주택명, 입주예정월(YYYY-MM), 세대수]

전국 목록을 페이지 단위로 받아 우리가 원하는 조건(서울 + 특정 월 범위)으로
파이썬에서 직접 필터링합니다. (사이트의 지역/월 필터 파라미터가 세션 상태에
의존적이라, 전체를 받아 거르는 방식이 가장 안정적입니다.)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict

import requests
from bs4 import BeautifulSoup

BASE = "https://www.applyhome.co.kr"
SEED_URL = f"{BASE}/ai/aia/selectAPTMvnPrearngeHsHldcoList.do"
LIST_URL = f"{BASE}/ai/aia/selectAPTMvnPrearngeInfoList.do"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_GU_RE = re.compile(r"([가-힣]+구)\b")
_SIGUN_RE = re.compile(r"([가-힣]+(?:시|군))\b")   # 경기 등: 시/군 단위
_DONG_RE = re.compile(r"([가-힣]+(?:동|가|리))\b")


def _district(region: str, address: str) -> str:
    """행정구역 이름: 서울은 자치구(강남구), 그 외(경기 등)는 시/군(화성시·가평군)."""
    if region.startswith("서울"):
        m = _GU_RE.search(address)
    else:
        m = _SIGUN_RE.search(address) or _GU_RE.search(address)
    return m.group(1) if m else ""


@dataclass
class Complex:
    region: str          # 시도 (서울 / 경기 등)
    supply_type: str     # 분양 / 임대
    address: str         # 전체 주소
    gu: str              # 자치구(서울) 또는 시(경기)
    dong: str            # 법정동 (주소에서 추출)
    name: str            # 주택명(단지명)
    move_in: str         # 입주예정월 (YYYY-MM)
    households: int      # 입주예정 세대수


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    # 최초 방문으로 세션 쿠키 확보
    s.get(SEED_URL, timeout=25)
    return s


def _parse_int(text: str) -> int:
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else 0


def _parse_page(html: str) -> list[Complex]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Complex] = []
    for tr in soup.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        cells = [td.get_text(strip=True) for td in tds]
        region, supply_type, address, name, move_in, households = cells[:6]
        # 데이터 없음 안내행 등 방어
        if not region or not re.match(r"\d{4}-\d{2}", move_in):
            continue
        dong_m = _DONG_RE.search(address)
        rows.append(
            Complex(
                region=region,
                supply_type=supply_type,
                address=address,
                gu=_district(region, address),
                dong=dong_m.group(1) if dong_m else "",
                name=name,
                move_in=move_in,
                households=_parse_int(households),
            )
        )
    return rows


def _max_page(html: str) -> int:
    nums = [int(n) for n in re.findall(r"fn_link_page\((\d+)\)", html)]
    return max(nums) if nums else 1


def fetch_all(
    session: requests.Session | None = None,
    max_pages: int = 100,
    delay: float = 0.4,
    stop_after: str | None = None,
    log=print,
) -> list[Complex]:
    """전국 입주예정 목록을 페이지 순서대로 수집.

    목록은 입주예정월 오름차순이므로, stop_after(YYYY-MM)를 넘어서는 페이지가
    나오면 조기 종료해 불필요한 요청을 줄입니다.
    """
    s = session or _make_session()
    headers = {"X-Requested-With": "XMLHttpRequest", "Referer": SEED_URL}

    first = s.post(LIST_URL, data={"pageIndex": 1}, headers=headers, timeout=25)
    first.raise_for_status()
    last = min(_max_page(first.text), max_pages)
    out = _parse_page(first.text)
    log(f"  page 1/{last}: {len(out)} rows")

    for page in range(2, last + 1):
        time.sleep(delay)
        r = s.post(LIST_URL, data={"pageIndex": page}, headers=headers, timeout=25)
        r.raise_for_status()
        rows = _parse_page(r.text)
        out.extend(rows)
        log(f"  page {page}/{last}: {len(rows)} rows")
        if stop_after and rows:
            earliest = min(x.move_in for x in rows)
            if earliest > stop_after:
                log(f"  -> {earliest} > {stop_after}, 조기 종료")
                break
    return out


def collect_regions(
    months: list[str],
    sidos: tuple[str, ...] = ("서울",),
    include_types: tuple[str, ...] = ("분양",),
    **kwargs,
) -> list[dict]:
    """지정한 시도(서울/경기 등) + 입주예정월(YYYY-MM 리스트) 단지만 반환.

    sidos: 시도명 접두어 매칭(예: ('서울','경기')).
    include_types: 기본 '분양'만, 임대까지 보려면 ('분양','임대').
    """
    stop_after = max(months) if months else None
    allrows = fetch_all(stop_after=stop_after, **kwargs)
    wanted = set(months)
    result = [
        asdict(c)
        for c in allrows
        if any(c.region.startswith(s) for s in sidos)
        and c.move_in in wanted
        and (not include_types or c.supply_type in include_types)
    ]
    result.sort(key=lambda x: (x["move_in"], x["region"], x["gu"], x["name"]))
    return result


# 하위호환 별칭
def collect_seoul(months, include_types=("분양",), **kwargs):
    return collect_regions(months, sidos=("서울",), include_types=include_types, **kwargs)


if __name__ == "__main__":
    ms = ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]
    data = collect_regions(ms, sidos=("서울", "경기"), include_types=("분양", "임대"))
    print(f"\n입주예정({ms[0]}~{ms[-1]}): {len(data)}개 단지")
    for d in data:
        print(f"  {d['move_in']}  {d['region']:3} {d['gu']:7} {d['name']}  ({d['households']}세대)")
