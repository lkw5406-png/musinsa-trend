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
  --c1: #2a78d6; --c2: #eb6834; --c3: #1baf7a; --c4: #eda100; --chip: rgba(42,120,214,0.16);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --bar: #3987e5; --accent: #3987e5; --up-text: #0ca30c; --down-text: #e66767;
    --c1: #3987e5; --c2: #d95926; --c3: #199e70; --c4: #c98500; --chip: rgba(57,135,229,0.30);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --bar: #3987e5; --accent: #3987e5; --up-text: #0ca30c; --down-text: #e66767;
  --c1: #3987e5; --c2: #d95926; --c3: #199e70; --c4: #c98500; --chip: rgba(57,135,229,0.30);
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
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
/* 상단 바: 성별 전환 + 목적별 탭 (스크롤해도 위에 붙어 있음) */
.topbar { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--page);
  margin: 22px 0 18px; padding: 10px 0; display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center;
  border-bottom: 1px solid var(--grid); }
.gswitch { display: inline-flex; flex: none; padding: 3px; border: 1px solid var(--border); border-radius: 999px;
  background: var(--surface); }
.gswitch button { font: inherit; font-weight: 700; padding: 6px 16px; border: 0; border-radius: 999px; cursor: pointer;
  background: transparent; color: var(--ink-2); }
.gswitch button[aria-pressed="true"] { background: var(--ink); color: var(--page); }
.tabs { display: flex; gap: 6px; flex: 1 1 0; min-width: 0; overflow-x: auto; scrollbar-width: none; }
.tabs::-webkit-scrollbar { display: none; }
.tabs button { flex: none; white-space: nowrap; font: inherit; font-weight: 600; padding: 7px 14px; border-radius: 999px;
  cursor: pointer; border: 1px solid var(--border); background: var(--surface); color: var(--ink-2); }
.tabs button small { font-size: 11px; color: var(--muted); margin-right: 6px; font-variant-numeric: tabular-nums; }
.tabs button[aria-selected="true"] { background: var(--ink); color: var(--page); border-color: var(--ink); }
.tabs button[aria-selected="true"] small { color: inherit; opacity: 0.7; }
.tabs button:focus-visible, .gswitch button:focus-visible, .row:focus-visible, select:focus-visible,
.chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
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
/* 카테고리 구성 막대 */
.mix { margin-top: 18px; }
.mix h3, .sec-h { font-size: 15px; margin: 0 0 8px; }
.mixbar { display: flex; gap: 2px; height: 26px; border-radius: 6px; overflow: hidden; }
.mixbar span { display: block; height: 100%; }
.mixlegend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 8px; font-size: 13px; color: var(--ink-2); }
.mixlegend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
.mixlegend b { color: var(--ink); font-variant-numeric: tabular-nums; }
/* 카테고리 탭 (TOP 10) */
.seg { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 14px; }
.seg button { font: inherit; font-size: 13px; font-weight: 600; padding: 6px 14px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--border); background: transparent; color: var(--ink-2); }
.seg button[aria-selected="true"] { background: var(--chip); color: var(--ink); border-color: var(--accent); }
.seg button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.topgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(170px, 100%), 1fr)); gap: 12px; }
.topcard { position: relative; text-decoration: none; color: inherit; border: 1px solid var(--border); border-radius: 12px;
  overflow: hidden; display: flex; flex-direction: column; background: var(--surface); }
.topcard:hover { border-color: var(--accent); }
.topcard .tlink { display: flex; flex-direction: column; text-decoration: none; color: inherit; }
.rv { border-top: 1px solid var(--grid); padding: 8px 11px 10px; font-size: 12px; display: flex; flex-direction: column;
  gap: 3px; color: var(--ink-2); }
.rv-h { color: var(--muted); font-variant-numeric: tabular-nums; }
.rv-s { color: var(--ink-2); }
.rv b { font-weight: 700; margin-right: 4px; }
.rv-p b { color: var(--up-text); } .rv-c b { color: var(--down-text); }
.rv-none { color: var(--muted); }
.rv details summary { cursor: pointer; color: var(--muted); margin-top: 2px; }
.rv .q { margin: 4px 0 0; padding-left: 8px; border-left: 2px solid var(--grid); line-height: 1.45; }
.rv .q.good { border-left-color: var(--up-text); } .rv .q.bad { border-left-color: var(--down-text); }
.topcard img { width: 100%; aspect-ratio: 1 / 1.15; object-fit: cover; background: var(--grid); display: block; }
.topcard .rk { position: absolute; top: 8px; left: 8px; background: var(--ink); color: var(--page); font-weight: 700;
  font-size: 13px; min-width: 26px; height: 26px; border-radius: 13px; display: grid; place-items: center; padding: 0 7px;
  font-variant-numeric: tabular-nums; }
.topcard .body { padding: 9px 11px 11px; display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
.topcard .brand { color: var(--muted); }
.topcard .name { font-size: 13px; font-weight: 600; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.topcard .meta { color: var(--ink-2); }
.topcard .price { font-weight: 700; font-size: 13px; }
/* 아이템 종류별 정리 */
.types { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(440px, 100%), 1fr)); gap: 14px; }
.type-cat { font-size: 15px; margin: 22px 0 10px; color: var(--ink-2); }
.type-cat:first-of-type { margin-top: 4px; }
.tcard { border: 1px solid var(--border); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 9px; min-width: 0; }
.tcard h4 { margin: 0; font-size: 16px; }
.tcard .ts { font-size: 12px; color: var(--muted); margin-top: 2px; }
.gallery { display: grid; grid-template-columns: repeat(6, 1fr); gap: 4px; }
.gallery img { width: 100%; aspect-ratio: 1 / 1.2; object-fit: cover; border-radius: 6px; background: var(--grid); display: block; }
.share-meter { height: 6px; background: var(--grid); border-radius: 3px; overflow: hidden; }
.share-meter span { display: block; height: 100%; background: var(--bar); border-radius: 0 3px 3px 0; }
.arow { display: grid; grid-template-columns: 78px 1fr; gap: 8px; align-items: start; font-size: 12px; }
.arow .al { color: var(--muted); padding-top: 3px; line-height: 1.3; }
.arow .al small { display: block; font-size: 10.5px; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { position: relative; overflow: hidden; border: 1px solid var(--border); border-radius: 6px; padding: 2px 8px;
  background: var(--surface); white-space: nowrap; }
.chip .fill { position: absolute; top: 0; bottom: 0; left: 0; background: var(--chip); }
.chip span { position: relative; }
.chip b { font-weight: 600; font-variant-numeric: tabular-nums; }
.sw { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px; vertical-align: 0;
  border: 1px solid var(--border); }
.none { color: var(--muted); padding-top: 3px; }
/* 가격대 */
.medians { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--ink-2); margin-top: 12px; }
.medians b { color: var(--ink); font-variant-numeric: tabular-nums; }
/* 오늘 요약 */
.brief { margin: 0; padding-left: 1.2em; display: flex; flex-direction: column; gap: 8px; font-size: 15px; }
.brief li::marker { color: var(--muted); }
/* 아이템 순위표 */
.rt td { white-space: nowrap; }
.rt td:nth-child(3) { white-space: normal; min-width: 110px; }
.mini { display: flex; align-items: center; gap: 8px; min-width: 130px; }
.mini-track { flex: 1; height: 8px; background: var(--grid); border-radius: 4px; overflow: hidden; }
.mini-track span { display: block; height: 100%; background: var(--bar); }
.mini b { font-variant-numeric: tabular-nums; min-width: 32px; text-align: right; }
tr.hi td { background: color-mix(in srgb, var(--up-text) 9%, transparent); }
/* 컬러 팔레트 */
.cov { font-size: 12px; color: var(--muted); margin: 0 0 10px; }
.palette { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(128px, 100%), 1fr)); gap: 10px; }
.pcell { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--surface); }
.pcell .sq { height: 60px; border-bottom: 1px solid var(--border); }
.pcell .pb { padding: 8px 10px 10px; display: flex; flex-direction: column; font-size: 13px; }
.pcell .pv { font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; }
.pcell .pn { font-size: 12px; color: var(--muted); display: flex; justify-content: space-between; gap: 6px; }
.more { display: block; margin: 14px auto 0; font: inherit; font-weight: 600; font-size: 14px; padding: 9px 22px;
  border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--ink); cursor: pointer; }
.more:hover { border-color: var(--accent); }
.more:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.pal-h { margin: 18px 0 8px; } .pal-h:first-of-type { margin-top: 0; }
.pal-h small { font-weight: 400; color: var(--muted); font-size: 12px; }
/* 아이템별 가격 */
.pt tr.grp td { font-weight: 700; color: var(--ink-2); padding-top: 14px; border-bottom: 1px solid var(--axis); }
.pt td.num { white-space: nowrap; }
.pr-cell { min-width: 140px; width: 34%; }
.prange { position: relative; height: 10px; background: var(--grid); border-radius: 5px; }
.prange span { position: absolute; top: 0; bottom: 0; background: var(--chip); border: 1px solid var(--accent); border-radius: 5px; }
.prange i { position: absolute; top: -3px; bottom: -3px; width: 2px; margin-left: -1px; background: var(--ink); border-radius: 1px; }
.prange i.o { width: 0; background: none; border-left: 2px dotted var(--down-text); }
footer { margin-top: 32px; font-size: 12px; color: var(--muted); max-width: 70ch; }
#tip { position: fixed; pointer-events: none; z-index: 20; background: var(--ink); color: var(--page);
  font-size: 12px; line-height: 1.5; padding: 8px 10px; border-radius: 8px; max-width: 260px; }
@media (max-width: 480px) {
  .row, .chg-head { grid-template-columns: 84px 1fr 38px 52px; }
  .wrap { padding: 20px 16px 48px; }
  .gallery { grid-template-columns: repeat(3, 1fr); }
  .gswitch button { padding: 6px 12px; }
  .tabs { flex-basis: 100%; }
}
"""

JS = """
// 성별 × 목적 탭. 주소 끝(#여성-소재컬러)으로 화면 공유, 마지막 화면은 이 브라우저에 기억
const G = [...document.querySelectorAll('.gswitch button')], T = [...document.querySelectorAll('.tabs button')];
let curG = G.length ? G[0].dataset.g : '0', curT = T.length ? T[0].dataset.t : '';
function viewHash() { const b = G.find(x => x.dataset.g === curG); return '#' + encodeURIComponent((b ? b.dataset.name : '') + '-' + curT); }
function apply(save) {
  G.forEach(b => b.setAttribute('aria-pressed', b.dataset.g === curG));
  T.forEach(b => b.setAttribute('aria-selected', b.dataset.t === curT));
  document.querySelectorAll('.panel').forEach(p => p.hidden = !(p.dataset.g === curG && p.dataset.t === curT));
  if (save) {
    try { history.replaceState(null, '', viewHash()); } catch (e) {}
    try { localStorage.setItem('mss-view', viewHash()); } catch (e) {}
  }
}
function fromHash(h) {
  if (!h) return false;
  let s; try { s = decodeURIComponent(h.replace(/^#/, '')); } catch (e) { return false; }
  const i = s.lastIndexOf('-'); if (i < 0) return false;
  const gb = G.find(b => b.dataset.name === s.slice(0, i)), tb = T.find(b => b.dataset.t === s.slice(i + 1));
  if (!gb || !tb) return false;
  curG = gb.dataset.g; curT = tb.dataset.t; return true;
}
function toTop() { const h = document.querySelector('header'); const y = h.offsetTop + h.offsetHeight;
  if (window.scrollY > y) window.scrollTo(0, y); }
G.forEach(b => b.addEventListener('click', () => { curG = b.dataset.g; apply(true); }));
T.forEach(b => b.addEventListener('click', () => { curT = b.dataset.t; apply(true); toTop();
  b.scrollIntoView({block: 'nearest', inline: 'nearest'}); }));
let saved = null; try { saved = localStorage.getItem('mss-view'); } catch (e) {}
fromHash(location.hash) || fromHash(saved);
apply(false);
window.addEventListener('hashchange', () => { if (fromHash(location.hash)) apply(false); });

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

// 카테고리 탭: 같은 섹션 안의 패널만 전환
document.querySelectorAll('.seg').forEach(seg => {
  const btns = seg.querySelectorAll('button');
  btns.forEach(b => b.addEventListener('click', () => {
    btns.forEach(x => x.setAttribute('aria-selected', x === b));
    seg.parentElement.querySelectorAll('.seg-panel').forEach(p => p.hidden = p.id !== b.dataset.show);
  }));
});

// 카테고리별 인기 TOP: 더보기 / 접기
document.querySelectorAll('.more').forEach(b => b.addEventListener('click', () => {
  const extra = b.parentElement.querySelectorAll('.extra'), open = extra.length && extra[0].hidden;
  extra.forEach(x => x.hidden = !open);
  b.textContent = open ? b.dataset.close : b.dataset.open;
}));

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
    location.href = (d === latest ? base + 'index.html' : base + 'reports/' + d + '.html') + viewHash();
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
    cov = f"상품 {group['coverage']:.0f}%에서 파악 · 파악된 상품 중 인기 비중"
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
            f'<div class="row" tabindex="0" data-tip="{e(tip)}"><span class="label">{swatch(r["name"])}{e(r["name"])}</span>'
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


COLOR_HEX = {  # 컬러 칩에 보여줄 실제 색 (대표색)
    "블랙": "#111111", "화이트": "#ffffff", "아이보리/크림": "#f1e8d4", "그레이/차콜": "#7d7d7d",
    "네이비": "#1f2a48", "블루/인디고": "#3e64a8", "브라운/카멜": "#8a5a2e", "베이지/샌드": "#d6c2a1",
    "카키/올리브": "#6b6a3a", "그린/민트": "#4e9a6c", "레드/버건디": "#9c2233", "핑크": "#f0a6b9",
    "퍼플/라벤더": "#8d6bb7", "옐로우/머스타드": "#dfb236", "오렌지": "#e77a2f",
}
PROFILE_ROWS = [("silhouette", "실루엣·기장"), ("texture", "원단"), ("fit", "핏"),
                ("fiber", "소재"), ("color", "컬러"), ("detail", "디테일")]
CAT_COLORS = {"001": "var(--c1)", "002": "var(--c2)", "003": "var(--c3)", "100": "var(--c4)"}


def swatch(name: str) -> str:
    hexv = COLOR_HEX.get(name)
    return f"<i class='sw' style='background:{hexv}'></i>" if hexv else ""


def mix_bar(mix: list[dict]) -> str:
    if not mix:
        return ""
    total = sum(m["count"] for m in mix) or 1
    segs, legend = [], []
    for m in mix:
        color = CAT_COLORS.get(m["code"], "var(--c1)")
        pct = 100 * m["count"] / total
        tip = f"<b>{m['name']}</b><br>{m['count']}개 ({pct:.0f}%) · 인기 비중 {m['share']:.0f}%"
        segs.append(f"<span style='flex:{m['count']};background:{color}' tabindex='0' data-tip='{e(tip)}'></span>")
        legend.append(f"<span><i style='background:{color}'></i>{e(m['name'])} <b>{m['count']}개</b> ({pct:.0f}%)</span>")
    return (f"<div class='mix'><h3>카테고리 구성</h3><div class='mixbar' role='img' aria-label='카테고리 구성'>"
            f"{''.join(segs)}</div><div class='mixlegend'>{''.join(legend)}</div></div>")


def top10_section(idx: int, cats: list[dict]) -> str:
    if not cats:
        return '<p class="empty">데이터가 없어요.</p>'
    btns, panels = [], []
    for i, c in enumerate(cats):
        pid = f"top-{idx}-{c['code']}"
        btns.append(f"<button type='button' data-show='{pid}' aria-selected='{str(i == 0).lower()}'>"
                    f"{e(c['name'])} <small>({c['count']})</small></button>")
        cards = []
        extra = len(c["products"]) - TOP_VISIBLE
        for n, p in enumerate(c["products"], 1):
            attrs = " · ".join(p.get("attrs") or [])
            attrs_html = f"<span class='meta'>{e(attrs)}</span>" if attrs else ""
            hide = " hidden" if n > TOP_VISIBLE else ""
            cards.append(
                f"<div class='topcard{' extra' if hide else ''}'{hide}>"
                f"<a class='tlink' href='{e(p['product_url'])}' target='_blank' rel='noopener'>"
                f"<span class='rk'>{n}</span>"
                f"<img src='{e(p['image_url'])}' alt='' loading='lazy' referrerpolicy='no-referrer'>"
                f"<div class='body'><span class='brand'>{e(p['brand'])}</span>"
                f"<span class='name'>{e(p['product_name'])}</span>"
                f"<span class='price'>{won(p['final_price'])}</span>"
                f"<span class='meta'>{e(p['item_type'])} · 전체 {p['rank']}위</span>{attrs_html}</div></a>"
                f"{review_html(p.get('review'))}</div>")
        hidden = "hidden" if i else ""
        more = (f"<button type='button' class='more' data-open='더보기 · {TOP_VISIBLE + 1}~{len(c['products'])}위' "
                f"data-close='접기'>더보기 · {TOP_VISIBLE + 1}~{len(c['products'])}위</button>") if extra > 0 else ""
        panels.append(f"<div class='seg-panel' id='{pid}' {hidden}><div class='topgrid'>{''.join(cards)}</div>{more}</div>")
    return f"<div><div class='seg' role='tablist'>{''.join(btns)}</div>{''.join(panels)}</div>"


def review_html(r: dict | None) -> str:
    """TOP 카드 아래 후기 요약: 설문 · 좋은 점 · 아쉬운 점 · 대표 후기."""
    if not r:
        return ""
    if not r.get("sampled"):
        return "<div class='rv'><span class='rv-none'>아직 후기가 없어요</span></div>"
    head = f"후기 {r['total']:,}개"
    if r.get("bad_pct") is not None:  # 3점 이하 후기 비율 (끝까지 못 셌으면 '이상')
        head += f" · 3점 이하 {r['bad_pct']:.0f}%" + ("" if r.get("bad_exact") else " 이상")
    survey = " · ".join(f"{e(s['attribute'])} {e(s['answer'])} {s['pct']}%" for s in (r.get("survey") or [])[:3])
    pros = " · ".join(e(x["name"]) for x in r.get("pros") or [])
    cons = " · ".join(e(x["name"]) for x in r.get("cons") or [])
    rows = [f"<div class='rv-h'>{head}</div>"]
    if survey:
        rows.append(f"<div class='rv-s'>{survey}</div>")
    rows.append(f"<div class='rv-p'><b>좋아요</b> {pros or '<span class=rv-none>특별히 많이 나온 말 없음</span>'}</div>")
    rows.append(f"<div class='rv-c'><b>아쉬워요</b> {cons or '<span class=rv-none>눈에 띄는 불만 없음</span>'}</div>")
    quotes = ""
    if r.get("good_quote"):
        quotes += f"<p class='q good'>“{e(r['good_quote'])}”</p>"
    if r.get("bad_quote"):
        quotes += f"<p class='q bad'>“{e(r['bad_quote'])}”</p>"
    if quotes:
        rows.append(f"<details><summary>대표 후기</summary>{quotes}</details>")
    return f"<div class='rv'>{''.join(rows)}</div>"


def chips_html(key: str, group: dict) -> str:
    vals = group.get("values") or []
    if not vals:
        return "<span class='none'>정보 없음</span>"
    out = []
    for v in vals:
        pct = min(100.0, v["pct"])
        sw = swatch(v["name"]) if key == "color" else ""
        tip = f"<b>{v['name']}</b><br>이 아이템 중 인기 비중 {v['pct']:.0f}% ({v['count']}개)"
        out.append(f"<span class='chip' tabindex='0' data-tip='{e(tip)}'><i class='fill' style='width:{pct:.0f}%'></i>"
                   f"<span>{sw}{e(v['name'])} <b>{v['pct']:.0f}%</b></span></span>")
    return f"<div class='chips'>{''.join(out)}</div>"


def price_section(pb: dict | None) -> str:
    if not pb or not pb.get("rows"):
        return '<p class="empty">데이터가 없어요.</p>'
    scale = max(pb["totals"]) or 1
    total_all = sum(pb["totals"]) or 1
    rows = []
    for i, label in enumerate(pb["labels"]):
        n = pb["totals"][i]
        detail = "<br>".join(f"{r['name']} {r['counts'][i]}개" for r in pb["rows"] if r["counts"][i])
        tip = f"<b>{label}</b><br>{n}개 ({100 * n / total_all:.0f}%)" + (f"<br>{detail}" if detail else "")
        rows.append(f"<div class='row' tabindex='0' data-tip='{e(tip)}'><span class='label'>{e(label)}</span>"
                    f"<span class='track'><span class='bar' style='width:{100 * n / scale:.1f}%'></span></span>"
                    f"<span class='val'>{n}개</span><span class='chg'>{100 * n / total_all:.0f}%</span></div>")
    medians = "".join(f"<span>{e(r['name'])} <b>{won(r['median'])}</b></span>" for r in pb["rows"] if r.get("median"))
    return f"<div>{''.join(rows)}<div class='medians'>카테고리별 중간 가격: {medians}</div></div>"


PURPOSES = [  # 목적별 탭 (주소 끝 #여성-소재컬러 처럼 공유 가능). 2026-09-25 디자이너 실무용으로 개편
    ("요약", "오늘 요약"),
    ("인기", "카테고리별 인기 TOP"),
    ("기획", "카테고리 순위"),
    ("디자인", "디자인 참고"),
    ("소재컬러", "소재·컬러"),
    ("가격", "가격"),
    ("동향", "시장 동향"),
]
DESIGN_CHARTS = [("fit", "핏"), ("silhouette", "실루엣·기장"), ("detail", "디테일")]
MATERIAL_CHARTS = [("texture", "원단·가공"), ("fiber", "소재(주원료)")]
TOP_VISIBLE = 20  # 카테고리별 인기 TOP: 처음 보이는 개수, 나머지는 '더보기'로 (최대 50)
BRIEF_MIN_PCT = 30  # 요약 문장에 넣을 아이템 속성의 최소 비중


def _rows(g: dict, group: str, n: int) -> list[dict]:
    return [r for r in g["attributes"][group]["rows"] if not r["name"].startswith("기타")][:n]


def brief_lines(g: dict) -> str:
    """오늘 요약: 회의에 그대로 옮겨 쓸 수 있는 문장 몇 줄."""
    types = sorted(g.get("item_types", []), key=lambda t: -t["share"])
    lines = []
    if types:
        rest = ", ".join(e(t["name"]) for t in types[1:3])
        lines.append(f"가장 인기 있는 아이템은 <b>{e(types[0]['name'])}</b>(인기 비중 {types[0]['share']:.0f}%)"
                     + (f", 이어서 {rest}." if rest else "."))
        top = types[0]
        spec = [f"{e(label)} <b>{e(v['name'])}</b> {v['pct']:.0f}%" for key, label in PROFILE_ROWS if key in top["groups"]
                for v in top["groups"][key]["values"][:1] if v["pct"] >= BRIEF_MIN_PCT]
        if spec:
            lines.append(f"{e(top['name'])} 특징: " + " · ".join(spec))
    rising = sorted((t for t in types if (t.get("dod_pp") or 0) >= 0.5), key=lambda t: -t["dod_pp"])[:3]
    if rising:
        lines.append("어제보다 오른 아이템: " + ", ".join(
            f"<b>{e(t['name'])}</b> <span class='up-t'>▲{t['dod_pp']:.1f}%p</span>" for t in rising))
    colors = _rows(g, "color", 3)
    if colors:
        lines.append("많이 팔린 컬러: " + " · ".join(f"{swatch(r['name'])}{e(r['name'])} {r['share']:.0f}%" for r in colors))
    textures = _rows(g, "texture", 3)
    if textures:
        lines.append("많이 쓰인 원단: " + " · ".join(f"{e(r['name'])} {r['share']:.0f}%" for r in textures))
    pb = g.get("price_bands") or {}
    if pb.get("totals") and sum(pb["totals"]):
        i = max(range(len(pb["totals"])), key=lambda k: pb["totals"][k])
        pct = 100 * pb["totals"][i] / sum(pb["totals"])
        median = f"중간 가격 <b>{won(pb['median'])}</b> · " if pb.get("median") else ""
        lines.append(f"{median}가장 많은 가격대 {e(pb['labels'][i])} ({pct:.0f}%)")
    if not lines:
        return '<p class="empty">데이터가 없어요.</p>'
    return "<ul class='brief'>" + "".join(f"<li>{x}</li>" for x in lines) + "</ul>"


def item_rank_table(types: list[dict], has_yesterday: bool) -> str:
    """무엇을 만들까: 아이템 종류를 인기 비중 순으로. 어제보다 0.5%p 이상 오른 아이템은 강조."""
    if not types:
        return '<p class="empty">데이터가 없어요.</p>'
    types = sorted(types, key=lambda t: -t["share"])
    scale = max(t["share"] for t in types) or 1
    body = []
    for n, t in enumerate(types, 1):
        first = t["top_products"][0] if t["top_products"] else None
        img = (f"<a href='{e(first['product_url'])}' target='_blank' rel='noopener'>"
               f"<img src='{e(first['image_url'])}' alt='' loading='lazy' referrerpolicy='no-referrer'></a>") if first else ""
        hi = " class='hi'" if (t.get("dod_pp") or 0) >= 0.5 else ""
        body.append(
            f"<tr{hi}><td class='num'>{n}</td><td>{img}</td>"
            f"<td><b>{e(t['name'])}</b><br><small style='color:var(--muted)'>{e(t['category_name'])}</small></td>"
            f"<td><div class='mini'><span class='mini-track'><span style='width:{100 * t['share'] / scale:.0f}%'></span></span>"
            f"<b>{t['share']:.0f}%</b></div></td>"
            f"<td class='num'>{change_html(t.get('dod_pp')) if has_yesterday else '–'}</td>"
            f"<td class='num'>{t['count']}개</td><td class='num'>{won(t.get('median_price'))}</td>"
            f"<td class='num'>{t['best_rank']}위</td></tr>")
    head = ("<th class='num'>#</th><th></th><th>아이템</th><th>인기 비중</th><th class='num'>어제 대비(%p)</th>"
            "<th class='num'>상품 수</th><th class='num'>중간 가격</th><th class='num'>최고 전체 순위</th>")
    return (f"<div class='table-wrap'><table class='rt'><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def item_card(p: dict, max_share: float) -> str:
    dod = f" · 어제 대비 {change_html(p['dod_pp'])}%p" if p.get("dod_pp") is not None else ""
    median = f" · 중간 가격 {won(p['median_price'])}" if p.get("median_price") else ""
    gallery = "".join(
        f"<a href='{e(t['product_url'])}' target='_blank' rel='noopener' title='{e(t['brand'])} {e(t['product_name'])}'>"
        f"<img src='{e(t['image_url'])}' alt='' loading='lazy' referrerpolicy='no-referrer'></a>"
        for t in p["top_products"])
    rows = "".join(
        f"<div class='arow'><span class='al'>{e(label)}<small>파악 {p['groups'][key]['coverage']}%</small></span>"
        f"{chips_html(key, p['groups'][key])}</div>" for key, label in PROFILE_ROWS if key in p["groups"])
    return (f"<div class='tcard'><div class='tt'><h4>{e(p['name'])}</h4>"
            f"<div class='ts'>{p['count']}개 · 인기 비중 {p['share']:.0f}%{median} · 최고 전체 {p['best_rank']}위{dod}</div></div>"
            f"<div class='share-meter' title='인기 비중'><span style='width:{100 * p['share'] / max_share:.0f}%'></span></div>"
            f"<div class='gallery'>{gallery}</div>{rows}</div>")


def design_section(gi: int, profiles: list[dict]) -> str:
    """디자인 참고: 카테고리 버튼으로 걸러 보는 아이템별 스펙 카드."""
    if not profiles:
        return '<p class="empty">데이터가 없어요.</p>'
    max_share = max(p["share"] for p in profiles) or 1
    cats: dict[str, list[dict]] = {}
    for p in profiles:
        cats.setdefault(p["category_name"], []).append(p)
    btns, panels = [], []
    for i, (name, items) in enumerate(cats.items()):
        pid = f"dz-{gi}-{i}"
        btns.append(f"<button type='button' data-show='{pid}' aria-selected='{str(i == 0).lower()}'>"
                    f"{e(name)} <small>({len(items)})</small></button>")
        cards = "".join(item_card(p, max_share) for p in items)
        panels.append(f"<div class='seg-panel' id='{pid}' {'hidden' if i else ''}><div class='types'>{cards}</div></div>")
    return f"<div><div class='seg' role='tablist'>{''.join(btns)}</div>{''.join(panels)}</div>"


def palette(group: dict, has_trend: bool) -> str:
    rows = [r for r in group["rows"] if r["name"] in COLOR_HEX]
    if not rows:
        return '<p class="empty">데이터가 부족해요.</p>'
    cells = []
    for r in rows:
        change = r["week_pp"] if r["week_pp"] is not None else r["dod_pp"]
        chg = f"<span class='pc'>{change_html(change)}%p</span>" if has_trend else ""
        cells.append(f"<div class='pcell'><div class='sq' style='background:{COLOR_HEX[r['name']]}'></div>"
                     f"<div class='pb'><span>{e(r['name'])}</span><span class='pv'>{r['share']:.0f}%</span>"
                     f"<span class='pn'>{r['count']}개{chg}</span></div></div>")
    return (f"<p class='cov'>상품 {group['coverage']:.0f}%에서 파악 · 파악된 상품 중 인기 비중</p>"
            f"<div class='palette'>{''.join(cells)}</div>")


def item_price_table(types: list[dict]) -> str:
    """아이템별 가격: 중간 가격과 주로 팔리는 가격 범위(가운데 50%)를 막대로."""
    rows = [t for t in types if t.get("median_price")]
    if not rows:
        return '<p class="empty">데이터가 없어요.</p>'
    top = max(max(t.get("price_high") or 0, t.get("median_original") or 0, t["median_price"]) for t in rows) or 1
    body, current = [], None
    for t in rows:
        if t["category_name"] != current:
            current = t["category_name"]
            body.append(f"<tr class='grp'><td colspan='6'>{e(current)}</td></tr>")
        lo, hi = t.get("price_low"), t.get("price_high")
        rng = f"{won(lo)} ~ {won(hi)}" if lo and hi else "<span class='flat-t'>상품이 적어 생략</span>"
        bar = ""
        if lo and hi:
            bar = (f"<span style='left:{100 * lo / top:.1f}%;width:{max(1.0, 100 * (hi - lo) / top):.1f}%'></span>")
        bar += f"<i style='left:{100 * t['median_price'] / top:.1f}%'></i>"
        orig = t.get("median_original")
        if orig:
            bar += f"<i class='o' style='left:{min(100.0, 100 * orig / top):.1f}%'></i>"
        disc = f"{t['discount_avg']:.0f}%" if t.get("discount_avg") is not None else "–"
        body.append(f"<tr><td><b>{e(t['name'])}</b> <small style='color:var(--muted)'>{t['count']}개</small></td>"
                    f"<td class='num'><b>{won(t['median_price'])}</b></td><td class='num'>{won(orig) or '–'}</td>"
                    f"<td class='num'>{disc}</td><td class='num'>{rng}</td>"
                    f"<td class='pr-cell'><div class='prange'>{bar}</div></td></tr>")
    head = ("<th>아이템</th><th class='num'>실판매가(중간)</th><th class='num'>정가(중간)</th><th class='num'>평균 할인율</th>"
            "<th class='num'>주로 팔리는 실판매가</th><th>분포</th>")
    return (f"<div class='table-wrap'><table class='pt'><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def big_category_charts(gi: int, g: dict) -> str:
    """디자인 참고: 아우터/상의/하의 버튼으로 바꿔 보는 핏·실루엣·디테일 순위."""
    cats = g.get("big_categories") or []
    if not cats:
        return '<p class="empty">데이터가 없어요.</p>'
    btns, panels = [], []
    for i, c in enumerate(cats):
        pid = f"bc-{gi}-{i}"
        btns.append(f"<button type='button' data-show='{pid}' aria-selected='{str(i == 0).lower()}'>"
                    f"{e(c['name'])} <small>({c['count']})</small></button>")
        charts = "".join(share_chart(title, c["attributes"][key], "어제", g["has_trend"]) for key, title in DESIGN_CHARTS)
        panels.append(f"<div class='seg-panel' id='{pid}' {'hidden' if i else ''}><div class='charts'>{charts}</div></div>")
    return f"<div><div class='seg' role='tablist'>{''.join(btns)}</div>{''.join(panels)}</div>"


def big_category_palettes(g: dict) -> str:
    """소재·컬러: 아우터/상의/하의 컬러 팔레트를 차례로."""
    cats = g.get("big_categories") or []
    if not cats:
        return '<p class="empty">데이터가 없어요.</p>'
    return "".join(f"<h3 class='sec-h pal-h'>{e(c['name'])} <small>{c['count']}개</small></h3>"
                   f"{palette(c['attributes']['color'], g['has_trend'])}" for c in cats)


def charts_html(g: dict, groups: list[tuple[str, str]]) -> str:
    return "".join(share_chart(title, g["attributes"][key], g["trend_label"], g["has_trend"]) for key, title in groups)


def gender_panels(gi: int, gender: str, g: dict, has_yesterday: bool) -> str:
    if g["has_trend"]:
        chart_sub = (f"막대 = 인기 비중(순위가 높을수록 크게 반영). 오른쪽 숫자 = {e(g['trend_label'])} 변화(%p). "
                     "막대에 마우스를 올리면 자세한 수치.")
        head_sub = f"{e(g['trend_label'])} 가장 많이 늘어난 속성"
    else:
        chart_sub = "막대 = 인기 비중(순위가 높을수록 크게 반영). 어제 대비 변화는 기록이 쌓이면 표시돼요."
        head_sub = "오늘 랭킹에서 비중이 가장 큰 속성"
    no_yday = "어제 기록이 없어 내일부터 표시돼요."
    trend_word = "뜨는" if g["has_trend"] else "인기"
    types = g.get("item_types", [])
    body = {
        "요약": f"""
  <section class="card">
    <h2>{e(gender)} · 오늘 요약</h2>
    <p class="sub">1일 랭킹 의류 {g['count']}개 기준 · 회의 자료에 그대로 옮겨 쓸 수 있게 정리했어요.</p>
    {brief_lines(g)}
  </section>
  <section class="card">
    <h2>핵심 지표</h2>
    <p class="sub">{head_sub}</p>
    {headline_cards(g['headlines'])}
    {mix_bar(g.get('category_mix', []))}
  </section>""",
        "인기": f"""
  <section class="card">
    <h2>카테고리별 인기 TOP {TOP_VISIBLE}</h2>
    <p class="sub">카테고리를 눌러 바꿔 보세요. 맨 아래 '더보기'로 50위까지. 번호 = 카테고리 안 순위, '전체 N위' = 신발·가방 등을 포함한 무신사 전체 순위.
    카드 아래 후기 요약(50위까지) = 도움순 후기 50개·별점 낮은 후기 최대 50개에서 자주 나온 표현(좋아요 = 4~5점 후기, 아쉬워요 = 3점 이하 후기)과 구매자 설문 결과.</p>
    {top10_section(gi, g.get('top_by_category', []))}
  </section>""",
        "기획": f"""
  <section class="card">
    <h2>아이템 순위</h2>
    <p class="sub">어떤 아이템이 잘 팔리는지 인기 비중 순으로. 초록 줄 = 어제보다 0.5%p 이상 오른 아이템. 3개 이상 오른 아이템만.</p>
    {item_rank_table(types, has_yesterday)}
  </section>
  <section class="card">
    <h2>추천 아이템</h2>
    <p class="sub">순위가 높고 {trend_word} 속성을 많이 가진 상품 (아이템 종류별 1개)</p>
    {rec_cards(g['recommendations'])}
  </section>""",
        "디자인": f"""
  <section class="card">
    <h2>아이템별 스펙</h2>
    <p class="sub">카테고리를 눌러 바꿔 보세요. 사진 = 그 아이템에서 잘 팔리는 순서. 칩의 % = 그 아이템 중 해당 속성의 인기 비중(파악된 상품 기준). 실루엣·기장은 팬츠류만.</p>
    {design_section(gi, types)}
  </section>
  <section class="card">
    <h2>대분류별 핏 · 실루엣 · 디테일</h2>
    <p class="sub">아우터 / 상의 / 하의(바지·스커트)를 눌러 바꿔 보세요. {chart_sub}</p>
    {big_category_charts(gi, g)}
  </section>""",
        "소재컬러": f"""
  <section class="card">
    <h2>컬러 팔레트</h2>
    <p class="sub">대분류별로 잘 팔리는 컬러를 인기 비중 순으로. 여러 색으로 파는 상품은 판매 중인 색을 모두 셌어요.{' 작은 숫자 = 어제 대비 변화.' if g['has_trend'] else ''}</p>
    {big_category_palettes(g)}
  </section>
  <section class="card">
    <h2>원단 · 소재</h2>
    <p class="sub">{chart_sub} 소재 = 상품정보제공고시의 겉감 주원료.</p>
    <div class="charts">{charts_html(g, MATERIAL_CHARTS)}</div>
  </section>""",
        "가격": f"""
  <section class="card">
    <h2>아이템별 가격</h2>
    <p class="sub">실판매가 = 할인이 적용된 지금 가격, 정가 = 할인 전 원래 가격. 주로 팔리는 실판매가 = 가운데 절반의 상품이 들어가는 범위. 막대: 파란 칸 = 주로 팔리는 실판매가, 검은 선 = 실판매가 중간, 빨간 점선 = 정가 중간.</p>
    {item_price_table(types)}
  </section>
  <section class="card">
    <h2>가격대 분포</h2>
    <p class="sub">막대 = 상품 수. 마우스를 올리면 카테고리별 개수가 나와요.</p>
    {price_section(g.get('price_bands'))}
  </section>""",
        "동향": f"""
  <section class="card two">
    {product_table('어제보다 순위가 크게 오른 상품', g['movers'], extra_col='변화', empty=no_yday if not has_yesterday else '')}
    {product_table('오늘 새로 TOP 50에 진입', g['new_entries'], empty=no_yday if not has_yesterday else '')}
  </section>""",
    }
    return "".join(
        f'<div class="panel" data-g="{gi}" data-t="{key}" role="tabpanel" {"" if gi == 0 and n == 0 else "hidden"}>{body[key]}</div>'
        for n, (key, _) in enumerate(PURPOSES))


def render(a: dict, dates: list[str] | None, base: str) -> str:
    genders = list(a["genders"].items())
    gswitch = "".join(
        f'<button type="button" data-g="{i}" data-name="{e(name)}" aria-pressed="{str(i == 0).lower()}">{e(name)}</button>'
        for i, (name, _) in enumerate(genders))
    tabs = "".join(
        f'<button type="button" role="tab" data-t="{key}" aria-selected="{str(n == 0).lower()}">'
        f'<small>{n + 1}</small>{e(label)}</button>' for n, (key, label) in enumerate(PURPOSES))
    panels = "".join(gender_panels(i, name, g, a["has_yesterday"]) for i, (name, g) in enumerate(genders))
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
  <div class="topbar">
    <div class="gswitch" role="group" aria-label="성별">{gswitch}</div>
    <nav class="tabs" role="tablist" aria-label="목적">{tabs}</nav>
  </div>
  {panels}
  <footer>
    <p>매일 오전 10시 기준 무신사 전체 랭킹(최근 1일)을 모아 날짜별로 쌓아요. 남성·여성은 무신사 성별 랭킹 그대로예요.
    '인기 비중'은 순위가 높을수록 크게 반영한 비중(의류 중 1위=1, 300위≈0)이고, 속성을 파악한 상품끼리 비교해요.
    '전체 순위'는 신발·가방 등을 포함한 무신사 전체 랭킹 순위예요.
    핏·두께는 판매자가 입력한 값, 소재는 상품정보제공고시의 겉감 주원료, 실루엣·원단은 상품명·상세 설명·실측 사이즈표로 분류해요.
    보고 있는 화면의 주소를 복사하면 같은 성별·탭이 열려요.</p>
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
