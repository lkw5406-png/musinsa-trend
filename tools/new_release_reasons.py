"""신상 랭킹 진입 원인 도우미 Tool — 그해 신상 페이지(new_releases.py)의 상품마다 Claude가 조사한 '랭킹에 오른 이유'를
검사해서 data/new_release_reasons_<연도>.json에 합친다. 조사 방법·형식은 매일 리포트의 순위 급상승 원인(rise_reasons.py)과 같다.
(2026-10-15 사장님: "상승 원인도 같이 조사. 시장 동향 조사한 방법대로")

- 조사 대상 (2026-10-15 사장님 선택): **처음 랭킹에 오른 달에 세부 카테고리(또는 대분류) 10위 안**에 든 신상.
  그해 남성 신상 1,025개 중 278개. 하루 유튜브 검색 한도(약 100번, 매일 루틴과 나눠 씀) 때문에 며칠에 나눠 조사.
- 원인을 찾는 기간 = 등록일 ~ 처음 오른 달 말일 (월간 랭킹이라 그 한 달 동안의 판매·관심이 순위를 만듦).
- 유튜브만 보지 말고 종합적으로 (2026-10-15 사장님): 그 달 날씨·무신사 세일(data/new_release_context_<연도>.json, 페이지 '그 달 배경'에도 자동 표시),
  할인·가격(매일 수집 data/history는 2026-09-24부터라 9월 상품만 할인율·판매량 단서가 있음), 같은 브랜드 동반 진입, 브랜드 화제까지 보고
  관련 있으면 causes·points에 넣는다.
- 매일 리포트에서 같은 상품을 이미 조사했으면(data/rise_reasons.json) --import로 가져와 다시 조사하지 않음.

사용법:
  python tools/new_release_reasons.py --check                         달별 남은 개수
  python tools/new_release_reasons.py --import                        매일 리포트 조사 결과 가져오기
  python tools/new_release_reasons.py --next [N] [--month 2026-03]   조사할 상품 N개(기본 10) + 데이터 단서 → .tmp/nr_queue.json
  python tools/new_release_reasons.py --merge .tmp/nr_batch.json      검사 후 합치기 (형식은 rise_reasons.py와 같음)
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, RISE_REASONS_PATH, TMP_DIR
from rise_reasons import CAUSES, validate

YEAR = "2026"
BEST_RANK = 10
QUEUE_PATH = TMP_DIR / "nr_queue.json"


def data_path(year: str) -> Path:
    return TMP_DIR / f"new_releases_{year}.json"


def reasons_path(year: str) -> Path:
    return ROOT / "data" / f"new_release_reasons_{year}.json"


def best_rank(p: dict, ym: str) -> int:
    r = p["ranks"].get(ym, {})
    return min([r.get("top", 99), *(r.get("sub") or {}).values()])


def targets(year: str) -> dict:
    prods = json.loads(data_path(year).read_text(encoding="utf-8"))["products"]
    return {pid: p for pid, p in prods.items() if best_rank(p, p["first"]) <= BEST_RANK}


def load(year: str) -> dict:
    path = reasons_path(year)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(year: str, reasons: dict) -> None:
    reasons_path(year).write_text(json.dumps(reasons, ensure_ascii=False, indent=1), encoding="utf-8")


def rank_text(p: dict, ym: str) -> str:
    r = p["ranks"][ym]
    parts = [f"대분류 {r['top']}위"] if r.get("top") else []
    parts += [f"{s} {v}위" for s, v in sorted((r.get("sub") or {}).items(), key=lambda kv: kv[1])]
    return " · ".join(parts)


def context(year: str) -> dict:
    path = ROOT / "data" / f"new_release_context_{year}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def daily_hints(pid: str, ym: str) -> list[str]:
    """매일 수집(data/history, 2026-09-24부터)에 그 달 이 상품이 있으면 가격·할인율·판매량 (첫날·마지막 날)."""
    seen = []
    for path in sorted((ROOT / "data" / "history").glob(f"{ym}-*.csv")):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r["product_id"] == pid and r["gender_filter"] == "M":
                    seen.append(r)
                    break
    if not seen:
        return []
    fmt = lambda r: (f"{r['date']} {int(float(r['final_price'] or 0)):,}원(할인 {r['discount_rate'] or 0}%)"
                     + (f" · {r['sales_label']}" if r.get("sales_label") and r["sales_label"].lower() != "none" else ""))
    return [f"매일 수집: {fmt(seen[0])}" + (f" → {fmt(seen[-1])}" if len(seen) > 1 else "")]


def clues(p: dict, all_t: dict, ctx: dict | None = None) -> list[str]:
    ym = p["first"]
    last_day = calendar.monthrange(int(ym[:4]), int(ym[5:]))[1]
    same = [q for q in all_t.values() if q["brand"] == p["brand"] and q["first"] == ym]
    out = [f"원인 찾을 기간: {p['reg']} ~ {ym}-{last_day:02d}",
           f"처음 오른 달 {ym}: {rank_text(p, ym)}",
           f"랭킹 든 달: {', '.join(p['ranks'])}",
           f"정가 {p['price']:,}원" if p.get("price") else "정가 정보 없음"]
    if len(same) > 1:
        out.append(f"같은 브랜드 같은 달 신상 진입 {len(same)}개 (대상 안)")
    c = (ctx or {}).get(ym) or {}
    if c.get("weather"):
        out.append(f"그 달 날씨: {c['weather']}")
    out += [f"그 달 무신사: {e}" for e in c.get("events", [])]
    return out + daily_hints(p["id"], ym)


def warn_months(batch: dict, t: dict) -> None:
    """'N월까지'라고 쓴 달이 실제 마지막 랭킹 달과 다르면 경고 (2026-10-15: 한 달씩 틀리게 쓴 적 있음)."""
    for pid, r in batch.items():
        last = int(max(t[pid]["ranks"])[5:])
        text = " ".join(r.get("points", [])) + " " + r.get("reason", "")
        for m in re.findall(r"(\d+)월까지 (?:\d+개월|매달|랭킹|거의|여러)", text):
            if int(m) != last:
                print(f"  확인 필요 {pid}: '{m}월까지'라고 썼지만 마지막 랭킹 달은 {last}월")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default=YEAR)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--import", dest="do_import", action="store_true")
    ap.add_argument("--next", nargs="?", type=int, const=10)
    ap.add_argument("--month")
    ap.add_argument("--merge")
    args = ap.parse_args()

    t = targets(args.year)
    reasons = load(args.year)

    if args.do_import:
        daily = json.loads(RISE_REASONS_PATH.read_text(encoding="utf-8")) if RISE_REASONS_PATH.exists() else {}
        added = 0
        for k in sorted(daily):  # 가장 이른 조사(처음 뜰 때)를 씀
            for pid, r in daily[k].items():
                if pid in t and pid not in reasons and r.get("points"):
                    reasons[pid] = {**r, "from": f"매일 리포트 {k}"}
                    added += 1
        save(args.year, reasons)
        print(f"매일 리포트 조사 결과 {added}개 가져옴")

    if args.merge:
        batch = json.loads(Path(args.merge).read_text(encoding="utf-8"))
        errs = validate(batch, set(t))
        # 화면 출력을 자르다 영상 주소가 잘린 채 들어간 적 있음(2026-10-15) → 유튜브 영상 번호는 11자
        errs += [f"{pid}: 잘린 유튜브 주소 {s['url']}" for pid, r in batch.items() for s in r.get("sources", [])
                 if "youtu.be/" in s.get("url", "") and len(s["url"].split("youtu.be/")[1].split("?")[0]) != 11]
        if errs:
            print("거부 — 고쳐서 다시:\n  " + "\n  ".join(errs))
            return 1
        warn_months(batch, t)
        reasons.update(batch)
        save(args.year, reasons)
        print(f"{len(batch)}개 합침 → {reasons_path(args.year)}")

    if args.next is not None:
        todo = sorted((p for pid, p in t.items() if pid not in reasons and (not args.month or p["first"] == args.month)),
                      key=lambda p: (p["first"], p["brand"], best_rank(p, p["first"])))[: args.next]
        items = [{"product_id": p["id"], "brand": p["brand"], "name": p["name"], "item_type": p["sub"],
                  "reg": p["reg"], "first": p["first"], "hints": clues(p, t, context(args.year))} for p in todo]
        QUEUE_PATH.write_text(json.dumps({"causes": CAUSES, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
        for it in items:
            print(f"- {it['product_id']} {it['brand']} | {it['name']} ({it['item_type']})")
            for h in it["hints"]:
                print(f"    {h}")

    left = Counter(p["first"] for pid, p in t.items() if pid not in reasons)
    done = Counter(p["first"] for pid, p in t.items() if pid in reasons)
    print(f"대상 {len(t)}개 · 조사 끝 {sum(done.values())} · 남음 {sum(left.values())} | 남은 달별 {dict(sorted(left.items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
