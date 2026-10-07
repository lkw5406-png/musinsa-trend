"""무신사 월간 랭킹 아카이브 분석 Tool.

data/archive_monthly/YYYY-MM.csv (musinsa_archive.py) 전부를 읽어 .tmp/archive_analysis.json 하나로 정리한다.

- 기준 순위: 대분류(상의·아우터·바지·원피스/스커트) TOP 30. 세부 카테고리 순위는 '이 상품이 어느 세부 종류인지'와
  세부 카테고리별 목록 보기에 쓴다.
- 꾸준템: 대분류 TOP 30에 든 달 수, 최장 연속 달 수, 최고 순위
- 시즌템: 대분류 TOP 30 안의 세부 종류 구성(달마다 몇 개) + 달력 월(1~12월) 평균 → 매년 반복되는지
- 월별 변화: 신규 진입(처음 등장) · 재진입 · 순위 급상승 → Claude가 원인 조사할 후보 (notable)
- 품목 통합 전체 랭킹(data/archive_overall)은 의류만 남겨 순위 찾아보기 목록에만 쓴다 (overall).
  의류 = 의류 카테고리 순위(archive_monthly)에 한 번이라도 나온 상품. 신발·가방·양말·뷰티 등은 빠지고,
  순위 숫자는 무신사 전체 순위 그대로 둔다(그래서 중간이 빈다). 꾸준템·시즌·브랜드 분석에는 넣지 않는다.
  (2026-10-07 사장님 결정: 의류만, 순위와 아이템만 보이게)
- 상품명 키워드: 핏·실루엣·원단·디테일·컬러 (tools/attribute_keywords.json 재사용)

사용법: python tools/analyze_archive.py
"""
import csv
import json
import sys
from collections import Counter, defaultdict

import classify_attributes
from common import ROOT, TMP_DIR

ARCHIVE_DIR = ROOT / "data" / "archive_monthly"
OVERALL_DIR = ROOT / "data" / "archive_overall"
OUT_PATH = TMP_DIR / "archive_analysis.json"
TOP_CATS = {"001": "상의", "002": "아우터", "003": "바지", "100": "원피스/스커트"}
GENDERS = {"A": "전체", "M": "남성", "F": "여성"}
KEYWORD_GROUPS = ("fit", "silhouette", "texture", "detail", "color")
NOTABLE_PER_MONTH = 12  # 성별마다 달마다 원인 조사 후보 수


def load_rows(folder=ARCHIVE_DIR) -> tuple[list[str], list[dict]]:
    months, rows = [], []
    for path in sorted(folder.glob("*.csv")):
        months.append(path.stem)
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                r["rank"] = int(r["rank"])
                rows.append(r)
    return months, rows


def product_table(rows: list[dict]) -> dict:
    """상품번호 → 이름·브랜드·사진·대분류·세부 종류. 세부 종류는 세부 카테고리 순위에 가장 많이 나온 것."""
    products, subs = {}, defaultdict(Counter)
    for r in rows:
        pid = r["product_id"]
        p = products.setdefault(pid, {"id": pid, "name": r["product_name"], "brand": r["brand_name"],
                                      "brand_id": r["brand"], "image": r["image_url"], "cat": "", "sub": ""})
        p["discontinued"] = r["discontinued"] == "True"
        if r["parent_code"]:
            subs[pid][r["category_name"]] += 1
            p["cat"] = p["cat"] or r["parent_code"]
        else:
            p["cat"] = r["category_code"]
    for pid, p in products.items():
        p["sub"] = subs[pid].most_common(1)[0][0] if subs[pid] else "기타"
        # 디자인 키워드 (상품명 기준) — 시즌 추천 카드에서 세부 종류별로 모아 보여 줌
        tags = {g: classify_attributes.keywords(p["name"], g) for g in KEYWORD_GROUPS}
        p["tags"] = {g: v for g, v in tags.items() if v}
    return products


def ranking_tables(rows: list[dict]) -> dict:
    """(성별, 카테고리 코드) → 달 → [상품번호 순위순]"""
    table = defaultdict(lambda: defaultdict(list))
    for r in sorted(rows, key=lambda r: r["rank"]):
        table[(r["gender"], r["category_code"])][r["year_month"]].append(r["product_id"])
    return table


def item_history(months: list[str], table: dict, gender: str) -> dict:
    """상품번호 → {달: 대분류 순위}"""
    hist = defaultdict(dict)
    for cat in TOP_CATS:
        for ym, ids in table[(gender, cat)].items():
            for i, pid in enumerate(ids, 1):
                hist[pid][ym] = i
    return hist


def longest_streak(months: list[str], present: set[str]) -> int:
    best = run = 0
    for ym in months:
        run = run + 1 if ym in present else 0
        best = max(best, run)
    return best


def persistent(months: list[str], hist: dict, products: dict, limit: int = 40) -> list[dict]:
    items = []
    for pid, ranks in hist.items():
        present = set(ranks)
        items.append({
            "id": pid, "months": len(present), "streak": longest_streak(months, present),
            "best": min(ranks.values()), "avg": round(sum(ranks.values()) / len(ranks), 1),
            "first": min(present), "last": max(present), "cat": products[pid]["cat"],
            "ranks": [ranks.get(ym) for ym in months],
        })
    items.sort(key=lambda x: (-x["months"], x["avg"]))
    return items[:limit]


def composition(months: list[str], table: dict, gender: str, products: dict) -> dict:
    """대분류 → 세부 종류 → 달마다 TOP 30 안 개수, 그리고 달력 월 평균"""
    out = {}
    for cat in TOP_CATS:
        per = defaultdict(lambda: [0] * len(months))
        for mi, ym in enumerate(months):
            for pid in table[(gender, cat)].get(ym, []):
                per[products[pid]["sub"]][mi] += 1
        cal = {}
        for sub, counts in per.items():
            by_cal = defaultdict(list)
            for ym, n in zip(months, counts):
                by_cal[int(ym[5:])].append(n)
            cal[sub] = [round(sum(by_cal[m]) / len(by_cal[m]), 1) if by_cal[m] else None for m in range(1, 13)]
        out[cat] = {"by_month": dict(per), "calendar": cal}
    return out


def keyword_trends(months: list[str], table: dict, gender: str, products: dict) -> dict:
    """키워드 그룹 → 이름 → 달마다 대분류 TOP 30 합계(남성 90·전체·여성 120) 중 비율(%)"""
    out = {g: defaultdict(lambda: [0.0] * len(months)) for g in KEYWORD_GROUPS}
    for mi, ym in enumerate(months):
        ids = [pid for cat in TOP_CATS for pid in table[(gender, cat)].get(ym, [])]
        if not ids:
            continue
        for group in KEYWORD_GROUPS:
            counts = Counter(k for pid in ids for k in set(classify_attributes.keywords(products[pid]["name"], group)))
            for k, n in counts.items():
                out[group][k][mi] = round(n * 100 / len(ids), 1)
    # 한 번이라도 5% 넘은 것만
    return {g: {k: v for k, v in d.items() if max(v) >= 5} for g, d in out.items()}


def brand_trends(months: list[str], hist: dict, products: dict, limit: int = 80) -> list[dict]:
    per = defaultdict(lambda: [0] * len(months))
    for pid, ranks in hist.items():
        for mi, ym in enumerate(months):
            if ym in ranks:
                per[products[pid]["brand"]][mi] += 1
    ranked = sorted(per.items(), key=lambda kv: -sum(kv[1]))[:limit]
    return [{"brand": b, "counts": c, "total": sum(c)} for b, c in ranked]


def notable(months: list[str], hist: dict, gender: str) -> dict:
    """달 → 원인 조사 후보: 처음 등장해 높은 순위 / 재진입 / 크게 오름"""
    out = {}
    for mi, ym in enumerate(months):
        prev = months[mi - 1] if mi else None
        cands = []
        for pid, ranks in hist.items():
            if ym not in ranks:
                continue
            r = ranks[ym]
            seen_before = any(m < ym for m in ranks)
            if prev is None:
                kind, score = "기존", 0
            elif not seen_before:
                kind, score = "신규 진입", 40 - r
            elif prev not in ranks:
                kind, score = "재진입", 30 - r
            elif ranks[prev] - r >= 10:
                kind, score = "급상승", ranks[prev] - r
            else:
                continue
            if score > 0:
                cands.append({"id": pid, "kind": kind, "rank": r, "prev": ranks.get(prev) if prev else None,
                              "score": score})
        cands.sort(key=lambda c: -c["score"])
        out[ym] = cands[:NOTABLE_PER_MONTH]
    return out


def monthly_top(months: list[str], table: dict, gender: str, n: int = 30) -> dict:
    """카테고리 코드(대분류·세부) → 달 → 상위 n 상품번호"""
    out = defaultdict(dict)
    for (g, cat), per in table.items():
        if g != gender:
            continue
        for ym, ids in per.items():
            out[cat][ym] = ids[:n]
    return dict(out)


def overall_apparel(months: list[str], products: dict, gender: str) -> dict:
    """달 → [[무신사 전체 순위, 상품번호]] — 품목 통합 전체 랭킹 TOP 30 중 의류만"""
    _, rows = load_rows(OVERALL_DIR)
    out = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["rank"]):
        if r["gender"] == gender and r["year_month"] in months and r["product_id"] in products:
            out[r["year_month"]].append([r["rank"], r["product_id"]])
    return dict(out)


def analyze() -> dict:
    months, rows = load_rows()
    if not months:
        raise FileNotFoundError(f"{ARCHIVE_DIR}에 CSV가 없음 — 먼저 python tools/musinsa_archive.py")
    products = product_table(rows)
    table = ranking_tables(rows)
    categories = {}
    for r in rows:
        categories.setdefault(r["category_code"], {"name": r["category_name"], "parent": r["parent_code"]})
    result = {"months": months, "categories": categories, "products": products, "genders": {}}
    for g in GENDERS:
        hist = item_history(months, table, g)
        result["genders"][g] = {
            "persistent": persistent(months, hist, products),
            "composition": composition(months, table, g, products),
            "keywords": keyword_trends(months, table, g, products),
            "brands": brand_trends(months, hist, products),
            "notable": notable(months, hist, g),
            "top": monthly_top(months, table, g),
            "overall": overall_apparel(months, products, g),
        }
    return result


def main() -> int:
    result = analyze()
    TMP_DIR.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"분석 저장: {OUT_PATH} ({len(result['months'])}개월, 상품 {len(result['products'])}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
