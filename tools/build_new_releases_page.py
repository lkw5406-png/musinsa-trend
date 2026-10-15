"""그해 신상 랭킹 진입 페이지(Claude 링크용 한 장짜리) 생성 Tool.

입력: .tmp/new_releases_<연도>.json (tools/new_releases.py), data/archive_prices.json (정가, 만들 때 다시 읽음),
      data/new_release_reasons_<연도>.json (랭킹에 오른 이유, tools/new_release_reasons.py — 카드의 '이유' 버튼)
틀: tools/new_releases_template.html
출력 (한 번에 둘 다)
- .tmp/new_releases_<연도>.html → Claude 링크로 올림 (Artifact). 사진을 페이지 안에 넣음
- docs/new-releases/index.html → GitHub Pages https://lkw5406-png.github.io/musinsa-trend/new-releases/
  (2026-10-15 사장님: 깃허브로도). 사진은 무신사 220px 사진 주소를 그대로 불러옴(1장 약 46KB, 늦게 불러오기)

- Claude 링크는 외부 사진을 막으므로 사진을 줄여(무신사 500px 사진을 WebP 가로 180px로) 페이지 안에 넣는다. 줄인 사진은 .tmp/new_release_thumbs/에 보관.
  상품 1,000개 기준 약 5MB (16MB 제한). Pillow 필요.

사용법: python tools/build_new_releases_page.py [--year 2026] [--thumbs-only]
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

from build_archive_report import PAGE_HEAD
from common import DOCS_DIR, ROOT, TMP_DIR, USER_AGENT

PRICES_PATH = ROOT / "data" / "archive_prices.json"
TEMPLATE_PATH = Path(__file__).resolve().parent / "new_releases_template.html"
THUMB_DIR = TMP_DIR / "new_release_thumbs"
THUMB_WIDTH = 180
MAX_PAGE_MB = 15
PAGES_OUT = DOCS_DIR / "new-releases" / "index.html"


def thumb(pid: str, url: str) -> str:
    """상품 사진 → data: 주소 (실패하면 빈 문자열)."""
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    cached = THUMB_DIR / f"{pid}.webp"
    if not cached.exists():
        src = re.sub(r"_\d+\.(jpg|png)$", r"_500.\1", url)  # 250px 사진은 무신사에 없음(404)
        try:
            req = urllib.request.Request(src, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
            time.sleep(0.15)
        except Exception:
            return ""
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 2))
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=66)
        cached.write_bytes(buf.getvalue())
    return "data:image/webp;base64," + base64.b64encode(cached.read_bytes()).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2026")
    ap.add_argument("--thumbs-only", action="store_true", help="사진만 미리 받기")
    args = ap.parse_args()
    data = json.loads((TMP_DIR / f"new_releases_{args.year}.json").read_text(encoding="utf-8"))
    prices = json.loads(PRICES_PATH.read_text(encoding="utf-8")) if PRICES_PATH.exists() else {}
    rpath = ROOT / "data" / f"new_release_reasons_{args.year}.json"
    reasons = json.loads(rpath.read_text(encoding="utf-8")) if rpath.exists() else {}

    items, imgs, web_imgs = {}, {}, {}
    for i, (pid, p) in enumerate(data["products"].items(), 1):
        uri = thumb(pid, p["image"])
        if uri:
            imgs[pid] = uri
        web_imgs[pid] = re.sub(r"_\d+\.(jpg|png)$", r"_220.\1", p["image"])
        if i % 200 == 0:
            print(f"  사진 {i}/{len(data['products'])}", flush=True)
        price = (prices.get(pid) or {}).get("normal")
        q = reasons.get(pid)
        why = {"c": q["causes"], "cf": q["confidence"], "pt": q["points"], "r": q["reason"],
               "src": [[x["title"], x["url"]] for x in q.get("sources", [])]} if q else None
        items[pid] = {"b": p["brand"], "n": p["name"], "d": p["reg"], "c": p["cat"], "s": p["sub"],
                      "f": p["first"], "r": p["ranks"], **({"p": price} if price else {}), **({"x": 1} if p["discontinued"] else {}),
                      **({"q": why} if why else {})}
    if args.thumbs_only:
        print(f"사진 {len(imgs)}/{len(items)}장 준비")
        return 0

    import new_release_reasons as nrr
    payload = {"reason_targets": len(nrr.targets(args.year)), "reason_done": sum(1 for x in items.values() if "q" in x),
               "reason_rank": nrr.BEST_RANK, "year": data["year"], "gender": data["gender"], "months": data["months"], "cats": data["cats"],
               "excluded": data["excluded_sports"], "items": items}
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    def page(img_map: dict) -> str:
        return (template.replace("/*__DATA__*/null", data_js)
                .replace("/*__IMGS__*/null", json.dumps(img_map, separators=(",", ":"))))

    # GitHub Pages: 문서 뼈대를 직접 붙이고 사진은 무신사 주소로
    head, sep, body = page(web_imgs).partition("</style>")
    PAGES_OUT.parent.mkdir(parents=True, exist_ok=True)
    PAGES_OUT.write_text(PAGE_HEAD + head + sep + "\n</head>\n<body>\n" + body + "\n</body>\n</html>\n", encoding="utf-8")
    print(f"GitHub 페이지: {PAGES_OUT} ({PAGES_OUT.stat().st_size / 1e6:.1f}MB)")

    out = TMP_DIR / f"new_releases_{args.year}.html"
    out.write_text(page(imgs), encoding="utf-8")
    mb = out.stat().st_size / 1e6
    print(f"페이지: {out} ({mb:.1f}MB, 상품 {len(items)}개 · 사진 {len(imgs)}장 · 정가 {sum(1 for x in items.values() if 'p' in x)}개 · 이유 {payload['reason_done']}/{payload['reason_targets']}개)")
    if mb > MAX_PAGE_MB:
        print("16MB 제한에 가까움 — THUMB_WIDTH를 줄일 것")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
