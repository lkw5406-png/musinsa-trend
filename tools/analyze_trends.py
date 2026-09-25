"""랭킹 트렌드 분석 Tool.

입력: data/history/*.csv (musinsa_fetch.py), data/product_details.json (product_details.py)
출력: .tmp/analysis_YYYY-MM-DD.json (build_report.py가 읽음)

분석 기준
- 성별: 무신사 남성 랭킹 / 여성 랭킹 그대로. (두 랭킹에 모두 오른 상품은 양쪽에 다 반영)
- 비중(share): 순위가 높을수록 큰 가중치(1위=1.0, 300위≈0)로 속성별 비중을 계산.
- 추세: 오늘 비중 − 어제 비중(%p), 오늘 비중 − 최근 7일 평균(%p). 기록이 쌓이면 표시.
  첫날은 추세 없이 '많이 팔리는 속성'만 보여준다.

사용법: python tools/analyze_trends.py [--date YYYY-MM-DD]
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from classify_attributes import GROUP_LABELS, GROUPS, classify
from common import DETAILS_PATH, HISTORY_DIR, TMP_DIR, today_kst

MAX_RANK = 300  # musinsa_fetch.py와 같게
GENDERS = {"M": "남성", "F": "여성"}
HEADLINE_GROUPS = ["item_type", "fit", "silhouette", "fiber", "color"]
MIN_COUNT = 5          # 이보다 적게 등장한 속성은 우연일 수 있어 순위표에서 뺌
TREND_WINDOW_DAYS = 7
MIN_WEEK_DAYS = 3      # 7일 평균 비교는 지난 기록이 3일 이상일 때부터
RECOMMEND_PER_GENDER = 5


def load_day(date: str) -> list[dict] | None:
    path = HISTORY_DIR / f"{date}.csv"
    if not path.exists():
        return None
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_details() -> dict:
    return json.loads(DETAILS_PATH.read_text(encoding="utf-8")) if DETAILS_PATH.exists() else {}


def build_products(rows: list[dict], details: dict) -> dict[str, list[dict]]:
    """{성별: [상품...]}. 상품 하나 = 성별 랭킹·카테고리별 한 줄."""
    out: dict[str, list[dict]] = {g: [] for g in GENDERS.values()}
    for r in rows:
        gender = GENDERS.get(r["gender_filter"])
        if not gender:
            continue
        p = {k: r[k] for k in ("product_id", "brand", "product_name", "category_code", "category_name",
                               "final_price", "original_price", "discount_rate", "sales_label",
                               "image_url", "product_url")}
        p["rank"] = int(r["rank"])  # 무신사 전체 랭킹 순위 (비의류 포함 순위)
        p["clothing_rank"] = int(r.get("clothing_rank") or r["rank"])  # 의류끼리 순위 1~300
        p["weight"] = (MAX_RANK + 1 - p["clothing_rank"]) / MAX_RANK
        p.update(classify(r["product_name"], r["category_code"], r["category_name"], details.get(r["product_id"]),
                          r["product_id"]))
        out[gender].append(p)
    for products in out.values():
        products.sort(key=lambda x: (x["rank"], x["category_code"]))
    return out


def attr_values(p: dict, group: str) -> list[str]:
    v = p[group]
    return [v] if isinstance(v, str) else v


def shares(products: list[dict], group: str) -> dict[str, tuple[float, int]]:
    """{속성: (가중 비중 %, 등장 상품 수)}. 분모는 이 속성이 파악된 상품만 (모르는 상품은 빼고 비교)."""
    known = [p for p in products if attr_values(p, group)]
    total = sum(p["weight"] for p in known) or 1.0
    weight_sum: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    for p in known:
        for v in attr_values(p, group):
            weight_sum[v] += p["weight"]
            count[v] += 1
    return {v: (100 * weight_sum[v] / total, count[v]) for v in weight_sum}


def previous_dates(date: str, days: int) -> list[str]:
    d = datetime.strptime(date, "%Y-%m-%d")
    return [(d - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, days + 1)]


def data_scope(rows: list[dict]) -> str:
    """'overall' = 전체 랭킹에서 의류만 300개 (2026-09-25~), 'category' = 카테고리별 랭킹 (2026-09-24)."""
    return "overall" if rows and "clothing_rank" in rows[0] else "category"


def product_brief(p: dict) -> dict:
    return {k: p[k] for k in ("product_id", "brand", "product_name", "category_name", "item_type", "rank",
                              "clothing_rank", "final_price", "discount_rate", "sales_label", "image_url",
                              "product_url")} | {
        "attrs": [a for g in ("fit", "silhouette", "fiber", "color") for a in attr_values(p, g)]}


CATEGORY_ORDER = ["001", "002", "003", "100"]  # 상의, 아우터, 바지, 원피스/스커트
ITEM_PROFILE_GROUPS = ["silhouette", "texture", "fit", "fiber", "color", "detail"]  # 사장님이 정한 순서
ITEM_PROFILE_MIN = 3        # 이보다 적은 아이템 종류는 따로 정리하지 않음
PRICE_BANDS = [(0, 30000, "3만원 미만"), (30000, 50000, "3~5만원"), (50000, 100000, "5~10만원"),
               (100000, 200000, "10~20만원"), (200000, float("inf"), "20만원 이상")]


def _weight_share(part: list[dict], whole: list[dict]) -> float:
    return 100 * sum(p["weight"] for p in part) / (sum(p["weight"] for p in whole) or 1.0)


def _price(p: dict) -> int | None:
    try:
        return int(float(p["final_price"]))
    except (TypeError, ValueError):
        return None


def _median(values: list[int]) -> int | None:
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) // 2


def top_by_category(products: list[dict], n: int = 10) -> list[dict]:
    """카테고리(상의/아우터/바지/원피스·스커트)별 인기 TOP n."""
    out = []
    for code in CATEGORY_ORDER:
        items = [p for p in products if p["category_code"] == code]
        if items:
            out.append({"code": code, "name": items[0]["category_name"], "count": len(items),
                        "products": [product_brief(p) for p in items[:n]]})
    return out


def category_mix(products: list[dict]) -> list[dict]:
    """카테고리 구성: 상품 수와 순위 가중 비중."""
    out = []
    for code in CATEGORY_ORDER:
        items = [p for p in products if p["category_code"] == code]
        if items:
            out.append({"code": code, "name": items[0]["category_name"], "count": len(items),
                        "share": round(_weight_share(items, products), 1)})
    return out


def item_type_profiles(today: list[dict], yesterday: list[dict] | None) -> list[dict]:
    """아이템 종류(긴소매 티셔츠, 데님 팬츠 …)마다 실루엣·원단·핏·소재·컬러·디테일 구성을 정리."""
    by_type: dict[str, list[dict]] = defaultdict(list)
    for p in today:
        by_type[p["item_type"]].append(p)
    prev_share = {}
    if yesterday:
        prev_by_type: dict[str, list[dict]] = defaultdict(list)
        for p in yesterday:
            prev_by_type[p["item_type"]].append(p)
        prev_share = {t: _weight_share(ps, yesterday) for t, ps in prev_by_type.items()}

    profiles = []
    for item_type, items in by_type.items():
        if len(items) < ITEM_PROFILE_MIN:
            continue
        share = _weight_share(items, today)
        groups = {}
        for group in ITEM_PROFILE_GROUPS:
            s = shares(items, group)
            known = sum(1 for p in items if attr_values(p, group))
            values = sorted(s.items(), key=lambda kv: -kv[1][0])[:4]
            groups[group] = {"coverage": round(100 * known / len(items)),
                             "values": [{"name": v, "pct": round(pct, 1), "count": c} for v, (pct, c) in values]}
        prices = [x for x in (_price(p) for p in items) if x]
        profiles.append({
            "name": item_type,
            "category_code": items[0]["category_code"],
            "category_name": items[0]["category_name"],
            "count": len(items),
            "share": round(share, 1),
            "dod_pp": round(share - prev_share.get(item_type, 0.0), 1) if yesterday else None,
            "median_price": _median(prices),
            "best_rank": min(p["rank"] for p in items),
            "groups": groups,
            "top_products": [product_brief(p) for p in items[:3]],
        })
    profiles.sort(key=lambda x: (CATEGORY_ORDER.index(x["category_code"]) if x["category_code"] in CATEGORY_ORDER else 9,
                                 -x["share"]))
    return profiles


def price_bands(products: list[dict]) -> dict:
    """가격대별 상품 수 (카테고리별로도)."""
    labels = [b[2] for b in PRICE_BANDS]
    rows = []
    for code in CATEGORY_ORDER:
        items = [p for p in products if p["category_code"] == code]
        if not items:
            continue
        counts = [0] * len(PRICE_BANDS)
        for p in items:
            price = _price(p)
            if price is None:
                continue
            for i, (lo, hi, _) in enumerate(PRICE_BANDS):
                if lo <= price < hi:
                    counts[i] += 1
                    break
        prices = [x for x in (_price(p) for p in items) if x]
        rows.append({"name": items[0]["category_name"], "counts": counts, "median": _median(prices)})
    totals = [sum(r["counts"][i] for r in rows) for i in range(len(labels))]
    return {"labels": labels, "rows": rows, "totals": totals}


def analyze_gender(today: list[dict], yesterday: list[dict] | None, history: list[list[dict]]) -> dict:
    has_week = len(history) >= MIN_WEEK_DAYS
    attributes = {}
    trend: dict[tuple[str, str], float] = {}     # 속성별 추세 (7일 대비 우선, 없으면 어제 대비)
    share_today: dict[tuple[str, str], float] = {}
    for group in GROUPS:
        s_today = shares(today, group)
        s_yday = shares(yesterday, group) if yesterday else None
        week = [shares(h, group) for h in history] if has_week else []
        table = []
        for v, (share, cnt) in s_today.items():
            if cnt < MIN_COUNT:
                continue
            entry = {"name": v, "share": round(share, 1), "count": cnt, "dod_pp": None, "week_pp": None}
            if s_yday is not None:
                entry["dod_pp"] = round(share - s_yday.get(v, (0.0, 0))[0], 1)
            if week:
                entry["week_pp"] = round(share - sum(w.get(v, (0.0, 0))[0] for w in week) / len(week), 1)
            t = entry["week_pp"] if entry["week_pp"] is not None else entry["dod_pp"]
            if t is not None:
                trend[(group, v)] = t
            share_today[(group, v)] = share
            table.append(entry)
        table.sort(key=lambda e: -e["share"])
        known = sum(1 for p in today if attr_values(p, group))
        attributes[group] = {"rows": table, "coverage": round(100 * known / max(1, len(today)), 1)}

    has_trend = bool(trend)
    trend_label = "7일 평균 대비" if has_week else "어제 대비"

    # 순위 급등 / 신규 진입 (어제 대비, 같은 카테고리 안에서)
    movers, new_entries = [], []
    prev_rank = {}
    if yesterday:
        prev_rank = {(p["category_code"], p["product_id"]): p["rank"] for p in yesterday}
        for p in today:
            prev = prev_rank.get((p["category_code"], p["product_id"]))
            if prev is None:
                if p["clothing_rank"] <= 50:
                    new_entries.append(product_brief(p))
            elif prev - p["rank"] >= 10:
                movers.append(product_brief(p) | {"prev_rank": prev, "change": prev - p["rank"]})
        movers.sort(key=lambda m: -m["change"])

    # 추천: 순위가 높고, (기록이 있으면) 뜨는 속성·순위 상승, (첫날엔) 인기 속성을 가진 상품. 아이템 종류는 겹치지 않게.
    def score(p: dict) -> tuple[float, list[str]]:
        bonus, reasons = 0.0, []
        for group in ("item_type", "fit", "silhouette", "fiber", "color"):
            for v in attr_values(p, group):
                if v.startswith("기타"):
                    continue
                if has_trend:
                    t = trend.get((group, v), 0.0)
                    if t > 0:
                        bonus += 0.05 * t
                        reasons.append((t, f"{v} +{t:.1f}%p"))
                elif group != "item_type":
                    s = share_today.get((group, v), 0.0)
                    bonus += 0.004 * s
                    reasons.append((s, f"{v} {s:.0f}%"))
        prev = prev_rank.get((p["category_code"], p["product_id"]))
        if prev:
            bonus += max(0, prev - p["rank"]) / MAX_RANK
        reasons.sort(reverse=True)
        return p["weight"] + bonus, [r for _, r in reasons[:3]]

    recommendations, used_types = [], set()
    for p, (s, reasons) in sorted(((p, score(p)) for p in today), key=lambda x: -x[1][0]):
        if p["item_type"] in used_types:
            continue
        used_types.add(p["item_type"])
        why = f"1일 전체 랭킹 {p['rank']}위 ({p['category_name']})"
        prev = prev_rank.get((p["category_code"], p["product_id"]))
        if prev and prev > p["rank"]:
            why += f" (어제 {prev}위)"
        if reasons:
            why += (f" · 뜨는 속성({trend_label}): " if has_trend else " · 인기 속성 비중: ") + ", ".join(reasons)
        recommendations.append(product_brief(p) | {"reason": why, "score": round(s, 3)})
        if len(recommendations) >= RECOMMEND_PER_GENDER:
            break

    headlines = []
    for group in HEADLINE_GROUPS:
        rows = [r for r in attributes[group]["rows"] if not r["name"].startswith("기타")]  # '기타 하의'는 정보가 없음
        if has_trend:
            best = max(rows, key=lambda e: trend.get((group, e["name"]), -99), default=None)
            t = trend.get((group, best["name"])) if best else None
            if best and t is not None and t > 0:
                headlines.append({"kind": "뜨는", "group": GROUP_LABELS[group], "name": best["name"],
                                  "value": f"+{t:.1f}%p", "note": f"비중 {best['share']:.0f}% · {trend_label}"})
        elif rows:
            headlines.append({"kind": "가장 많은", "group": GROUP_LABELS[group], "name": rows[0]["name"],
                              "value": f"{rows[0]['share']:.0f}%", "note": "순위 가중 비중"})

    return {
        "count": len(today),
        "has_trend": has_trend,
        "trend_label": trend_label,
        "headlines": headlines,
        "attributes": attributes,
        "category_mix": category_mix(today),
        "top_by_category": top_by_category(today),
        "item_types": item_type_profiles(today, yesterday),
        "price_bands": price_bands(today),
        "movers": movers[:10],
        "new_entries": new_entries[:10],
        "recommendations": recommendations,
    }


def analyze(date: str) -> dict:
    rows = load_day(date)
    if rows is None:
        raise FileNotFoundError(f"{HISTORY_DIR / (date + '.csv')} 없음 — 먼저 musinsa_fetch.py 실행")
    details = load_details()
    today = build_products(rows, details)
    scope = data_scope(rows)
    yesterday_date = previous_dates(date, 1)[0]
    yesterday, history = None, []
    for d in previous_dates(date, TREND_WINDOW_DAYS):
        prev = load_day(d)
        if prev is None or data_scope(prev) != scope:
            continue  # 수집 방식이 다른 날(예: 9/24 카테고리별 랭킹)은 비교하지 않음
        products = build_products(prev, details)
        history.append(products)
        if d == yesterday_date:
            yesterday = products  # '어제 대비'는 정확히 어제 데이터가 있을 때만

    ids = {r["product_id"] for r in rows}
    return {
        "date": date,
        "scope": scope,
        "history_days": len(history),
        "has_yesterday": yesterday is not None,
        "detail_coverage": round(100 * sum(1 for i in ids if i in details) / max(1, len(ids)), 1),
        "genders": {g: analyze_gender(today[g], yesterday[g] if yesterday else None, [h[g] for h in history])
                    for g in GENDERS.values()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_kst())
    args = parser.parse_args()
    result = analyze(args.date)
    TMP_DIR.mkdir(exist_ok=True)
    out = TMP_DIR / f"analysis_{args.date}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"분석 완료: {out} (상세정보 반영 {result['detail_coverage']}%)")
    for g, data in result["genders"].items():
        print(f"  {g}: {data['count']}개")
        for h in data["headlines"]:
            print(f"    - {h['kind']} {h['group']}: {h['name']} {h['value']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
