# 서울 입주예정 단지 트래커 (2026 하반기)

대출 규제 강화로 **입주장(신축 입주 시기) 급전세·급매**가 나오는 서울 단지를
한눈에 보기 위한 개인/가족용 도구입니다. 올해(2026년) 안에 입주 가능한 집을 찾는 것이 목표.

- **데이터 출처**: 청약홈(한국부동산원) 입주(예정)정보 — 공식
- **현재 매물/시세**: 각 단지의 네이버 부동산 링크로 바로 이동(모바일 최적화)
- **화면**: `docs/index.html` (GitHub Pages로 서빙 → 휴대폰에서 열람)

현재는 **1단계(대상 단지 리스트업 + 모바일 열람)** 까지 구현되어 있습니다.

---

## 빠른 시작

```bash
# 1) 의존성 설치
pip install -r requirements.txt

# 2) 데이터 수집 (docs/data.json 생성)
python collect.py

# 3) 로컬 미리보기 (휴대폰과 같은 화면)
python -m http.server -d docs 8000
#   -> 브라우저에서 http://localhost:8000
```

기본 수집 조건: **서울 · 2026-08 ~ 2026-12 · 분양+임대**.
바꾸려면 `collect.py` 상단의 `TARGET_MONTHS`, `INCLUDE_TYPES`를 수정하세요.

---

## 가족에게 공유하기 (GitHub Pages)

1. 이 저장소를 GitHub에 올립니다(push).
2. 저장소 **Settings → Pages → Build and deployment**
   - Source: **Deploy from a branch**
   - Branch: **main** / 폴더: **/docs** 선택 후 Save
3. 잠시 후 `https://<사용자명>.github.io/<저장소명>/` 주소가 생성됩니다.
   이 링크를 가족에게 보내면 **휴대폰에서 바로** 열람할 수 있습니다.

> 데이터를 새로 갱신하려면 `python collect.py` 실행 후 변경된 `docs/data.json`을
> 다시 커밋·push 하면 됩니다. (자동화는 아래 참고)

### (선택) 매일 자동 갱신 — Windows 작업 스케줄러
`python collect.py` 를 매일 아침 실행하도록 등록하고, 변경분을 커밋/푸시하는
배치를 걸어두면 링크가 항상 최신 상태로 유지됩니다.

---

## 구조

```
estate/
├─ collect.py          # 오케스트레이터: 1→2→3단계 수집 → docs/data.json
├─ src/
│  ├─ cheongyak.py     # 1단계: 청약홈 입주예정정보 스크래퍼
│  ├─ bunyang.py       # 2단계: 청약홈 분양정보 API(분양가)
│  └─ naver.py         # 3단계: 네이버 단지번호 딥링크 + 전세가율
├─ data/
│  └─ jeonse.csv       # 가족이 적는 전세 호가(전세가율 계산용)
├─ docs/               # GitHub Pages 루트
│  ├─ index.html       # 모바일 반응형(구/월/예산 필터, 분양가·전세가율, 매물 딥링크)
│  └─ data.json        # 생성물(커밋 대상)
├─ requirements.txt
└─ README.md
```

## 데이터 항목 (`docs/data.json`)

| 필드 | 설명 |
|---|---|
| `name` | 단지명(주택명) |
| `gu` / `dong` | 자치구 / 법정동 |
| `address` | 전체 주소 |
| `move_in` | 입주예정월 (YYYY-MM) |
| `households` | 입주예정 세대수 |
| `supply_type` | 분양 / 임대 |
| `naver_complex_no` | 네이버 단지번호(해결 시) |
| `naver_url` | 네이버 단지 매물 딥링크(없으면 검색 링크) |
| `jeonse_low`/`jeonse_high`/`jeonse_ratio` | 전세 호가·전세가율 — `data/jeonse.csv` 입력 시 |
| `bunyang_price_min` / `_max` | 평형별 분양최고금액의 최저~최고(만원) — 청약홈 API |
| `price_by_type` | 주택형별 `[{type, area, price(만원), households}]` |
| `pblanc` | 공고정보 `{pblanc_no, supply_addr, builder, notice_date, homepage}` |
| `jeonse_low` / `listings_count` | 현재 최저 전세·매물 수 — *3단계에서 채움* |

---

## API 키 설정 (2단계)

청약홈 분양정보 API를 쓰려면 공공데이터포털 키가 필요합니다.

1. [청약홈 분양정보 조회 서비스(15098547)](https://www.data.go.kr/data/15098547/openapi.do)에서 **활용신청**
2. 발급된 **일반 인증키(Encoding)** 를 저장소 루트 `secret_key.txt`에 한 줄로 저장
   (또는 환경변수 `DATA_GO_KR_KEY`). 이 파일은 `.gitignore`로 커밋되지 않습니다.
3. `python collect.py` 실행 → 분양 단지에 공고정보가 보강됩니다.

> 참고: 이 API는 공고 메타데이터(공급위치·총세대·청약기간·공고 홈페이지)를 제공하며,
> **평형별 분양가(공급금액)는 별도 '주택형별 분양정보'(파일데이터 15101047)** 에 있어
> API만으로는 분양가가 안 나올 수 있습니다. 실제 응답 필드는 첫 실행 시 콘솔에 덤프됩니다.

## 로드맵

- [x] **1단계** 서울 입주예정 단지 자동 수집 + 모바일 열람 페이지
- [x] **2단계** 청약홈 분양정보 API로 **평형별 분양가** 매칭 (10/13 분양단지, 금액 필터·정렬)
      → `getAPTLttotPblancDetail`(공고) + `getAPTLttotPblancMdl`(주택형별 분양가), 입주월로 오매칭 방지
- [x] **3단계** 네이버 **단지번호 딥링크**(단지별 전세·매물 바로가기) + **전세가율**
      → ⚠️ 네이버 매물 API는 인증·강한 rate-limit로 자동 스크래핑 불가·약관 위반.
        대신 딥링크로 실시간 호가를 한 번에 열람하고, `data/jeonse.csv`에 관찰 전세가를
        적으면 분양가 대비 전세가율을 자동 계산.
- [ ] **4단계(후보)** 실거래가 API 연동(입주 후 전월세 실거래), 시세 추이 차트

## 전세 시트 사용법 (전세가율 보기)

입주장 전세 호가는 공식 API가 없어(신축 미입주라 실거래도 없음) 자동 수집이 어렵습니다.
그래서 가족이 **각 단지 카드의 "전세·매물 보기"를 눌러 본 최저 전세 호가**를
`data/jeonse.csv`에 적으면, 분양가 대비 **전세가율**이 카드에 자동 표시됩니다.

```csv
name,jeonse_low_manwon,jeonse_high_manwon,note,updated
반포 래미안 트리니원,180000,210000,입주장 급전세,2026-07-24
```
(금액은 만원 단위: 180000 = 18억) 저장 후 `python collect.py` 다시 실행 → push.

## 주의

- 개인/가족 참고용입니다. 매물·시세는 네이버 링크의 실시간 정보를 확인하세요.
- 스크래핑은 공개된 공식 정보를 저빈도로 조회합니다. 대상 사이트에 부담을 주지
  않도록 요청 간격(`src/cheongyak.py`의 `delay`)을 지켜주세요.
- **실제 계약 전 반드시 입주자모집공고·현장·등기부를 직접 확인하세요.**
