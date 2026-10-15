"""월간 랭킹에 든 그해 신상품 찾기 Tool.

월간 랭킹 아카이브(data/archive_monthly)에서, 그해에 새로 등록된 상품 중 랭킹(대분류·세부 카테고리 TOP 30)에 든 것을
달·카테고리별로 모은다. (2026-10-15 사장님 요청: "기존 후기를 쌓아오던 제품 말고 2026년 신상으로 출시해서 랭크에 들어간 제품")

- 등록일 = 무신사 상품 사진 주소의 날짜(goods_img/YYYYMMDD 또는 prd_img/YYYYMMDD). 상품번호 순서와 맞는 것을 확인함
  (2026-10-15: 2026년 날짜 상품은 전부 5,865,000번 이후, 2025년 이전 날짜 상품 중 그 번호를 넘는 것 없음).
- 기본: 남성(M), 2026-01-01 이후 등록, 스포츠·아웃도어 브랜드와 운동복 제외(data/plan_items_27ss.json, 상품 기획 분석과 같은 기준).
- 정가는 data/archive_prices.json (tools/archive_prices.py --ids로 이 목록부터 받음).
- 결과: .tmp/new_releases_<연도>.json (페이지용), .tmp/new_releases_<연도>_ids.txt (정가 받을 목록)

사용법: python tools/new_releases.py [--year 2026] [--gender M]
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict

from common import ROOT, TMP_DIR

ARCHIVE_DIR = ROOT / "data" / "archive_monthly"
PRICES_PATH = ROOT / "data" / "archive_prices.json"
SPEC_PATH = ROOT / "data" / "plan_items_27ss.json"
TOP_CATS = {"001": "상의", "002": "아우터", "003": "바지", "100": "원피스/스커트"}
DATE_RE = re.compile(r"/(?:goods_img|prd_img)/(\d{8})/")


def reg_date(image_url: str) -> str | None:
    m = DATE_RE.search(image_url)
    return f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else None


def collect(year: str, gender: str) -> dict:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    ex_brands = set(spec.get("exclude_brands", []))
    ex_name = re.compile(spec["exclude_name"], re.I) if spec.get("exclude_name") else None
    prices = json.loads(PRICES_PATH.read_text(encoding="utf-8")) if PRICES_PATH.exists() else {}

    products, ranks, subs = {}, defaultdict(lambda: defaultdict(dict)), defaultdict(Counter)
    months, excluded = [], set()
    for path in sorted(ARCHIVE_DIR.glob(f"{year}-*.csv")):
        months.append(path.stem)
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r["gender"] != gender:
                    continue
                d = reg_date(r["image_url"])
                if not d or not d.startswith(year):
                    continue
                pid = r["product_id"]
                if r["brand"] in ex_brands or (ex_name and ex_name.search(r["product_name"])):
                    excluded.add(pid)
                    continue
                products.setdefault(pid, {"id": pid, "brand": r["brand_name"], "name": r["product_name"],
                                          "image": r["image_url"], "reg": d, "cat": ""})
                products[pid]["discontinued"] = r["discontinued"] == "True"
                ym = r["year_month"]
                if r["parent_code"]:  # 세부 카테고리 순위
                    subs[pid][r["category_name"]] += 1
                    products[pid]["cat"] = products[pid]["cat"] or r["parent_code"]
                    ranks[pid][ym].setdefault("sub", {})[r["category_name"]] = int(r["rank"])
                else:  # 대분류 순위
                    products[pid]["cat"] = r["category_code"]
                    ranks[pid][ym]["top"] = int(r["rank"])

    for pid, p in products.items():
        p["sub"] = subs[pid].most_common(1)[0][0] if subs[pid] else "기타"
        p["ranks"] = {ym: dict(v) for ym, v in sorted(ranks[pid].items())}
        p["first"] = min(p["ranks"])
        p["price"] = (prices.get(pid) or {}).get("normal")
    return {"year": year, "gender": gender, "months": months, "cats": TOP_CATS,
            "excluded_sports": len(excluded), "products": products}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2026")
    ap.add_argument("--gender", default="M")
    args = ap.parse_args()
    out = collect(args.year, args.gender)
    TMP_DIR.mkdir(exist_ok=True)
    path = TMP_DIR / f"new_releases_{args.year}.json"
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    ids = sorted(out["products"], key=lambda pid: out["products"][pid]["first"])
    (TMP_DIR / f"new_releases_{args.year}_ids.txt").write_text("\n".join(ids), encoding="utf-8")
    ps = out["products"].values()
    print(f"{args.year} 신상 (성별 {args.gender}, {out['months'][0]}~{out['months'][-1]}): {len(ids)}개 · "
          f"정가 있음 {sum(1 for p in ps if p['price'])}개 · 스포츠 제외 {out['excluded_sports']}개 → {path}")
    print("첫 진입 달별:", dict(sorted(Counter(p["first"] for p in ps).items())))
    print("대분류별:", dict(Counter(TOP_CATS.get(p["cat"], p["cat"]) for p in ps)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
