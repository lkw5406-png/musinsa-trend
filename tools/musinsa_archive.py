"""무신사 월간 랭킹 아카이브 수집 Tool.

무신사 '랭킹 아카이브' 화면(www.musinsa.com/ranking/archive)이 쓰는 공개 데이터 주소에서
월·성별·카테고리마다 TOP 30을 받아 한 달에 CSV 하나로 저장한다: data/archive_monthly/YYYY-MM.csv

- 의류만: 상의 001, 아우터 002, 바지 003, 원피스/스커트 100 + 그 아래 세부 카테고리 전부
  (2026-09-28 사장님 결정: 대분류 + 세부, 전체·남성·여성, 2024-01부터. 가방·모자는 넣었다가 같은 날 뺌)
- 세부 카테고리 목록은 달·성별마다 무신사가 알려주는 목록(categories)을 그대로 따른다.
- 지난 달 순위는 바뀌지 않으므로 이미 저장된 달은 건너뛴다 (--force로 다시 받기).
- 봇 위장 없음: 정직한 User-Agent, 요청 사이 고정 간격. 차단(401/403/429)되면 바로 멈춘다.

사용법: python tools/musinsa_archive.py [--from 2024-01] [--to 2026-08] [--force]
"""
import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from common import KST, ROOT, USER_AGENT, BlockedError

API = "https://api.musinsa.com/api2/dp/v1/ranking-archive/{kind}"
ARCHIVE_DIR = ROOT / "data" / "archive_monthly"
REQUEST_INTERVAL_SEC = 1.5
FIRST_MONTH = "2024-01"  # 아카이브 시작 (2026-09-28 확인: 2023-12 이전은 '정보가 존재하지 않습니다')

GENDERS = {"A": "전체", "M": "남성", "F": "여성"}
TARGET_CATEGORIES = {"001": "상의", "002": "아우터", "003": "바지", "100": "원피스/스커트"}

CSV_COLUMNS = [
    "year_month", "gender", "category_code", "category_name", "parent_code", "parent_name",
    "rank", "product_id", "brand", "brand_name", "product_name", "image_url", "discontinued",
]


def request(kind: str, params: dict) -> dict | None:
    """아카이브 요청. 무신사가 '해당 달 정보 없음'이라고 답하면 None."""
    url = API.format(kind=kind) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise BlockedError(f"HTTP {e.code} — 무신사가 요청을 거부함: {url}") from e
            try:
                body = json.loads(e.read().decode("utf-8"))
                break
            except (ValueError, OSError):
                if attempt == 2:
                    raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(30)
    time.sleep(REQUEST_INTERVAL_SEC)
    meta = body.get("meta") or {}
    if meta.get("result") == "FAIL":
        if meta.get("errorCode") == "DISPLAY_000_0002":  # 그 달·카테고리 랭킹 없음
            return None
        raise RuntimeError(f"무신사 오류 {meta} — {url}")
    return body.get("data")


def month_range(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    months = []
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def last_finished_month() -> str:
    now = datetime.now(KST)
    y, m = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    return f"{y:04d}-{m:02d}"


def target_categories(ym: str, gender: str) -> list[tuple[str, str, str, str]]:
    """(카테고리 코드, 이름, 대분류 코드, 대분류 이름) — 대분류 먼저, 그 아래 세부."""
    data = request("categories", {"yearMonth": ym.replace("-", ""), "gf": gender}) or {}
    cats = []
    for top in data.get("list", []) or []:
        code = top.get("categoryCode", "")
        if code not in TARGET_CATEGORIES:
            continue
        name = top.get("categoryTitle", "") or TARGET_CATEGORIES[code]
        cats.append((code, name, "", ""))
        for sub in top.get("categoryList", []) or []:
            cats.append((sub.get("categoryCode", ""), sub.get("categoryTitle", ""), code, name))
    if not cats:  # 목록을 못 받으면 대분류만이라도
        cats = [(c, n, "", "") for c, n in TARGET_CATEGORIES.items()]
    return cats


def collect_month(ym: str) -> list[dict]:
    rows = []
    for gender in GENDERS:
        for code, name, parent, parent_name in target_categories(ym, gender):
            data = request("goods", {"yearMonth": ym.replace("-", ""), "gf": gender, "category": code})
            for item in (data or {}).get("list", []) or []:
                rows.append({
                    "year_month": ym, "gender": gender,
                    "category_code": code, "category_name": name,
                    "parent_code": parent, "parent_name": parent_name,
                    "rank": item.get("rank"), "product_id": item.get("goodsNo"),
                    "brand": item.get("brand", ""), "brand_name": item.get("brandName", ""),
                    "product_name": item.get("goodsName", ""), "image_url": item.get("imageUrl", ""),
                    "discontinued": item.get("isPermanentStopped", False),
                })
        print(f"  {ym} {GENDERS[gender]}: 누적 {len(rows)}행")
    return rows


def save_csv(rows: list[dict], ym: str):
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE_DIR / f"{ym}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", default=FIRST_MONTH)
    parser.add_argument("--to", dest="end", default=last_finished_month())
    parser.add_argument("--force", action="store_true", help="이미 저장된 달도 다시 받기")
    args = parser.parse_args()

    for ym in month_range(args.start, args.end):
        path = ARCHIVE_DIR / f"{ym}.csv"
        if path.exists() and not args.force:
            print(f"{ym}: 이미 있음 — 건너뜀")
            continue
        print(f"{ym}: 수집 시작")
        rows = collect_month(ym)
        tops = sum(1 for r in rows if not r["parent_code"])
        if tops < 200:  # 대분류 4개 × 3성별 × 30 = 360 근처가 정상
            print(f"{ym}: 대분류 순위가 {tops}행뿐 — 아직 집계 전이거나 구조 변경. 저장 안 함")
            continue
        print(f"{ym}: 저장 {save_csv(rows, ym)} ({len(rows)}행)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
