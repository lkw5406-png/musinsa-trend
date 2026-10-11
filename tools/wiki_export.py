"""일간 분석 결과(JSON) → 위키 원본용 마크다운 Tool.

사장님의 남성복 위키(옵시디언, 비공개 저장소 michiko-london_menswear-wiki)의 raw/ 폴더에 넣을 글 파일을 만든다.
웹 리포트(docs/index.html)와 같은 분석 결과에서 만들므로 숫자가 같다. 사진·그래프는 없고 표와 글만.

출력: docs/wiki_raw/무신사 {성별} 일간 랭킹 리포트 (YYYY-MM-DD).md
  - docs/ 아래에 두는 이유: 수집 Action과 Claude 루틴이 둘 다 docs를 커밋하므로 따로 챙길 게 없음
  - 위키 저장소의 Action(sync-musinsa-raw)이 하루 두 번 이 폴더를 raw/로 복사해 감
  - build_report.build()가 일간 리포트를 만들 때마다 자동으로 같이 만듦 (원인 조사 뒤 다시 만들면 이유가 채워짐)

넣는 범위 (2026-10-11 사장님 확인): 남성만, 인기 TOP은 전체 50위 + 대분류별 20위, 후기는 집계만(원문 인용 없음).

사용법:
  python tools/wiki_export.py [--date YYYY-MM-DD]   그 날짜 하나 (기본: 오늘)
  python tools/wiki_export.py --all                 .tmp에 분석 파일이 있는 모든 날짜
"""
import argparse
import json
import sys
from pathlib import Path

from analyze_trends import analysis_path
from common import DOCS_DIR, TMP_DIR, today_kst

OUT_DIR = DOCS_DIR / "wiki_raw"
URL = "https://lkw5406-png.github.io/musinsa-trend/"
GROUPS = [("silhouette", "실루엣·기장"), ("texture", "원단"), ("fit", "핏"), ("fiber", "소재"), ("color", "컬러"), ("detail", "디테일")]
GNAME = dict(GROUPS)
TOP_ALL, TOP_CAT = 50, 20


def won(v):
    return f"{int(float(v)):,}원" if v not in (None, "", 0, "0") else "–"


def pp(v):
    return "–" if v is None else f"{v:+.1f}%p"


def cell(s):
    return str(s).replace("|", "/").replace("\n", " ")


def pname(p):
    return cell(f"{p['brand']} {p['product_name']}")


def plink(p):
    return f"[{pname(p)}]({p['product_url']})"


def render(a: dict, gender: str = "남성") -> str:
    g = a["genders"][gender]
    date, prev = a["date"], a["compare_date"]
    types = sorted(g.get("item_types", []), key=lambda t: -t["share"])
    if not a.get("has_yesterday"):
        compare = "비교 기록 없음 — 첫 기록이거나 집계 방식이 바뀐 첫날이라 '어제 대비' 숫자가 비어 있다"
    elif a.get("history_days"):
        compare = f"비교 대상: 어제 {prev}, 최근 {a['history_days']}일 평균"
    else:
        compare = f"비교 대상: 어제 {prev}"
    if a.get("scope") == "category":
        target = (f"무신사 {gender} 카테고리별 랭킹(상의/아우터/바지 각 1~200위)을 합친 {g['count']}개. "
                  "2026-09-24 하루만 쓴 방식이다. 9/25부터는 전체 랭킹에서 의류 상위 300개를 보는 방식으로 바뀌어 다른 날짜와 직접 비교할 수 없다")
    else:
        target = f"무신사 {gender} 전체 랭킹(최근 1일)에서 의류만 상위 {g['count']}개 · 상의/아우터/바지"
    L = [f"# 무신사 {gender} 일간 랭킹 리포트 ({date})", "",
         f"- 출처: {URL} (무신사 랭킹 프로젝트에서 Claude가 만든 일간 리포트, {gender} 탭 전체)",
         f"- 날짜: {date} ({compare})",
         f"- 대상: {target}",
         "- '인기 비중': 순위가 높을수록 크게 반영한 비중(의류 중 1위=1, 300위≈0). 상품 수 비율과 다르다.",
         "- '전체 순위': 신발·가방 등을 포함한 무신사 전체 랭킹 순위. '의류 순위': 의류만 센 순위.",
         "- 핏·두께는 판매자가 입력한 값, 소재는 겉감 주원료, 실루엣·원단은 상품명·상세 설명·실측표로 분류한 값.",
         "- 하루치 스냅샷이다. 어제 대비 변화는 하루 사이의 출렁임일 수 있다.", ""]

    # ---------- 1. 오늘 요약 ----------
    L += ["## 1. 오늘 요약", "", "### 가장 인기 있는 아이템", ""]
    L += [f"- {t['category_name']} · **{t['name']}**: 인기 비중 {t['share']:.1f}% · 상품 {t['count']}개" for t in types[:3]]
    rising = sorted((t for t in types if (t.get("dod_pp") or 0) >= 0.5), key=lambda t: -t["dod_pp"])[:3]
    L += ["", "### 어제보다 오른 아이템", "", "인기 비중이 어제보다 0.5%p 이상 오른 아이템."]
    for t in rising:
        spec = ", ".join(f"{GNAME.get(x['group'], x['group'])} {x['name']} +{x['gain']:.0f}%p" for x in t.get("spec_changes") or [])
        L.append(f"- {t['category_name']} · **{t['name']}**: ▲{t['dod_pp']:.1f}%p (인기 비중 {t['share']:.1f}%)" + (f" — 늘어난 스펙: {spec}" if spec else ""))
    L += ["", f"### {g['trend_label']} 뜨는 속성", ""]
    L += [f"- {h['group']} **{h['name']}**: {h['value']} ({h['note']})" for h in g.get("headlines", [])]
    L += ["", "### 순위가 크게 오른 상품 (상위 3)", ""]
    for m in g.get("movers", [])[:3]:
        w = m.get("why")
        why = f" — {w.get('summary') or ' · '.join(w['causes'])} [{w['confidence']}]" if w else ""
        L.append(f"- {plink(m)}: ▲{m['change']} ({m['prev_rank']}위 → {m['rank']}위){why}")
    fresh = g.get("fresh_entries", [])
    L += ["", "### 뜨는 신상", "", f"등록한 지 {g.get('fresh_days', 45)}일이 안 된 상품 중 의류 100위 안에 새로 들었거나 10계단 이상 오른 상품."]
    for p in fresh:
        was = f"{p['prev_clothing_rank']}위" if p.get("prev_clothing_rank") else "300위 밖"
        L.append(f"- {plink(p)}: 의류 {p['clothing_rank']}위 (어제 {was}) · {p['item_type']} · {won(p['final_price'])} · {p['registered']} 등록")
    L += ["", "### 뜨는 브랜드", "", "300위 안 상품 수가 어제보다 늘어난 브랜드.", "",
          "| 브랜드 | 300위 안 상품 수 | 어제 대비 | 크게 오른 상품 수 | 대표 상품 |", "|---|---|---|---|---|"]
    L += [f"| {b['brand']} | {b['count']} | +{b['gain']} | {b['movers']} | {cell(b['best'])} |" for b in g.get("rising_brands", [])]

    # ---------- 2. 아이템 순위 ----------
    L += ["", "## 2. 아이템 순위", "", "어떤 종류의 옷이 잘 팔리는지 인기 비중 순.", "",
          "| 순위 | 대분류 | 아이템 | 인기 비중 | 어제 대비 | 상품 수 | 가장 높은 전체 순위 |", "|---|---|---|---|---|---|---|"]
    L += [f"| {i} | {t['category_name']} | {t['name']} | {t['share']:.1f}% | {pp(t.get('dod_pp'))} | {t['count']} | {t.get('best_rank', '–')}위 |"
          for i, t in enumerate(types, 1)]
    L += ["", "### 추천 아이템", "", "순위가 높고 뜨는 속성을 많이 가진 상품. 아이템 종류별 1개."]
    for p in g.get("recommendations", []):
        L.append(f"- {plink(p)} · {p['item_type']} · {won(p['final_price'])} — {p['reason']}")

    # ---------- 3. 아이템별 스펙 ----------
    L += ["", "## 3. 아이템별 스펙", "",
          "아이템마다 잘 팔리는 스펙. %는 그 아이템 안에서의 인기 비중(파악된 상품 기준). 여러 색으로 파는 상품은 색을 모두 세므로 합이 100%를 넘는다."]
    for t in types:
        L += ["", f"### {t['name']} ({t['category_name']} · 상품 {t['count']}개 · 인기 비중 {t['share']:.1f}%)", ""]
        for key, label in GROUPS:
            vals = (t.get("groups", {}).get(key) or {}).get("values") or []
            if vals:
                L.append(f"- {label}: " + ", ".join(f"{v['name']} {v['pct']:.0f}%" for v in vals[:5]))
        tops = t.get("top_products") or []
        if tops:
            L.append("- 잘 팔리는 상품: " + " / ".join(f"{pname(p)} (전체 {p['rank']}위)" for p in tops[:3]))

    # ---------- 4. 대분류별 ----------
    BG = [("fit", "핏"), ("silhouette", "실루엣·기장"), ("detail", "디테일"), ("color", "컬러")]
    L += ["", "## 4. 대분류별 핏 · 실루엣 · 디테일 · 컬러", "", "인기 비중과 어제 대비 변화."]
    for b in g.get("big_categories", []):
        L += ["", f"### {b['name']} (상품 {b['count']}개)"]
        for key, label in BG:
            rows = (b["attributes"].get(key) or {}).get("rows") or []
            if not rows:
                continue
            L += ["", f"**{label}**", "", "| 항목 | 인기 비중 | 상품 수 | 어제 대비 |", "|---|---|---|---|"]
            L += [f"| {r['name']} | {r['share']:.1f}% | {r['count']} | {pp(r.get('dod_pp'))} |" for r in rows[:10]]

    # ---------- 5. 전체 속성 ----------
    AG = [("fit", "핏"), ("silhouette", "실루엣"), ("fiber", "소재(주원료)"), ("texture", "원단"), ("color", "컬러"), ("detail", "디테일"), ("thickness", "두께")]
    L += ["", f"## 5. 전체 의류 속성 ({g['trend_label']} 변화 포함)", ""]
    for key, label in AG:
        rows = (g.get("attributes", {}).get(key) or {}).get("rows") or []
        if not rows:
            continue
        L += [f"### {label}", "", "| 항목 | 인기 비중 | 상품 수 | 어제 대비 | 7일 평균 대비 |", "|---|---|---|---|---|"]
        L += [f"| {r['name']} | {r['share']:.1f}% | {r['count']} | {pp(r.get('dod_pp'))} | {pp(r.get('week_pp'))} |" for r in rows[:10]] + [""]

    # ---------- 6. 가격 ----------
    L += ["## 6. 가격", "", "### 아이템별 가격", "",
          "실판매가 = 할인이 적용된 지금 가격, 정가 = 할인 전 가격. '주로 팔리는 실판매가' = 가운데 절반의 상품이 들어가는 범위.", "",
          "| 대분류 | 아이템 | 상품 수 | 실판매가(중간) | 정가(중간) | 평균 할인율 | 주로 팔리는 실판매가 |", "|---|---|---|---|---|---|---|"]
    for t in sorted((t for t in g.get("item_types", []) if t.get("median_price")), key=lambda t: (t["category_code"], -t["share"])):
        lo, hi = t.get("price_low"), t.get("price_high")
        rng = f"{won(lo)} ~ {won(hi)}" if lo and hi else "상품이 적어 생략"
        disc = f"{t['discount_avg']:.0f}%" if t.get("discount_avg") is not None else "–"
        L.append(f"| {t['category_name']} | {t['name']} | {t['count']} | {won(t['median_price'])} | {won(t.get('median_original'))} | {disc} | {rng} |")
    pb = g.get("price_bands")
    if pb:
        L += ["", "### 가격대 분포 (상품 수)", "", "| 대분류 | " + " | ".join(pb["labels"]) + " | 중간 가격 |", "|---|" + "---|" * (len(pb["labels"]) + 1)]
        L += [f"| {r['name']} | " + " | ".join(str(c) for c in r["counts"]) + f" | {won(r['median'])} |" for r in pb["rows"]]
        L.append("| **전체** | " + " | ".join(str(c) for c in pb["totals"]) + f" | {won(pb['median'])} |")

    # ---------- 7. 시장 동향 ----------
    L += ["", "## 7. 시장 동향", "", "### 어제보다 순위가 크게 오른 상품과 이유", "",
          "오른 이유는 Claude가 웹·유튜브·SNS·커뮤니티를 조사해 찾은 유입 경로. [확인] = 출처에서 이 상품(또는 같은 모델)이 직접 소개된 것을 봄, [추정] = 직접 증거 없이 정황으로 판단."]
    for m in g.get("movers", []):
        L += ["", f"#### {pname(m)}", "",
              f"- {m['item_type']} · {won(m['final_price'])} (할인 {m['discount_rate']}%) · {m.get('sales_label', '')}",
              f"- 전체 {m['prev_rank']}위 → {m['rank']}위 (▲{m['change']}) · 의류 {m['clothing_rank']}위",
              f"- 속성: {', '.join(m.get('attrs') or [])}", f"- 링크: {m['product_url']}"]
        w = m.get("why")
        if not w:
            L.append("- 이유: 조사 전")
            continue
        L += [f"- 이유 [{w['confidence']}]: {w.get('summary', '')} (분류: {', '.join(w['causes'])})"]
        L += [f"  - {x}" for x in w.get("points", [])]
        if w.get("sources"):
            L.append("- 출처: " + " / ".join(f"[{cell(s['title'])}]({s['url']})" for s in w["sources"]))
    L += ["", "### 오늘 새로 TOP 50에 진입", "", "| 전체 순위 | 의류 순위 | 상품 | 아이템 | 가격 | 할인 | 속성 |", "|---|---|---|---|---|---|---|"]
    L += [f"| {p['rank']} | {p['clothing_rank']} | {plink(p)} | {p['item_type']} | {won(p['final_price'])} | {p['discount_rate']}% | {', '.join(p.get('attrs') or [])} |"
          for p in g.get("new_entries", [])]

    # ---------- 8. 인기 TOP ----------
    cats = {c["code"]: c for c in g.get("top_by_category", [])}
    L += ["", f"## 8. 인기 TOP", "", f"### 의류 전체 TOP {TOP_ALL}", "",
          "후기 요약은 도움순 후기 50개와 별점 낮은 후기 최대 50개에서 자주 나온 표현. 좋아요는 4~5점 후기, 아쉬워요는 3점 이하 후기에서 셌다. 숫자는 그 표현이 나온 후기 수."]
    for p in cats["all"]["products"][:TOP_ALL]:
        L += ["", f"**{p['clothing_rank']}. {plink(p)}**", "",
              f"- {p['category_name']} · {p['item_type']} · {won(p['final_price'])} (할인 {p['discount_rate']}%) · {p.get('sales_label', '')} · 전체 {p['rank']}위",
              f"- 속성: {', '.join(p.get('attrs') or [])}"]
        r = p.get("review")
        if r:
            if r.get("pros"):
                L.append("- 좋아요: " + ", ".join(f"{x['name']} {x['count']}" for x in r["pros"][:4]))
            if r.get("cons"):
                L.append("- 아쉬워요: " + ", ".join(f"{x['name']} {x['count']}" for x in r["cons"][:4]))
            if r.get("survey"):
                L.append("- 구매자 응답: " + ", ".join(f"{s['attribute']} '{s['answer']}' {s['pct']}%" for s in r["survey"]))
            meta = f"후기 {r['total']:,}개" if r.get("total") else ""
            if r.get("bad_pct") is not None:
                meta += f" · 3점 이하 {r['bad_pct']}%"
            if meta:
                L.append(f"- {meta}")
    for code in ("001", "002", "003"):
        c = cats.get(code)
        if not c:
            continue
        L += ["", f"### {c['name']} TOP {TOP_CAT} (300위 안 {c['count']}개)", "", "| 순위 | 상품 | 아이템 | 가격 | 할인 | 전체 순위 |", "|---|---|---|---|---|---|"]
        L += [f"| {i} | {plink(p)} | {p['item_type']} | {won(p['final_price'])} | {p['discount_rate']}% | {p['rank']} |"
              for i, p in enumerate(c["products"][:TOP_CAT], 1)]


    return "\n".join(L) + "\n"


def export(a: dict, gender: str = "남성") -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"무신사 {gender} 일간 랭킹 리포트 ({a['date']}).md"
    path.write_text(render(a, gender), encoding="utf-8", newline="\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_kst())
    parser.add_argument("--all", action="store_true", help=".tmp에 분석 파일이 있는 모든 날짜")
    args = parser.parse_args()
    if args.all:
        files = sorted(TMP_DIR.glob("analysis_20??-??-??.json"))
    else:
        files = [analysis_path(args.date, "daily")]
        if not files[0].exists():
            print(f"분석 파일이 없어요: {files[0]} — 먼저 python tools/run_daily.py --skip-fetch 로 분석을 만드세요")
            return 1
    for f in files:
        print(f"위키 원본 생성: {export(json.loads(f.read_text(encoding='utf-8')))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
