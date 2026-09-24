"""상품 → 아이템 종류 / 핏 / 실루엣 / 주원료 / 원단·가공 / 컬러 / 디테일 / 두께 분류 Tool.

우선순위
- 아이템 종류: 상세정보의 공식 소분류 → 없으면 상품명 키워드
- 핏: 판매자가 입력한 핏(상세정보) → 없으면 상품명 키워드
- 주원료: 제품 소재 표기(상세정보) → 없으면 상품명 키워드
- 실루엣·원단/가공: 상품명 키워드 → 없으면 상세 설명 글 키워드
- 컬러·디테일: 상품명 키워드
- 두께: 상세정보

키워드 사전: tools/attribute_keywords.json (분류가 빠지면 이 파일에 키워드를 추가)

사용법(점검용): python tools/classify_attributes.py data/history/2026-09-24.csv
"""
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

KEYWORDS_PATH = Path(__file__).resolve().parent / "attribute_keywords.json"
KEYWORD_GROUPS = ("fit", "silhouette", "fiber", "texture", "color", "detail")
GROUPS = ("item_type", "fit", "silhouette", "fiber", "texture", "color", "detail", "thickness")
GROUP_LABELS = {"item_type": "아이템", "fit": "핏", "silhouette": "실루엣", "fiber": "소재(주원료)",
                "texture": "원단·가공", "color": "컬러", "detail": "디테일", "thickness": "두께"}


def _compile(keyword: str) -> re.Pattern:
    if keyword.startswith("re:"):
        return re.compile(keyword[3:], re.IGNORECASE)
    if re.fullmatch(r"[A-Za-z0-9 ./\-]+", keyword):
        # 영어는 단어 경계로: 'red'가 'tiered' 안에서 잡히지 않게
        return re.compile(r"(?<![a-z])" + re.escape(keyword.lower()) + r"(?![a-z])", re.IGNORECASE)
    return re.compile(re.escape(keyword), re.IGNORECASE)


@lru_cache(maxsize=1)
def load_rules() -> dict:
    raw = json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
    rules = {"item_type": {}}
    for cat_code, types in raw["item_type"].items():
        rules["item_type"][cat_code] = [(name, [_compile(k) for k in kws]) for name, kws in types.items()]
    for group in KEYWORD_GROUPS:
        rules[group] = [(name, _compile(k)) for name, kws in raw[group].items() for k in kws]
    return rules


OTHER_TYPE = {"001": "기타 상의", "002": "기타 아우터", "003": "기타 하의"}  # 무신사 공식 소분류 이름


def _item_type(name: str, category_code: str, category_name: str) -> str:
    """상세정보가 없을 때만 쓰는 대체 분류. 이름은 무신사 공식 소분류와 같게 맞춰 둠."""
    for type_name, patterns in load_rules()["item_type"].get(category_code, []):
        if any(p.search(name) for p in patterns):
            return type_name
    return OTHER_TYPE.get(category_code, f"기타 {category_name}")


def keywords(text: str, group: str) -> list[str]:
    """겹치는 매칭은 긴 쪽이 이김 ('크림화이트'는 화이트가 아니라 아이보리/크림)."""
    hits = []
    for canonical, pattern in load_rules()[group]:
        for m in pattern.finditer(text or ""):
            hits.append((m.end() - m.start(), m.start(), m.end(), canonical))
    hits.sort(key=lambda h: (-h[0], h[1]))
    taken: list[tuple[int, int]] = []
    found: list[str] = []
    for _, start, end, canonical in hits:
        if any(start < t_end and end > t_start for t_start, t_end in taken):
            continue
        taken.append((start, end))
        if canonical not in found:
            found.append(canonical)
    return found


def classify(product_name: str, category_code: str, category_name: str, detail: dict | None = None) -> dict:
    name = product_name or ""
    d = detail if detail and not detail.get("missing") else {}
    desc = d.get("desc", "")

    cat2 = d.get("category2", "")
    item_type = cat2 if cat2 and str(d.get("category2_code", "")).startswith(category_code) else \
        _item_type(name, category_code, category_name)

    fiber = [d["main_fiber"]] if d.get("main_fiber") else keywords(name, "fiber")
    return {
        "item_type": item_type,
        "fit": d.get("fit") or keywords(name, "fit"),
        "silhouette": keywords(name, "silhouette") or keywords(desc, "silhouette"),
        "fiber": fiber,
        "texture": keywords(name, "texture") or keywords(desc, "texture"),
        "color": keywords(name, "color"),
        "detail": keywords(name, "detail"),
        "thickness": d.get("thickness") or [],
    }


def main() -> int:
    import csv

    from common import DETAILS_PATH

    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    details = json.loads(DETAILS_PATH.read_text(encoding="utf-8")) if DETAILS_PATH.exists() else {}
    with open(sys.argv[1], encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    seen, samples = set(), []
    missing = {g: 0 for g in GROUPS}
    for r in rows:
        if r["product_id"] in seen:
            continue
        seen.add(r["product_id"])
        c = classify(r["product_name"], r["category_code"], r["category_name"], details.get(r["product_id"]))
        for g in GROUPS:
            missing[g] += not c[g]
        if len(samples) < 30:
            samples.append((r["product_name"], c))
    for name, c in samples:
        print(f"- {name}\n    {c}")
    n = len(seen)
    have = sum(1 for pid in seen if pid in details)
    print(f"\n고유 상품 {n}개 (상세정보 있음 {have}개)")
    for g in GROUPS:
        print(f"  {GROUP_LABELS[g]} 미분류: {missing[g] / n:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
