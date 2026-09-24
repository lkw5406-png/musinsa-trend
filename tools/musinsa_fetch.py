"""무신사 의류 랭킹 수집 Tool.

무신사 웹사이트가 랭킹 화면을 그릴 때 쓰는 공개 데이터 주소(api.musinsa.com)에서
전체 랭킹(최근 1일 기준)을 남성·여성 × 의류 카테고리별로 200위까지 받아 CSV로 저장한다.

- 봇 위장 없음: 정직한 User-Agent, 요청 사이 고정 간격.
- 무신사가 차단(403/429)하면 재시도하지 않고 BlockedError로 멈춘다.

사용법: python tools/musinsa_fetch.py [--date YYYY-MM-DD]
"""
import argparse
import csv
import sys
import time
import urllib.parse

from common import HISTORY_DIR, get_json, today_kst

BASE_URL = "https://api.musinsa.com/api2/hm/web/v5/pans/ranking/sections/{section}"
REQUEST_INTERVAL_SEC = 4
MAX_RANK = 200
MAX_PAGES = 3  # 1페이지 ≈ 100위. 안전장치.

# 섹션/옵션은 랭킹 화면 설정(pans/ranking?subPan=product)에서 확인함 (2026-09-24)
SECTION = "199"      # 전체 랭킹 (201=급상승, 200=NEW는 쓰지 않음)
PERIOD = "DAILY"     # 최근 1일 (REALTIME=실시간, WEEKLY=1주, MONTHLY=1개월)
GENDERS = {"M": "남성", "F": "여성"}
CLOTHING_CATEGORIES = {"001": "상의", "002": "아우터", "003": "바지", "100": "원피스/스커트"}
SKIP = {("M", "100")}  # 남성 원피스/스커트 랭킹은 비어 있음

CSV_COLUMNS = [
    "date", "period", "gender_filter", "category_code", "category_name", "rank",
    "product_id", "brand", "product_name", "final_price", "original_price",
    "discount_rate", "sales_label", "viewers", "flag", "sold_out", "image_url", "product_url",
]


def build_url(gender: str, category: str, page: int, last_rank: int) -> str:
    params = {
        "storeCode": "musinsa",
        "gf": gender,
        "ageBand": "AGE_BAND_ALL",
        "period": PERIOD,
        "categoryCode": category,
        "contentsId": "",
    }
    if page > 1:
        # 화면이 쓰는 다음 페이지 규칙: offset=직전 마지막 순위, startRank=그 다음 순위
        params.update({"page": page, "offset": last_rank, "startRank": last_rank + 1})
    return BASE_URL.format(section=SECTION) + "?" + urllib.parse.urlencode(params)


def parse_products(data: dict) -> list[dict]:
    products = []
    for module in data.get("data", {}).get("modules", []):
        for item in module.get("items", []) or []:
            if item.get("type") != "PRODUCT_COLUMN":
                continue
            info = item.get("info", {}) or {}
            image = item.get("image", {}) or {}
            ga4 = ((item.get("impressionEventLog") or {}).get("ga4") or {}).get("payload") or {}
            rank = image.get("rank")
            if rank is None:
                continue
            extra = [x.get("text", "") for x in info.get("additionalInformation", []) or []]
            labels = [x.get("text", "") for x in image.get("labels", []) or []]
            products.append({
                "rank": int(rank),
                "product_id": str(item.get("id", "")),
                "brand": info.get("brandName", ""),
                "product_name": info.get("productName", ""),
                "final_price": info.get("finalPrice", ""),
                "original_price": ga4.get("original_price", ""),
                "discount_rate": info.get("discountRatio", ""),
                "sales_label": " / ".join(t for t in labels if t),
                "viewers": " / ".join(t for t in extra if t),
                "flag": ga4.get("item_flag", ""),
                "sold_out": info.get("isSoldOut", False),
                "image_url": image.get("url", ""),
                "product_url": (item.get("onClick") or {}).get("url", ""),
            })
    return products


def fetch_ranking(gender: str, category: str) -> list[dict]:
    by_rank: dict[int, dict] = {}
    last_rank = 0
    for page in range(1, MAX_PAGES + 1):
        data = get_json(build_url(gender, category, page, last_rank))
        time.sleep(REQUEST_INTERVAL_SEC)
        products = parse_products(data)
        if not products:
            break
        for p in products:
            by_rank.setdefault(p["rank"], p)
        new_last = max(p["rank"] for p in products)
        if new_last >= MAX_RANK or new_last <= last_rank:
            break
        last_rank = new_last
    return [by_rank[r] for r in sorted(by_rank) if r <= MAX_RANK]


def collect(date: str) -> list[dict]:
    rows = []
    for gender in GENDERS:
        for cat_code, cat_name in CLOTHING_CATEGORIES.items():
            if (gender, cat_code) in SKIP:
                continue
            products = fetch_ranking(gender, cat_code)
            print(f"  {gender} {cat_name:8} → {len(products)}개", flush=True)
            for p in products:
                rows.append({"date": date, "period": PERIOD, "gender_filter": gender,
                             "category_code": cat_code, "category_name": cat_name, **p})
    return rows


def validate(rows: list[dict]) -> None:
    """무신사 데이터 구조가 바뀌어 조용히 빈 결과가 나오는 걸 막는다."""
    expected_lists = len(GENDERS) * len(CLOTHING_CATEGORIES) - len(SKIP)
    counts: dict[tuple, int] = {}
    for r in rows:
        key = (r["gender_filter"], r["category_code"])
        counts[key] = counts.get(key, 0) + 1
    thin = [k for k, n in counts.items() if n < 50]
    if len(counts) < expected_lists or thin:
        raise RuntimeError(
            f"수집 결과가 비정상적으로 적음 (목록 {len(counts)}/{expected_lists}개, 50개 미만: {thin}). "
            "무신사 데이터 구조가 바뀌었을 수 있음 — workflows/musinsa_daily_report.md의 '구조 변경' 항목 참고."
        )


def save_csv(rows: list[dict], date: str):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / f"{date}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_kst())
    args = parser.parse_args()

    print(f"무신사 랭킹 수집 시작 ({args.date}, 최근 1일 기준)")
    rows = collect(args.date)
    validate(rows)
    path = save_csv(rows, args.date)
    print(f"저장 완료: {path} ({len(rows)}행)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
