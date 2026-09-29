"""무신사 월간 랭킹 아카이브 리포트(한 장짜리 페이지) 생성 Tool.

입력
- .tmp/archive_analysis.json  (analyze_archive.py)
- data/archive_reasons.json   (Claude가 조사한 월별 배경·아이템별 원인·핵심 발견. 없으면 빈 칸으로 만듦)
- tools/archive_report_template.html (화면 틀)

출력 (2026-09-28 사장님 결정: GitHub 링크로)
- 기본: docs/archive/index.html → GitHub Pages https://lkw5406-png.github.io/musinsa-trend/archive/
  상품 사진은 무신사 작은 사진(_125) 주소를 그대로 불러옴 → 모든 상품에 사진.
- --embed: 외부 사진을 막는 곳(Claude 링크)용 한 장짜리. 사진을 WebP 96px로 줄여 페이지 안에 넣되,
  16MB 제한 때문에 꾸준템 · 달마다 대분류 TOP 5 · 원인 조사 후보에만. 줄인 사진은 .tmp/archive_thumbs/에 보관.
  사진 줄이기에 Pillow 필요 (없으면 _125 사진을 그대로 넣음).

사용법: python tools/build_archive_report.py [--embed] [--out 파일.html]
"""
import argparse
import base64
import io
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from common import DOCS_DIR, ROOT, TMP_DIR, USER_AGENT

ANALYSIS_PATH = TMP_DIR / "archive_analysis.json"
REASONS_PATH = ROOT / "data" / "archive_reasons.json"
PRICES_PATH = ROOT / "data" / "archive_prices.json"  # archive_prices.py (조회 시점 정가, 받는 중이면 받은 만큼)
TEMPLATE_PATH = Path(__file__).resolve().parent / "archive_report_template.html"
THUMB_DIR = TMP_DIR / "archive_thumbs"
PAGES_OUT = DOCS_DIR / "archive" / "index.html"
IMAGE_HOST = "https://image.msscdn.net/"
# GitHub Pages는 Claude 링크처럼 문서 뼈대를 붙여 주지 않으므로 직접 붙인다
PAGE_HEAD = ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
             '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
             '<meta name="robots" content="noindex">\n')
THUMB_WIDTH = 96
TOP_CATS = ("001", "002", "003", "100")
TOP_WITH_PHOTO = 5
NOTABLE_WITH_PHOTO = 8
MAX_PAGE_MB = 15


def photo_ids(a: dict) -> set[str]:
    ids = set()
    for g in a["genders"].values():
        ids.update(p["id"] for p in g["persistent"])
        for cat in TOP_CATS:
            for top in g["top"].get(cat, {}).values():
                ids.update(top[:TOP_WITH_PHOTO])
        for cands in g["notable"].values():
            ids.update(c["id"] for c in cands[:NOTABLE_WITH_PHOTO])
    return ids


def small_url(url: str) -> str:
    return re.sub(r"_\d+\.(jpg|png)$", r"_125.\1", url)


def thumb(pid: str, url: str) -> str:
    """상품 사진 → data: 주소. 실패하면 빈 문자열(페이지에선 브랜드 글자로 대신)."""
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    cached = THUMB_DIR / f"{pid}.webp"
    if not cached.exists():
        try:
            req = urllib.request.Request(small_url(url), headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
            time.sleep(0.2)
        except Exception:
            return ""
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            img.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 2))
            buf = io.BytesIO()
            img.save(buf, "WEBP", quality=72)
            cached.write_bytes(buf.getvalue())
        except ImportError:
            return "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    return "data:image/webp;base64," + base64.b64encode(cached.read_bytes()).decode()


def compact_products(products: dict, with_image_path: bool, prices: dict) -> dict:
    """페이지에 넣는 상품 정보. 사진은 무신사 주소 뒷부분만(i) 넣어 크기를 줄인다. p = 정가."""
    out = {}
    for pid, p in products.items():
        item = {"n": p["name"], "b": p["brand"], "c": p["cat"], "s": p["sub"]}
        if (prices.get(pid) or {}).get("normal"):
            item["p"] = prices[pid]["normal"]
        if p.get("discontinued"):
            item["x"] = 1
        if p.get("tags"):
            item["k"] = p["tags"]
        if with_image_path and p["image"].startswith(IMAGE_HOST):
            item["i"] = small_url(p["image"])[len(IMAGE_HOST):]
        out[pid] = item
    return out


def embedded_images(a: dict) -> dict:
    ids = photo_ids(a)
    print(f"사진 {len(ids)}장 준비 (처음이면 몇 분 걸림)")
    imgs = {}
    for i, pid in enumerate(sorted(ids), 1):
        uri = thumb(pid, a["products"][pid]["image"])
        if uri:
            imgs[pid] = uri
        if i % 200 == 0:
            print(f"  {i}/{len(ids)}")
    return imgs


def build(out_path: Path, embed: bool) -> None:
    a = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    reasons = json.loads(REASONS_PATH.read_text(encoding="utf-8")) if REASONS_PATH.exists() else {}
    imgs = embedded_images(a) if embed else {}
    prices = json.loads(PRICES_PATH.read_text(encoding="utf-8")) if PRICES_PATH.exists() else {}
    price_dates = sorted({v["at"] for v in prices.values() if v.get("normal")})
    data = {
        "months": a["months"], "categories": a["categories"],
        "products": compact_products(a["products"], not embed, prices), "genders": a["genders"],
        "reasons": reasons, "imgs": imgs, "image_host": IMAGE_HOST,
        "price_dates": [price_dates[0], price_dates[-1]] if price_dates else [],
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE_PATH.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    if not embed:
        head, sep, body = html.partition("</style>")
        html = PAGE_HEAD + head + sep + "\n</head>\n<body>\n" + body + "\n</body>\n</html>\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    size_mb = out_path.stat().st_size / 1_000_000
    print(f"리포트 생성: {out_path} ({size_mb:.1f}MB, {'사진 ' + str(len(imgs)) + '장 포함' if embed else '사진은 무신사 주소로'})")
    if embed and size_mb > MAX_PAGE_MB:
        raise RuntimeError(f"페이지가 {size_mb:.1f}MB — Claude 링크 제한(16MB)에 가까움. TOP_WITH_PHOTO를 줄일 것")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--embed", action="store_true", help="사진을 페이지 안에 넣은 한 장짜리(Claude 링크용)")
    parser.add_argument("--out", help="저장 위치 (기본: GitHub용 docs/archive/index.html, --embed면 .tmp/archive_report.html)")
    args = parser.parse_args()
    out = Path(args.out) if args.out else (TMP_DIR / "archive_report.html" if args.embed else PAGES_OUT)
    build(out, args.embed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
