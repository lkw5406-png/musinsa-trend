"""무신사 의류 랭킹 수집 Tool.

무신사 웹사이트가 랭킹 화면을 그릴 때 쓰는 공개 데이터 주소(api.musinsa.com)에서
남성·여성 전체 랭킹(최근 1일)을 1위부터 내려가며, 의류만 골라 성별마다 300개를 모아 CSV로 저장한다.

- 전체 랭킹에는 상품의 카테고리 표시가 없어(모두 '000') 상품 상세정보로 의류인지 판별한다.
  한 번 본 상품은 data/product_details.json에 남아 다시 요청하지 않는다.
- 봇 위장 없음: 정직한 User-Agent, 요청 사이 고정 간격.
- 무신사가 차단(403/429)하면 재시도하지 않고 BlockedError로 멈춘다.

사용법: python tools/musinsa_fetch.py [--date YYYY-MM-DD]
"""
import argparse
import csv
import sys
import time
import urllib.parse

import product_details
from common import HISTORY_DIR, get_json, today_kst

BASE_URL = "https://api.musinsa.com/api2/hm/web/v5/pans/ranking/sections/{section}"
REQUEST_INTERVAL_SEC = 4
CLOTHING_TARGET = 300  # 성별마다 의류 300개 (2026-09-25 사장님 결정: 전체 랭킹에서 의류만 300개 채우기)
MAX_PAGES = 12         # 1페이지 ≈ 100위. 의류 300개가 안 차도 1,200위 근처에서 멈추는 안전장치
MIN_CLOTHING = 200     # 이보다 적게 모이면 구조 변경을 의심하고 멈춤

# 섹션/옵션은 랭킹 화면 설정(pans/ranking?subPan=product)에서 확인함 (2026-09-24)
SECTION = "199"      # 전체 랭킹 (201=급상승, 200=NEW는 쓰지 않음)
CATEGORY = "000"     # 전체 카테고리
PERIOD = "DAILY"     # 최근 1일 (REALTIME=실시간, WEEKLY=1주, MONTHLY=1개월)
GENDERS = {"M": "남성", "F": "여성"}
CLOTHING_CATEGORIES = {"001": "상의", "002": "아우터", "003": "바지", "100": "원피스/스커트"}

CSV_COLUMNS = [
    "date", "period", "gender_filter", "rank", "clothing_rank", "category_code", "category_name",
    "product_id", "brand", "product_name", "final_price", "original_price",
    "discount_rate", "sales_label", "viewers", "flag", "sold_out", "image_url", "product_url",
]


def build_url(gender: str, page: int, last_rank: int) -> str:
    params = {
        "storeCode": "musinsa",
        "gf": gender,
        "ageBand": "AGE_BAND_ALL",
        "period": PERIOD,
        "categoryCode": CATEGORY,
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


def fetch_gender(gender: str, date: str, details: dict) -> list[dict]:
    """전체 랭킹을 한 페이지씩 받아, 의류가 CLOTHING_TARGET개 모일 때까지 내려간다."""
    rows: list[dict] = []
    seen_ranks: set[int] = set()
    last_rank = 0
    for page in range(1, MAX_PAGES + 1):
        data = get_json(build_url(gender, page, last_rank))
        time.sleep(REQUEST_INTERVAL_SEC)
        products = [p for p in parse_products(data) if p["rank"] not in seen_ranks]
        if not products:
            break
        seen_ranks.update(p["rank"] for p in products)
        products.sort(key=lambda p: p["rank"])

        new = product_details.ensure_details([p["product_id"] for p in products], details, date)
        for p in products:
            detail = details.get(p["product_id"])
            if not product_details.is_clothing(detail):
                continue
            code = product_details.category1(detail)
            rows.append({"date": date, "period": PERIOD, "gender_filter": gender,
                         "clothing_rank": len(rows) + 1, "category_code": code,
                         "category_name": CLOTHING_CATEGORIES[code], **p})
            if len(rows) >= CLOTHING_TARGET:
                break
        print(f"  {GENDERS[gender]} {page}페이지(~{max(seen_ranks)}위): 의류 {len(rows)}개 (새 상세정보 {new}개)", flush=True)
        if len(rows) >= CLOTHING_TARGET:
            break
        new_last = max(p["rank"] for p in products)
        if new_last <= last_rank:
            break
        last_rank = new_last
    return rows


def collect(date: str) -> list[dict]:
    details = product_details.load_details()
    rows = []
    for gender in GENDERS:
        rows += fetch_gender(gender, date, details)
    return rows


def validate(rows: list[dict]) -> None:
    """무신사 데이터 구조가 바뀌어 조용히 빈 결과가 나오는 걸 막는다."""
    counts = {g: sum(1 for r in rows if r["gender_filter"] == g) for g in GENDERS}
    thin = {GENDERS[g]: n for g, n in counts.items() if n < MIN_CLOTHING}
    if thin:
        raise RuntimeError(
            f"의류가 비정상적으로 적게 모임 {thin} (기준 {MIN_CLOTHING}개). "
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

    print(f"무신사 랭킹 수집 시작 ({args.date}, 전체 랭킹 최근 1일 · 성별 의류 {CLOTHING_TARGET}개)")
    rows = collect(args.date)
    validate(rows)
    path = save_csv(rows, args.date)
    print(f"저장 완료: {path} ({len(rows)}행)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
