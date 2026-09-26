"""원인 조사용 웹 조회 Tool — 순위 급상승 원인(rise_reasons.py)을 조사할 때 유튜브를 빠르게 훑는다.
일반 웹 검색 결과는 한국 유튜브·SNS를 잘 못 잡아서(2026-09-27 확인), 유튜브 검색 결과·영상 설명란을 직접 읽는다.
영상 설명란에 소개 상품 목록(브랜드·상품명)이 적혀 있어 '어떤 영상이 이 상품을 소개했는지'를 확인할 수 있다.

사용법:
  python tools/web_research.py search "검색어" ["검색어2" ...] [--recent]   유튜브 검색 → 게시 시점·조회수·채널·제목·링크
  python tools/web_research.py video 영상ID [키워드 ...]                      게시일·조회수 + 설명란(키워드가 든 줄만)
  python tools/web_research.py channel 채널ID [키워드 ...]                    채널 최근 영상 15개 + 설명란(키워드 줄)
    --recent: '일 전/시간 전/1주 전' 영상만 (최근 1~2주)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept-Language": "ko-KR,ko;q=0.9"}
RECENT = re.compile(r"(분|시간|[1-9]일) 전|1주 전|스트리밍")


def fetch(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def text(o: dict) -> str:
    return o.get("simpleText") or "".join(r.get("text", "") for r in o.get("runs", []))


def search(q: str, recent: bool) -> list[str]:
    raw = fetch("https://www.youtube.com/results?hl=ko&gl=KR&search_query=" + urllib.parse.quote(q))
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", raw)
    if not m:
        return ["  (검색 결과를 못 읽음 — 유튜브가 막았거나 형식이 바뀜. 웹 검색으로 대신)"]
    out: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            v = o.get("videoRenderer")
            if v:
                pub = text(v.get("publishedTimeText", {}))
                if not recent or RECENT.search(pub):
                    out.append(f"  {pub:10} | {text(v.get('viewCountText', {})):14} | {text(v.get('ownerText', {}))} | "
                               f"{text(v.get('title', {}))} | https://youtu.be/{v.get('videoId')}")
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(json.loads(m.group(1)))
    return out[:15] or ["  (없음)"]


def video(vid: str, kws: list[str]) -> list[str]:
    raw = fetch(f"https://www.youtube.com/watch?v={vid}&hl=ko")
    m = re.search(r"var ytInitialPlayerResponse = (\{.*?\});(?:var|</script>)", raw)
    if not m:
        return [f"{vid}: 영상 정보를 못 읽음"]
    p = json.loads(m.group(1))
    vd, mf = p.get("videoDetails", {}), p.get("microformat", {}).get("playerMicroformatRenderer", {})
    lines = [f"{mf.get('publishDate', '')[:16]} | {vd.get('viewCount')}회 | {vd.get('author')} | {vd.get('title')} | https://youtu.be/{vid}"]
    lines += ["    " + ln.strip()[:220] for ln in vd.get("shortDescription", "").splitlines()
              if ln.strip() and (not kws or any(k.lower() in ln.lower() for k in kws))]
    return lines


def channel(ch: str, kws: list[str]) -> list[str]:
    ns = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/", "yt": "http://www.youtube.com/xml/schemas/2015"}
    root = ET.fromstring(fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={ch}"))
    lines = [root.findtext("a:title", namespaces=ns) or ch]
    for e in root.findall("a:entry", ns):
        g = e.find("m:group", ns)
        stats = g.find("m:community/m:statistics", ns)
        lines.append(f"\n{e.findtext('a:published', namespaces=ns)[:16]} | {stats.get('views') if stats is not None else '?'}회 | "
                     f"{e.findtext('a:title', namespaces=ns)} | https://youtu.be/{e.findtext('yt:videoId', namespaces=ns)}")
        lines += ["    " + ln.strip()[:220] for ln in g.findtext("m:description", default="", namespaces=ns).splitlines()
                  if ln.strip() and kws and any(k.lower() in ln.lower() for k in kws)]
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["search", "video", "channel"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--recent", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        if a.mode == "search":
            for q in a.args:
                print(f"\n=== {q}\n" + "\n".join(search(q, a.recent)), flush=True)
        else:
            print("\n".join((video if a.mode == "video" else channel)(a.args[0], a.args[1:])))
    except Exception as exc:  # 막히면 멈추고 알림 — 억지로 재시도하지 않음
        print(f"조회 실패: {exc} — 웹 검색(WebSearch)으로 대신 조사")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
