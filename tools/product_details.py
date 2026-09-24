"""상품 상세정보 수집 Tool.

무신사 상품 상세 데이터(goods-detail.musinsa.com)에서 판매자가 입력한 정보를 가져와
data/product_details.json에 저장한다. 한 번 가져온 상품은 다시 요청하지 않는다.

가져오는 것
- 핏(스키니/슬림/레귤러/루즈/오버사이즈), 두께, 신축성, 비침, 촉감, 계절
- 제품 소재(상품정보제공고시) → 겉감의 주원료
- 공식 소분류(예: 긴소매 티셔츠), 성별
- 상세 설명 글(앞부분) → 상품명에 없는 실루엣·원단 키워드를 찾는 데 사용

사용법: python tools/product_details.py [--date YYYY-MM-DD] [--limit N]
  해당 날짜 랭킹 CSV에 있는 상품 중 아직 상세정보가 없는 것만 가져온다.
"""
import argparse
import csv
import json
import re
import sys
import time
from html import unescape

from common import DETAILS_PATH, HISTORY_DIR, TMP_DIR, BlockedError, get_json, today_kst

DETAIL_URL = "https://goods-detail.musinsa.com/api2/goods/{id}"
REQUEST_INTERVAL_SEC = 2
SAVE_EVERY = 25
DESC_CHARS = 600
CLOTHING_CODES = {"001", "002", "003", "100"}  # 상의, 아우터, 바지, 원피스/스커트 (스포츠/레저 017 등은 제외)
LOCK_PATH = TMP_DIR / "product_details.lock"
LOCK_STALE_SEC = 600  # 25개 저장마다 갱신(약 2분). 10분 넘게 안 바뀌면 멈춘 것으로 보고 새로 시작 허용

MATERIAL_FIELDS = {"핏": "fit", "두께": "thickness", "신축성": "stretch", "비침": "sheer", "촉감": "touch", "계절": "season"}

# 제품 소재 표기 → 대표 이름. 위에서부터 먼저 맞는 것.
FIBERS = [
    ("스판(폴리우레탄)", ["spandex", "polyurethane", "elastane", "스판", "폴리우레탄", "pu "]),
    ("합성피혁", ["합성피혁", "인조가죽", "synthetic leather", "faux leather", "vegan leather"]),
    ("가죽", ["leather", "가죽", "소가죽", "양가죽", "램스킨", "lambskin", "cowhide"]),
    ("캐시미어", ["cashmere", "캐시미어"]),
    ("울", ["wool", "울", "양모", "merino", "메리노", "lambswool"]),
    ("모헤어·알파카", ["mohair", "모헤어", "alpaca", "알파카", "angora", "앙고라"]),
    ("코튼", ["cotton", "코튼", "면"]),
    ("린넨", ["linen", "린넨", "리넨", "아마", "ramie", "라미"]),
    ("나일론", ["nylon", "나일론", "polyamide", "폴리아미드"]),
    ("레이온·모달·큐프라", ["rayon", "레이온", "viscose", "비스코스", "modal", "모달", "tencel", "텐셀",
                         "lyocell", "라이오셀", "cupro", "큐프라", "acetate", "아세테이트"]),
    ("아크릴", ["acrylic", "아크릴"]),
    ("실크", ["silk", "실크", "견"]),
    ("폴리에스터", ["polyester", "폴리에스터", "폴리에스테르", "polyeseter", "poly", "폴리"]),
]
# 겉감 이외 부분이 시작되는 표시 (안감·충전재·배색 등은 주원료 판단에서 뺀다)
NON_SHELL = re.compile(r"(lining|안감|filling|충전|padding|배색|trim|rib|립|포켓|pocket|주머니|심지)", re.I)


def clean_text(html: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", html or ""))
    return re.sub(r"\s+", " ", text.replace("﻿", "")).strip()


def fiber_name(word: str, exact: bool = False) -> str | None:
    """영어·긴 단어는 앞부분 일치(POLYESTER→poly), '면'·'견' 같은 한 글자는 정확히 일치할 때만."""
    w = word.lower().strip()
    for name, keys in FIBERS:
        for k in keys:
            k = k.strip()
            if w == k or (not exact and len(k) >= 2 and w.startswith(k)):
                return name
    return None


def _best_pair(pairs: list[tuple[str, str]]) -> tuple[str, int] | None:
    best = None
    for word, pct in pairs:
        name = fiber_name(word)
        if name and (best is None or float(pct) > best[1]):
            best = (name, float(pct))
    return (best[0], int(best[1])) if best else None


def main_fiber(material_text: str) -> tuple[str | None, int | None]:
    """'(OUTSHELL) NYLON 100% (LINING) ...' → ('나일론', 100). 겉감에서 비율이 가장 큰 섬유."""
    text = clean_text(material_text).replace("％", "%")
    cut = NON_SHELL.search(text)
    shell = text[:cut.start()] if cut and cut.start() > 0 else text
    for segment in (shell, text):
        # '면 80%' 형식을 먼저, 없을 때만 '80% 면' 형식
        found = _best_pair(re.findall(r"([A-Za-z가-힣]+)\s*[:\-]?\s*(\d{1,3}(?:\.\d+)?)\s*%", segment))
        if not found:
            found = _best_pair([(w, n) for n, w in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%\s*([A-Za-z가-힣]+)", segment)])
        if found:
            return found
    # 비율 없이 '면' 같은 이름만 적힌 경우
    for token in re.findall(r"[A-Za-z가-힣]+", shell):
        name = fiber_name(token, exact=True)
        if name:
            return name, None
    return None, None


def category1(detail: dict | None) -> str:
    """무신사 대분류 코드 (001 상의, 002 아우터, 003 바지, 100 원피스/스커트, 103 신발 …). 모르면 ''."""
    if not detail or detail.get("missing"):
        return ""
    return detail.get("category1_code") or str(detail.get("category2_code", ""))[:3]


def is_clothing(detail: dict | None) -> bool:
    return category1(detail) in CLOTHING_CODES


def fetch_detail(product_id: str) -> dict:
    goods = get_json(DETAIL_URL.format(id=product_id), allow_404=True)
    time.sleep(REQUEST_INTERVAL_SEC)
    if not goods or not goods.get("data"):
        return {"missing": True}

    d = goods["data"]
    cat = d.get("category") or {}
    out: dict = {
        "category1_code": cat.get("categoryDepth1Code", ""),
        "category1": cat.get("categoryDepth1Name", ""),
        "category2": cat.get("categoryDepth2Name", ""),
        "category2_code": cat.get("categoryDepth2Code", ""),
        "sex": d.get("sex") or [],
    }
    if out["category1_code"] not in CLOTHING_CODES:
        return out  # 신발·가방·뷰티 등: 의류인지 가리는 데만 쓰므로 여기까지 (요청 1번)

    essential = get_json(DETAIL_URL.format(id=product_id) + "/essential", allow_404=True)
    time.sleep(REQUEST_INTERVAL_SEC)
    out["desc"] = clean_text(d.get("goodsContents", ""))[:DESC_CHARS]
    for m in (d.get("goodsMaterial") or {}).get("materials") or []:
        key = MATERIAL_FIELDS.get(m.get("name"))
        if key:
            out[key] = [i["name"].replace("|", "") for i in m.get("items") or [] if i.get("isSelected")]

    material_raw = ""
    for e in ((essential or {}).get("data") or {}).get("essentials") or []:
        if e.get("name") == "제품 소재":
            material_raw = clean_text(e.get("value", ""))
    out["material_raw"] = material_raw[:200]
    out["main_fiber"], out["main_fiber_pct"] = main_fiber(material_raw)
    return out


def load_details() -> dict:
    if DETAILS_PATH.exists():
        return json.loads(DETAILS_PATH.read_text(encoding="utf-8"))
    return {}


def save_details(details: dict) -> None:
    DETAILS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DETAILS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(details, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    tmp.replace(DETAILS_PATH)


def _another_run_active() -> bool:
    """다른 수집이 최근 LOCK_STALE_SEC 안에 잠금 파일을 갱신했으면 돌고 있는 것으로 본다.
    (2026-09-24: 창을 다시 켤 때마다 새로 시작해 3개가 동시에 돌며 같은 파일을 덮어쓴 일이 있었음)"""
    return LOCK_PATH.exists() and time.time() - LOCK_PATH.stat().st_mtime < LOCK_STALE_SEC


def _touch_lock() -> None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(str(time.time()), encoding="utf-8")


def ensure_details(product_ids: list[str], details: dict, date: str) -> int:
    """아직 없는 상품만 상세정보를 받아 details에 채운다 (랭킹 수집 중 의류 판별용). 받은 개수를 돌려준다."""
    done = 0
    for pid in product_ids:
        if pid in details:
            continue
        info = fetch_detail(pid)
        info["fetched"] = date
        details[pid] = info
        done += 1
        if done % SAVE_EVERY == 0:
            save_details(details)
    save_details(details)
    return done


def update_details(date: str, limit: int | None = None) -> int:
    """해당 날짜 랭킹에서 상세정보가 없는 상품만 가져온다. 새로 가져온 개수를 돌려준다."""
    if _another_run_active():
        print("다른 상세정보 수집이 이미 돌고 있어서 이번엔 건너뜀 (잠금: .tmp/product_details.lock)")
        return 0
    _touch_lock()
    try:
        return _update_details(date, limit)
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def _update_details(date: str, limit: int | None) -> int:
    with open(HISTORY_DIR / f"{date}.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    details = load_details()
    # 높은 순위부터: 도중에 멈춰도 중요한 상품이 먼저 채워지게
    todo = []
    for r in sorted(rows, key=lambda r: int(r["rank"])):
        if r["product_id"] not in details and r["product_id"] not in todo:
            todo.append(r["product_id"])
    if limit:
        todo = todo[:limit]
    print(f"상세정보: 새 상품 {len(todo)}개 (이미 있음 {len(details)}개)", flush=True)

    done = 0
    try:
        for pid in todo:
            info = fetch_detail(pid)
            info["fetched"] = date
            details[pid] = info
            done += 1
            if done % SAVE_EVERY == 0:
                save_details(details)
                _touch_lock()
                print(f"  {done}/{len(todo)}", flush=True)
    finally:
        save_details(details)  # 차단·오류로 멈춰도 받은 만큼은 저장
    print(f"상세정보 저장 완료: {done}개 추가 → 총 {len(details)}개")
    return done


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_kst())
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    try:
        update_details(args.date, args.limit)
    except BlockedError as e:
        print(f"중단: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
