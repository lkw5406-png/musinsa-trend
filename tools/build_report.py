"""분석 결과(JSON) → 리포트 웹페이지(HTML) Tool.

출력 (GitHub Pages가 docs/ 폴더를 그대로 공개 — 주소 하나로 계속 운영):
  docs/index.html               최신 리포트 (매일 덮어씀, 사장님이 보는 고정 주소)
  docs/reports/YYYY-MM-DD.html  날짜별 리포트 (페이지 위 날짜 선택으로 이동)
  docs/dates.json               리포트가 있는 날짜 목록

사용법:
  python tools/build_report.py [--date YYYY-MM-DD]
  python tools/build_report.py --date YYYY-MM-DD --standalone 파일.html   사진을 품은 한 장짜리 페이지
"""
import argparse
import base64
import json
import re
import sys
import time
import urllib.request
from html import escape

from common import DOCS_DIR, TMP_DIR, USER_AGENT, today_kst

CHART_GROUPS = [
    ("item_type", "아이템 종류"),
    ("fit", "핏"),
    ("silhouette", "실루엣·기장"),
    ("fiber", "소재(주원료)"),
    ("texture", "원단·가공"),
    ("color", "컬러"),
    ("thickness", "두께"),
    ("detail", "디테일"),
]
CHART_ROWS = 8
SCOPE_TEXT = {
    "overall": "무신사 남성·여성 전체 랭킹(최근 1일)에서 의류만 상위 300개 · 상의/아우터/바지/원피스·스커트",
    "category": "무신사 전체 랭킹(최근 1일) · 상의/아우터/바지/원피스·스커트 · 카테고리별 1~200위 (9/24 방식)",
}

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --bar: #2a78d6; --accent: #2a78d6; --up-text: #006300; --down-text: #b3261e;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --bar: #3987e5; --accent: #3987e5; --up-text: #0ca30c; --down-text: #e66767;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --bar: #3987e5; --accent: #3987e5; --up-text: #0ca30c; --down-text: #e66767;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 32px 20px 64px; }
header { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: flex-end; justify-content: space-between; }
header h1 { font-size: 26px; margin: 0 0 4px; letter-spacing: -0.01em; text-wrap: balance; }
header p { margin: 0; color: var(--ink-2); }
.datepick { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.datepick select { font: inherit; font-size: 15px; font-weight: 600; color: var(--ink); background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; padding: 8px 12px; min-width: 170px; }
.note { font-size: 13px; color: var(--muted); margin-top: 8px; }
.tabs { display: flex; gap: 6px; margin: 24px 0 20px; flex-wrap: wrap; position: sticky;
  top: env(safe-area-inset-top, 0px); background: var(--page); padding: 8px 0; z-index: 5; }
.tabs button { font: inherit; font-weight: 600; padding: 8px 18px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink-2); }
.tabs button[aria-selected="true"] { background: var(--ink); color: var(--page); border-color: var(--ink); }
.tabs button:focus-visible, .row:focus-visible, select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
section.card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 20px; margin-bottom: 18px; }
section.card h2 { font-size: 18px; margin: 0 0 4px; }
section.card .sub { font-size: 13px; color: var(--muted); margin: 0 0 14px; }
.headlines { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(180px, 100%), 1fr)); gap: 12px; }
.headline { border: 1px solid var(--border); border-radius: 12px; padding: 14px; }
.headline .k { font-size: 12px; color: var(--muted); }
.headline .v { font-size: 20px; font-weight: 700; margin: 2px 0; }
.headline .d { font-size: 13px; color: var(--ink-2); }
.recs { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(160px, 100%), 1fr)); gap: 14px; }
.rec { text-decoration: none; color: inherit; border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
  display: flex; flex-direction: column; background: var(--surface); }
.rec:hover { border-color: var(--accent); }
.rec img { width: 100%; aspect-ratio: 1 / 1.2; object-fit: cover; background: var(--grid); display: block; }
.rec .body { padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 3px; }
.rec .brand { font-size: 12px; color: var(--muted); }
.rec .name { font-size: 13px; font-weight: 600; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.rec .price { font-size: 14px; font-weight: 700; }
.rec .why { font-size: 12px; color: var(--ink-2); }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr)); gap: 22px 28px; }
.charts > div, .two > div { min-width: 0; }
.chart h3 { font-size: 15px; margin: 0; }
.chart .cov { font-size: 12px; color: var(--muted); margin: 0 0 8px; }
.row { display: grid; grid-template-columns: 104px 1fr 44px 58px; align-items: center; gap: 8px;
  padding: 5px 4px; font-size: 13px; border-radius: 6px; }
.row:hover { background: color-mix(in srgb, var(--grid) 55%, transparent); }
.row .label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row .val, .row .chg { text-align: right; font-variant-numeric: tabular-nums; }
.row .val { font-weight: 600; }
.row .chg { font-size: 12px; }
.track { position: relative; height: 12px; border-left: 1px solid var(--axis); }
.bar { position: absolute; left: 0; top: 1px; height: 10px; background: var(--bar); border-radius: 0 4px 4px 0; }
.chg-head { display: grid; grid-template-columns: 104px 1fr 44px 58px; gap: 8px; font-size: 11px; color: var(--muted);
  padding: 0 4px 4px; }
.chg-head span:nth-child(3), .chg-head span:nth-child(4) { text-align: right; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--grid); vertical-align: middle; }
th { color: var(--muted); font-weight: 600; font-size: 12px; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td img { width: 40px; height: 48px; object-fit: cover; border-radius: 4px; background: var(--grid); display: block; }
td a { color: inherit; text-decoration: none; }
td a:hover { text-decoration: underline; }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(340px, 100%), 1fr)); gap: 18px; }
.up-t { color: var(--up-text); } .down-t { color: var(--down-text); } .flat-t { color: var(--muted); }
.empty { color: var(--muted); font-size: 13px; }
footer { margin-top: 32px; font-size: 12px; color: var(--muted); max-width: 70ch; }
#tip { position: fixed; pointer-events: none; z-index: 20; background: var(--ink); color: var(--page);
  font-size: 12px; line-height: 1.5; padding: 8px 10px; border-radius: 8px; max-width: 260px; }
@media (max-width: 480px) {
  .row, .chg-head { grid-template-columns: 84px 1fr 38px 52px; }
  .wrap { padding: 20px 16px 48px; }
}
"""

JS = """
const tabs = document.querySelectorAll('.tabs button');
tabs.forEach(b => b.addEventListener('click', () => {
  tabs.forEach(t => t.setAttribute('aria-selected', t === b));
  document.querySelectorAll('.panel').forEach(p => p.hidden = p.id !== b.dataset.panel);
  try { localStorage.setItem('mss-tab', b.dataset.panel); } catch (e) {}
}));
try { const s = localStorage.getItem('mss-tab'); const b = s && document.querySelector(`[data-panel="${s}"]`); if (b) b.click(); } catch (e) {}

const tip = document.getElementById('tip');
function show(e) { const t = e.currentTarget.dataset.tip; if (!t) return; tip.innerHTML = t; tip.hidden = false; move(e); }
function move(e) { const r = e.currentTarget.getBoundingClientRect();
  const x = e.clientX ?? (r.left + r.width / 2), y = e.clientY ?? r.top;
  tip.style.left = Math.max(8, Math.min(x + 12, window.innerWidth - tip.offsetWidth - 8)) + 'px';
  tip.style.top = Math.max(8, y - tip.offsetHeight - 10) + 'px'; }
function hide() { tip.hidden = true; }
document.querySelectorAll('[data-tip]').forEach(el => {
  el.addEventListener('mouseenter', show); el.addEventListener('mousemove', move);
  el.addEventListener('mouseleave', hide); el.addEventListener('focus', show); el.addEventListener('blur', hide);
});

// 날짜 선택: 최신 목록(dates.json)을 불러와 채움. 못 불러오면 페이지에 들어 있는 목록을 씀.
const pick = document.getElementById('date');
if (pick) {
  const base = pick.dataset.base, current = pick.dataset.current;
  const fill = dates => {
    pick.innerHTML = '';
    dates.forEach((d, i) => { const o = document.createElement('option'); o.value = d;
      o.textContent = d + (i === 0 ? ' (최신)' : ''); o.selected = d === current; pick.appendChild(o); });
  };
  fetch(base + 'dates.json', {cache: 'no-store'}).then(r => r.ok ? r.json() : Promise.reject())
    .then(fill).catch(() => {});
  pick.addEventListener('change', () => {
    const d = pick.value, latest = pick.options[0] && pick.options[0].value;
    location.href = d === latest ? base + 'index.html' : base + 'reports/' + d + '.html';
  });
}
"""


def e(v) -> str:
    return escape(str(v if v is not None else ""))


def won(v) -> str:
    try:
        return f"{int(float(v)):,}원"
    except (TypeError, ValueError):
        return ""


def pp(v) -> str:
    return "–" if v is None else f"{'+' if v > 0 else ''}{v:.1f}%p"


def change_html(v) -> str:
    if v is None:
        return "<span class='flat-t'>–</span>"
    if abs(v) < 0.05:
        return "<span class='flat-t'>0.0</span>"
    cls, arrow = ("up-t", "▲") if v > 0 else ("down-t", "▼")
    return f"<span class='{cls}'>{arrow}{abs(v):.1f}</span>"


def headline_cards(headlines: list[dict]) -> str:
    if not headlines:
        return '<p class="empty">오늘은 뚜렷한 변화가 없어요.</p>'
    cards = "".join(
        f'<div class="headline"><div class="k">{e(h["kind"])} {e(h["group"])}</div><div class="v">{e(h["name"])}</div>'
        f'<div class="d"><b class="{"up-t" if h["kind"] == "뜨는" else ""}">{e(h["value"])}</b> · {e(h["note"])}</div></div>'
        for h in headlines)
    return f'<div class="headlines">{cards}</div>'


def rec_cards(recs: list[dict]) -> str:
    if not recs:
        return '<p class="empty">추천할 상품이 없어요.</p>'
    out = []
    for r in recs:
        discount = str(r.get("discount_rate") or "0")
        discount_html = f" <small>{e(discount)}%↓</small>" if discount != "0" else ""
        out.append(
            f'<a class="rec" href="{e(r["product_url"])}" target="_blank" rel="noopener">'
            f'<img src="{e(r["image_url"])}" alt="" loading="lazy" referrerpolicy="no-referrer">'
            f'<div class="body"><span class="brand">{e(r["brand"])} · {e(r["item_type"])}</span>'
            f'<span class="name">{e(r["product_name"])}</span>'
            f'<span class="price">{won(r["final_price"])}{discount_html}</span>'
            f'<span class="why">{e(r["reason"])}</span></div></a>')
    return f'<div class="recs">{"".join(out)}</div>'


def share_chart(title: str, group: dict, trend_label: str, has_trend: bool) -> str:
    rows = group["rows"][:CHART_ROWS]
    cov = f"상품 {group['coverage']:.0f}%에서 파악 · 파악된 상품 중 비중"
    if not rows:
        return f'<div class="chart"><h3>{e(title)}</h3><p class="cov">{cov}</p><p class="empty">데이터가 부족해요.</p></div>'
    scale = max(10.0, max(r["share"] for r in rows))
    head = (f"<div class='chg-head'><span></span><span></span><span>비중</span>"
            f"<span>{'7일比' if trend_label.startswith('7일') else '어제比'}</span></div>")
    out = []
    for r in rows:
        change = r["week_pp"] if r["week_pp"] is not None else r["dod_pp"]
        tip = f'<b>{e(r["name"])}</b><br>비중 {r["share"]:.1f}% ({r["count"]}개 상품)'
        if r["dod_pp"] is not None:
            tip += f'<br>어제 대비 {pp(r["dod_pp"])}'
        if r["week_pp"] is not None:
            tip += f'<br>7일 평균 대비 {pp(r["week_pp"])}'
        out.append(
            f'<div class="row" tabindex="0" data-tip="{e(tip)}"><span class="label">{e(r["name"])}</span>'
            f'<span class="track"><span class="bar" style="width:{r["share"] / scale * 100:.1f}%"></span></span>'
            f'<span class="val">{r["share"]:.0f}%</span><span class="chg">{change_html(change) if has_trend else ""}</span></div>')
    return f'<div class="chart"><h3>{e(title)}</h3><p class="cov">{cov}</p>{head if has_trend else ""}{"".join(out)}</div>'


def product_table(title: str, products: list[dict], extra_col: str | None = None, empty: str = "") -> str:
    if not products:
        return f'<div><h3>{e(title)}</h3><p class="empty">{e(empty or "해당 상품이 없어요.")}</p></div>'
    head = "<th class='num'>전체 순위</th><th></th><th>상품</th><th>카테고리</th><th class='num'>가격</th>"
    if extra_col:
        head += f"<th class='num'>{e(extra_col)}</th>"
    body = []
    for p in products:
        extra = ""
        if extra_col:
            extra = f"<td class='num up-t'>▲{p['change']} <small>({p['prev_rank']}→{p['rank']})</small></td>"
        attrs = " · ".join(p.get("attrs") or [])
        attrs_html = f"<br><small style='color:var(--muted)'>{e(attrs)}</small>" if attrs else ""
        body.append(
            f"<tr><td class='num'>{p['rank']}</td>"
            f"<td><img src='{e(p['image_url'])}' alt='' loading='lazy' referrerpolicy='no-referrer'></td>"
            f"<td><a href='{e(p['product_url'])}' target='_blank' rel='noopener'><small>{e(p['brand'])}</small><br>"
            f"{e(p['product_name'])}</a>{attrs_html}</td>"
            f"<td>{e(p['category_name'])}<br><small>{e(p['item_type'])}</small></td>"
            f"<td class='num'>{won(p['final_price'])}</td>{extra}</tr>")
    return (f'<div><h3>{e(title)}</h3><div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></div>')


def gender_panel(idx: int, gender: str, g: dict, has_yesterday: bool) -> str:
    charts = "".join(share_chart(title, g["attributes"][key], g["trend_label"], g["has_trend"])
                     for key, title in CHART_GROUPS)
    if g["has_trend"]:
        chart_sub = (f"막대 = 순위 가중 비중(1위일수록 크게 반영). 오른쪽 숫자 = {e(g['trend_label'])} 비중 변화(%p). "
                     "막대에 마우스를 올리면 자세한 수치.")
        head_sub = f"{e(g['trend_label'])} 비중이 가장 많이 늘어난 속성"
    else:
        chart_sub = "막대 = 순위 가중 비중(1위일수록 크게 반영). 어제 대비 변화는 내일부터 표시돼요."
        head_sub = "오늘 랭킹에서 비중이 가장 큰 속성 (추세는 기록이 쌓이면 표시)"
    no_yday = "어제 기록이 없어 내일부터 표시돼요."
    return f"""
<div class="panel" id="p{idx}" role="tabpanel" {'hidden' if idx else ''}>
  <section class="card">
    <h2>{e(gender)} 한눈에 보기</h2>
    <p class="sub">{e(head_sub)} · 1일 랭킹 {g['count']}개 상품 기준</p>
    {headline_cards(g['headlines'])}
  </section>
  <section class="card">
    <h2>추천 아이템</h2>
    <p class="sub">순위가 높고 {'뜨는' if g['has_trend'] else '인기'} 속성을 많이 가진 상품 (아이템 종류별 1개)</p>
    {rec_cards(g['recommendations'])}
  </section>
  <section class="card">
    <h2>무엇이 잘 팔리나</h2>
    <p class="sub">{chart_sub}</p>
    <div class="charts">{charts}</div>
  </section>
  <section class="card">
    {product_table('카테고리별 TOP 3', g['top'])}
  </section>
  <section class="card two">
    {product_table('어제보다 순위가 크게 오른 상품', g['movers'], extra_col='변화', empty=no_yday if not has_yesterday else '')}
    {product_table('오늘 새로 TOP 50에 진입', g['new_entries'], empty=no_yday if not has_yesterday else '')}
  </section>
</div>"""


def render(a: dict, dates: list[str] | None, base: str) -> str:
    genders = list(a["genders"].items())
    tabs = "".join(
        f'<button type="button" role="tab" data-panel="p{i}" aria-selected="{str(i == 0).lower()}">{e(name)}</button>'
        for i, (name, _) in enumerate(genders))
    panels = "".join(gender_panel(i, name, g, a["has_yesterday"]) for i, (name, g) in enumerate(genders))
    history_note = (f"최근 {a['history_days']}일 기록과 비교했어요." if a["history_days"]
                    else "첫 기록이라 어제·7일 비교는 기록이 쌓이면 표시돼요.")
    date_picker = ""
    if dates:
        options = "".join(f'<option value="{e(d)}"{" selected" if d == a["date"] else ""}>{e(d)}{" (최신)" if i == 0 else ""}</option>'
                          for i, d in enumerate(dates))
        date_picker = (f'<label class="datepick" for="date">날짜 선택'
                       f'<select id="date" data-base="{e(base)}" data-current="{e(a["date"])}">{options}</select></label>')
    return f"""<meta charset="utf-8">
<title>무신사 의류 트렌드</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>{CSS}</style>
<div class="wrap">
  <header>
    <div>
      <h1>무신사 의류 랭킹 트렌드 · {e(a['date'])}</h1>
      <p>{e(SCOPE_TEXT.get(a.get('scope', 'category')))}</p>
      <p class="note">{e(history_note)} 상품 상세정보(핏·소재·두께) 반영 {a['detail_coverage']:.0f}%</p>
    </div>
    {date_picker}
  </header>
  <nav class="tabs" role="tablist">{tabs}</nav>
  {panels}
  <footer>
    <p>매일 오전 10시 기준 무신사 전체 랭킹(최근 1일)을 모아 날짜별로 쌓아요. 남성·여성은 무신사 성별 랭킹 그대로예요.
    비중은 순위가 높을수록 크게 반영(의류 중 1위=1, 300위≈0)하고, 속성을 파악한 상품끼리 비교해요.
    '전체 순위'는 신발·가방 등을 포함한 무신사 전체 랭킹 순위예요.
    핏·두께는 판매자가 입력한 값, 소재는 상품정보제공고시의 겉감 주원료, 실루엣·원단은 상품명과 상세 설명의 키워드로 분류해요.</p>
  </footer>
</div>
<div id="tip" hidden></div>
<script>{JS}</script>
"""


def page(body: str) -> str:
    return f"<!doctype html>\n<html lang=\"ko\">\n<head>\n{body}"  # 브라우저가 head/body를 알아서 닫음


def report_dates() -> list[str]:
    return sorted((p.stem for p in (DOCS_DIR / "reports").glob("*.html")), reverse=True)


def build(date: str) -> None:
    a = json.loads((TMP_DIR / f"analysis_{date}.json").read_text(encoding="utf-8"))
    (DOCS_DIR / "reports").mkdir(parents=True, exist_ok=True)
    dates = sorted(set(report_dates()) | {date}, reverse=True)

    (DOCS_DIR / "reports" / f"{date}.html").write_text(page(render(a, dates, "../")), encoding="utf-8")
    if date == dates[0]:
        (DOCS_DIR / "index.html").write_text(page(render(a, dates, "")), encoding="utf-8")
    (DOCS_DIR / "dates.json").write_text(json.dumps(dates), encoding="utf-8")
    old_archive = DOCS_DIR / "archive.html"
    if old_archive.exists():
        old_archive.unlink()  # 예전 '지난 리포트' 목록 → 날짜 선택으로 대체
    print(f"리포트 생성: {DOCS_DIR / 'index.html'} (날짜 {len(dates)}개)")


def embed_images(html: str) -> str:
    """외부 이미지를 막는 곳(Claude 링크 페이지 등)용: 상품 사진을 페이지 안에 넣는다.
    표 썸네일은 작은 사진(_125), 추천 카드는 큰 사진(_500)."""
    cache: dict[str, str] = {}

    def fetch(url: str) -> str:
        if url not in cache:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    cache[url] = "data:image/jpeg;base64," + base64.b64encode(resp.read()).decode()
                time.sleep(0.2)
            except Exception:
                cache[url] = ""
        return cache[url]

    def thumb(m: re.Match) -> str:
        small = re.sub(r"_500\.jpg$", "_125.jpg", m.group(1))
        return f"src='{fetch(small)}'"

    html = re.sub(r"src='(https://image\.msscdn\.net[^']+)'", thumb, html)
    return re.sub(r'src="(https://image\.msscdn\.net[^"]+)"', lambda m: f'src="{fetch(m.group(1))}"', html)


def build_standalone(date: str, out_path: str) -> None:
    """사진을 품은 한 장짜리 페이지 (날짜 선택 없음)."""
    a = json.loads((TMP_DIR / f"analysis_{date}.json").read_text(encoding="utf-8"))
    html = embed_images(render(a, None, ""))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"단독 페이지 생성: {out_path} ({len(html) / 1_000_000:.1f}MB)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_kst())
    parser.add_argument("--standalone", metavar="OUT", help="사진을 품은 단독 페이지로 저장")
    args = parser.parse_args()
    if args.standalone:
        build_standalone(args.date, args.standalone)
    else:
        build(args.date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
