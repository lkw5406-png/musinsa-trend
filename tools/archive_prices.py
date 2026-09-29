"""월간 랭킹 아카이브 상품의 정가 수집 Tool.

랭킹 아카이브에는 가격이 없어서, 상품 상세 데이터(goods-detail.musinsa.com)의 정가(goodsPrice.normalPrice)를
상품마다 한 번씩 받아 data/archive_prices.json에 쌓는다. (2026-09-29 사장님 요청: 순위 찾아보기에 정가)

- 기준: **조회한 날의 정가** (지난 달 당시 가격은 무신사가 제공하지 않음). 받은 날짜를 함께 적는다.
- 순서: 대분류 TOP 30에 든 상품 먼저(페이지 기본 화면), 그다음 세부 카테고리에만 있던 상품.
- 이어받기: 받은 상품은 다시 요청하지 않는다. 50개마다 저장하므로 PC가 꺼져도 다음에 이어서 받는다.
- 못 받은 상품(없어진 상품 등)은 정가 없음(null)으로 적어 다시 요청하지 않는다.
- 요청 전에 매일 수집 CSV(data/history*)의 original_price로 먼저 채워 요청을 줄인다.
- 전체 약 2.6만 개 · 요청 간격 1.5초 → 약 12~13시간.

사용법: python tools/archive_prices.py [--limit N] [--top-only]
"""
import argparse
import csv
import json
import sys
import time

from common import ROOT, BlockedError, get_json, today_kst

ARCHIVE_DIR = ROOT / "data" / "archive_monthly"
PRICES_PATH = ROOT / "data" / "archive_prices.json"
DETAIL_URL = "https://goods-detail.musinsa.com/api2/goods/{id}"
REQUEST_INTERVAL_SEC = 1.5
SAVE_EVERY = 50


def load_prices() -> dict:
    return json.loads(PRICES_PATH.read_text(encoding="utf-8")) if PRICES_PATH.exists() else {}


def save_prices(prices: dict) -> None:
    PRICES_PATH.write_text(json.dumps(prices, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def archive_products() -> tuple[list[str], list[str]]:
    """(대분류 TOP 30 상품, 세부 카테고리에만 있던 상품) — 각각 순서 유지, 중복 없음"""
    top, sub = {}, {}
    for path in sorted(ARCHIVE_DIR.glob("*.csv")):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                (sub if r["parent_code"] else top).setdefault(r["product_id"], True)
    return list(top), [pid for pid in sub if pid not in top]


def seed_from_history(prices: dict, wanted: set[str]) -> int:
    """매일 수집 CSV에 이미 있는 정가로 먼저 채움 (가장 최근 날짜 값)."""
    added = 0
    for path in sorted(ROOT.glob("data/history*/*.csv")):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                pid, price = r.get("product_id"), (r.get("original_price") or "").replace(",", "")
                if pid in wanted and pid not in prices and price.isdigit():
                    prices[pid] = {"normal": int(price), "at": path.stem}
                    added += 1
    return added


def fetch_normal_price(pid: str) -> int | None:
    data = get_json(DETAIL_URL.format(id=pid), allow_404=True)
    price = (((data or {}).get("data") or {}).get("goodsPrice") or {}).get("normalPrice")
    return int(price) if isinstance(price, (int, float)) and price > 0 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="이번에 요청할 최대 상품 수 (시험용)")
    parser.add_argument("--top-only", action="store_true", help="대분류 TOP 30 상품만")
    args = parser.parse_args()

    top, sub = archive_products()
    order = top if args.top_only else top + sub
    prices = load_prices()
    seeded = seed_from_history(prices, set(order))
    if seeded:
        save_prices(prices)
    todo = [pid for pid in order if pid not in prices]
    have = len(order) - len(todo)
    if args.limit:
        todo = todo[: args.limit]
    print(f"정가 수집: 대상 {len(order)}개 (대분류 TOP 30 {len(top)}개 먼저) · 이미 있음 {have}개"
          f"(매일 수집분에서 {seeded}개) · 이번에 {len(todo)}개 · 약 {len(todo) * 1.8 / 3600:.1f}시간", flush=True)

    today = today_kst()
    top_set = set(top)
    for i, pid in enumerate(todo, 1):
        try:
            prices[pid] = {"normal": fetch_normal_price(pid), "at": today}
        except BlockedError as e:
            save_prices(prices)
            print(f"멈춤: {e}", flush=True)
            return 2
        except Exception as e:  # 일시적 오류는 건너뛰고 다음에 다시 시도 (저장 안 함)
            print(f"  {pid} 건너뜀: {e}", flush=True)
        if i % SAVE_EVERY == 0 or i == len(todo):
            save_prices(prices)
            done_top = sum(1 for p in top if p in prices)
            print(f"  {i}/{len(todo)} 저장 · 대분류 TOP 30 {done_top}/{len(top)}", flush=True)
        if pid in top_set and all(p in prices for p in top) and i < len(todo) and todo[i] not in top_set:
            print("대분류 TOP 30 상품 정가 다 받음", flush=True)
        time.sleep(REQUEST_INTERVAL_SEC)
    print("끝", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
