# 무신사 의류 랭킹 일일 리포트

## 목표
매일 오전 10시(KST), 무신사 의류 전체 랭킹(최근 1일)을 수집해 남성/여성별로 잘 팔리는·뜨는 아이템, 핏, 실루엣,
소재, 컬러를 분석하고 추천 아이템을 뽑는다. 결과는 **고정 주소 하나**(GitHub Pages `docs/index.html`)에
날짜별로 쌓는다. 매일 새 링크를 보내지 않는다.

## 수집 범위 (2026-09-25부터)
- 랭킹: **남성·여성 전체 랭킹**(섹션 199, 카테고리 000), 기간 `period=DAILY`(최근 1일)
- 1위부터 한 페이지(≈100위)씩 내려가며 **의류만 골라 성별마다 300개**가 모이면 멈춤 (2026-09-25 사장님 결정: "전체 랭킹 300위, 의류만, 300개 채우기")
- 의류 = 무신사 대분류 상의 001, 아우터 002, 바지 003, 원피스/스커트 100
- 제외: 뷰티 104, 신발 103, 가방 004, 모자 120, 소품 101, 속옷/홈웨어 026, 디지털/라이프 102, 키즈 106, 스포츠/레저 017(운동복 포함)
- 전체 랭킹에는 카테고리 표시가 없어서(모두 000) **상품 상세정보의 대분류로 의류인지 판별**. 비의류는 요청 1번, 의류는 2번(소재 포함). 한 번 본 상품은 다시 요청 안 함
- 급상승(201)·NEW(200)·유니섹스 구분은 쓰지 않음 (2026-09-24 사장님 결정)
- CSV의 `rank` = 무신사 전체 순위(비의류 포함), `clothing_rank` = 의류끼리 순위(1~300, 분석 가중치에 사용)
- 2026-09-24 기록은 예전 방식(카테고리별 1~200위)이라 추세 비교에서 자동으로 빠짐 (`analyze_trends.data_scope`)

## 순서와 Tool
| 단계 | Tool | 결과물 |
|---|---|---|
| 1. 랭킹 수집 (의류 판별용 상세정보 포함) | `tools/musinsa_fetch.py` | `data/history/YYYY-MM-DD.csv` |
| 2. 빠진 상세정보 채우기 | `tools/product_details.py` | `data/product_details.json` (상품별 누적 저장소) |
| 3. 분석 | `tools/analyze_trends.py` (분류: `tools/classify_attributes.py` + `tools/attribute_keywords.json`) | `.tmp/analysis_YYYY-MM-DD.json` |
| 4. 리포트 | `tools/build_report.py` | `docs/index.html`(최신), `docs/reports/YYYY-MM-DD.html`, `docs/dates.json` |

한 번에 실행: `python tools/run_daily.py`
자동 실행: `.github/workflows/daily.yml` (GitHub Actions, UTC 01:00). 실패하면 GitHub이 저장소 주인 계정 이메일로 자동 알림.
(`tools/send_email.py` + `--alert-on-fail`은 PC에서 돌릴 때 Gmail로 알림을 받고 싶을 때만 사용 — 현재 미사용)
사진을 품은 한 장짜리 페이지(Claude 링크 등): `python tools/build_report.py --date 날짜 --standalone 파일.html`

## 리포트 구성 (성별 탭마다, 2026-09-25 사장님 요청 반영)
1. 한눈에 보기: 가장 많은/뜨는 아이템·핏·실루엣·소재·컬러 + 카테고리 구성 막대
2. 추천 아이템 5개
3. 카테고리별 인기 TOP 10 (상의/아우터/바지/원피스·스커트 탭, 사진 카드)
4. 아이템 종류별 정리: 아이템마다 실루엣·기장 / 원단 / 핏 / 소재 / 컬러(실제 색 칩) / 디테일 비중 (3개 이상 오른 아이템만)
5. 전체 속성 순위 (막대 차트)
6. 가격대 분포 + 카테고리별 중간 가격
7. 어제보다 순위가 크게 오른 상품 / 새로 TOP 50 진입

## 분류 기준 (어디서 가져오나)
| 항목 | 1순위 | 없으면 |
|---|---|---|
| 아이템 종류 | 상세정보 공식 소분류 (예: 긴소매 티셔츠) | 상품명 키워드 (이름은 공식 소분류와 같게) |
| 핏 | 판매자 입력 핏 (스키니/슬림/레귤러/루즈/오버사이즈) | 상품명 키워드 |
| 소재(주원료) | 상품정보제공고시 '제품 소재'의 겉감 최대 비율 섬유 | 상품명 키워드 |
| 실루엣·기장, 원단·가공 | 상품명 키워드 | 상세 설명 글 키워드 |
| 컬러, 디테일 | 상품명 키워드 | — |
| 두께 | 판매자 입력 | — |

## 데이터 주소 (2026-09-24 확인)
- 랭킹: `https://api.musinsa.com/api2/hm/web/v5/pans/ranking/sections/199?storeCode=musinsa&gf=M&ageBand=AGE_BAND_ALL&period=DAILY&categoryCode=000&contentsId=`
  - 다음 페이지: `&page=2&offset={직전 마지막 순위}&startRank={+1}`
- 상품 상세: `https://goods-detail.musinsa.com/api2/goods/{상품번호}` (핏 등 `goodsMaterial`, 소분류 `category`, 설명 `goodsContents`)
- 제품 소재: `https://goods-detail.musinsa.com/api2/goods/{상품번호}/essential`
- 두 주소 모두 robots.txt 없음(404). www.musinsa.com은 등록 안 된 봇을 금지하므로 쓰지 않음.

## 필요한 설정
- 저장소: https://github.com/lkw5406-png/musinsa-trend (공개)
- **리포트 고정 링크: https://lkw5406-png.github.io/musinsa-trend/**
- GitHub Pages: Settings → Pages → Branch `main` / 폴더 `/docs` (저장소가 공개일 때만 무료로 켜짐)
- 비밀 정보 필요 없음 (Gmail 연동은 2026-09-24 사장님 결정으로 뺌)

## 수집 원칙 (바꾸지 말 것)
- 정직한 User-Agent(`MusinsaTrendReport/...`)로 요청. 사람 흉내·봇 위장 금지.
- 403/429(거부)가 오면 재시도하지 않고 멈춘 뒤 알림 메일. 사장님께 보고 후 방향 결정.
- 요청 횟수·간격을 늘리기 전에 사장님께 확인.
- 상세정보는 상품당 한 번만. 이미 있는 상품은 다시 요청하지 않음.

## 문제가 생겼을 때
- **"무신사가 데이터 요청을 거부"**: 클라우드(해외 서버)에서만 막히는지 로컬 PC에서 `python tools/musinsa_fetch.py`로 확인. PC에선 되면 Windows 작업 스케줄러로 전환 제안. 상세정보 단계에서 막혔다면 받은 만큼은 저장돼 있으니 다음 날 이어서 받음.
- **"수집 결과가 비정상적으로 적음" (구조 변경)**: `https://api.musinsa.com/api2/hm/web/v5/pans/ranking?storeCode=musinsa&subPan=product`에서 섹션 번호(`"sectionId"`)와 탭 이름(`applied_tab`, `extra_info`) 재확인. 상품 필드(`items[].info`, `items[].image.rank`)가 바뀌었으면 `parse_products` 수정.
- **분류 누락이 많음**: `python tools/classify_attributes.py data/history/날짜.csv`로 확인 → `attribute_keywords.json`에 키워드 추가. 짧은 키워드는 `re:` 정규식으로 다른 단어 안에서 잡히지 않게 (예: `re:블루(?!종)`).
- **소재가 이상하게 나옴**: `product_details.py`의 `FIBERS` 목록/`main_fiber` 확인. 표기 예시와 기대값을 먼저 테스트.
- **실패 알림을 못 받음**: GitHub → 오른쪽 위 프로필 → Settings → Notifications → Actions에서 실패 알림 이메일이 켜져 있는지 확인. 실행 기록은 저장소의 Actions 탭.

## 알게 된 것 (계속 추가)
- 2026-09-24: 랭킹 1페이지 ≈ 101개 (3페이지면 300위까지 빠짐없이 받음, 2026-09-25 확인). 전체 카테고리(000) 랭킹은 상품의 실제 카테고리를 알려주지 않아 카테고리별로 요청해야 함.
- 2026-09-24: 기간 옵션 `period`: REALTIME(실시간) / DAILY(1일) / WEEKLY(1주) / MONTHLY(1개월).
- 2026-09-24: 남성(M) × 원피스/스커트(100)는 0개 → `SKIP`.
- 2026-09-24: 상품명만으로는 실루엣 35%, 소재 41%만 분류됨 → 상세정보(판매자 입력 핏·제품 소재) 추가. 판매자 절반가량은 핏을 비워 둠.
- 2026-09-24: 짧은 키워드 함정 — '슬리브' 안의 '리브', '티셔츠' 안의 '셔츠', '블루종' 안의 '블루', '올리브' 안의 '리브'. 정규식으로 막아 둠.
- 2026-09-24: 상세정보 수집을 여러 번 시작하면 동시에 돌며 같은 파일을 덮어씀(요청도 몇 배). → 잠금 파일(`.tmp/product_details.lock`)로 하나만 돌게 막음. 10분 넘게 갱신 없으면 멈춘 것으로 보고 새로 시작 허용.
- 2026-09-24: 제품 소재 표기는 제각각 ("면100%", "COTTON 79% POLY 21%", "(OUTSHELL) NYLON 100% (LINING)..."). 안감·충전재 앞까지를 겉감으로 봄.
