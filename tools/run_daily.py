"""매일 실행 Tool — 랭킹 수집 → 상세정보 수집 → 분석 → 리포트 생성.

사용법:
  python tools/run_daily.py                 전체 실행
  python tools/run_daily.py --skip-fetch    이미 받은 오늘 랭킹으로 (상세정보 → 분석 → 리포트)
  python tools/run_daily.py --alert-on-fail 실패하면 알림 메일 (클라우드 자동 실행용)

리포트는 고정 주소(docs/index.html) 하나에 날짜별로 쌓이므로 매일 링크를 보내지 않는다.
"""
import argparse
import json
import sys
import traceback

import analyze_trends
import build_report
import musinsa_fetch
import product_details
import send_email
from common import TMP_DIR, BlockedError, today_kst


def run(date: str, skip_fetch: bool) -> None:
    if not skip_fetch:
        print("1/4 랭킹 수집 (최근 1일)")
        rows = musinsa_fetch.collect(date)
        musinsa_fetch.validate(rows)
        musinsa_fetch.save_csv(rows, date)
    print("2/4 상세정보 수집 (처음 보는 상품만)")
    product_details.update_details(date)
    print("3/4 트렌드 분석")
    TMP_DIR.mkdir(exist_ok=True)
    result = analyze_trends.analyze(date)
    (TMP_DIR / f"analysis_{date}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("4/4 리포트 생성")
    build_report.build(date)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_kst())
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--alert-on-fail", action="store_true")
    args = parser.parse_args()

    try:
        run(args.date, args.skip_fetch)
    except Exception as exc:
        traceback.print_exc()
        if args.alert_on_fail:
            if isinstance(exc, BlockedError):
                reason = ("무신사가 데이터 요청을 거부했습니다. 억지로 다시 시도하지 않고 멈췄습니다.\n"
                          f"상세: {exc}")
            else:
                reason = f"{type(exc).__name__}: {exc}"
            try:
                send_email.send(f"[무신사 트렌드] ⚠ {args.date} 자동 실행 실패", reason)
            except Exception:
                traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
