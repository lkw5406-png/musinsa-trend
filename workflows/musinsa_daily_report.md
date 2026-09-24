# 무신사 의류 랭킹 일일 리포트

## 목표
매일 오전 10시(KST), 무신사 의류 전체 랭킹(최근 1일)을 수집해 남성/여성별로 잘 팔리는·뜨는 아이템, 핏, 실루엣,
소재, 컬러를 분석하고 추천 아이템을 뽑는다. 결과는 **고정 주소 하나**(GitHub Pages `docs/index.html`)에
날짜별로 쌓는다. 매일 새 링크를 보내지 않는다.

## 수집 범위
- 랭킹: 전체 랭킹(섹션 199), 기간 `period=DAILY`(최근 1일). 급상승(201)·NEW(200)·유니섹스 구분은 쓰지 않음 (2026-09-24 사장님 결정)
- 성별 필터: 남성(M), 여성(F)
- 카테고리: 상의 001, 아우터 002, 바지 003, 원피스/스커트 100 (남성 × 원피스/스커트는 비어 있어 제외)
- 제외: 뷰티 104, 신발 103, 가방 004, 모자 120, 소품 101, 속옷/홈웨어 026, 디지털/라이프 102, 키즈 106, 스포츠/레저 017
- 랭킹: 7개 목록 × 200위 → 요청 14회, 4초 간격 (약 1분), 하루 1,400행
- 상세정보: 처음 보는 상품만, 상품당 요청 2회, 2초 간격. 첫날 1,318개(약 1.5시간), 이후 하루 수십~수백 개

## 순서와 Tool
| 단계 | Tool | 결과물 |
|---|---|---|
| 1. 랭킹 수집 | `tools/musinsa_fetch.py` | `data/history/YYYY-MM-DD.csv` |
| 2. 상세정보 수집 | `tools/product_details.py` | `data/product_details.json` (상품별 누적 저장소) |
| 3. 분석 | `tools/analyze_trends.py` (분류: `tools/classify_attributes.py` + `tools/attribute_keywords.json`) | `.tmp/analysis_YYYY-MM-DD.json` |
| 4. 리포트 | `tools/build_report.py` | `docs/index.html`(최신), `docs/reports/YYYY-MM-DD.html`, `docs/dates.json` |

한 번에 실행: `python tools/run_daily.py`
자동 실행: `.github/workflows/daily.yml` (GitHub Actions, UTC 01:00). 실패하면 GitHub이 저장소 주인 계정 이메일로 자동 알림.
(`tools/send_email.py` + `--alert-on-fail`은 PC에서 돌릴 때 Gmail로 알림을 받고 싶을 때만 사용 — 현재 미사용)
사진을 품은 한 장짜리 페이지(Claude 링크 등): `python tools/build_report.py --date 날짜 --standalone 파일.html`

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
- 랭킹: `https://api.musinsa.com/api2/hm/web/v5/pans/ranking/sections/199?storeCode=musinsa&gf=M&ageBand=AGE_BAND_ALL&period=DAILY&categoryCode=001&contentsId=`
  - 다음 페이지: `&page=2&offset={직전 마지막 순위}&startRank={+1}`
- 상품 상세: `https://goods-detail.musinsa.com/api2/goods/{상품번호}` (핏 등 `goodsMaterial`, 소분류 `category`, 설명 `goodsContents`)
- 제품 소재: `https://goods-detail.musinsa.com/api2/goods/{상품번호}/essential`
- 두 주소 모두 robots.txt 없음(404). www.musinsa.com은 등록 안 된 봇을 금지하므로 쓰지 않음.

## 필요한 설정
- GitHub Pages: Settings → Pages → Branch `main` / 폴더 `/docs` → 이 주소가 사장님이 보는 고정 링크
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
- 2026-09-24: 랭킹 1페이지 ≈ 101개. 전체 카테고리(000) 랭킹은 상품의 실제 카테고리를 알려주지 않아 카테고리별로 요청해야 함.
- 2026-09-24: 기간 옵션 `period`: REALTIME(실시간) / DAILY(1일) / WEEKLY(1주) / MONTHLY(1개월).
- 2026-09-24: 남성(M) × 원피스/스커트(100)는 0개 → `SKIP`.
- 2026-09-24: 상품명만으로는 실루엣 35%, 소재 41%만 분류됨 → 상세정보(판매자 입력 핏·제품 소재) 추가. 판매자 절반가량은 핏을 비워 둠.
- 2026-09-24: 짧은 키워드 함정 — '슬리브' 안의 '리브', '티셔츠' 안의 '셔츠', '블루종' 안의 '블루', '올리브' 안의 '리브'. 정규식으로 막아 둠.
- 2026-09-24: 제품 소재 표기는 제각각 ("면100%", "COTTON 79% POLY 21%", "(OUTSHELL) NYLON 100% (LINING)..."). 안감·충전재 앞까지를 겉감으로 봄.
