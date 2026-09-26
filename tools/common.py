"""여러 Tool이 같이 쓰는 경로, 날짜, .env 읽기, 무신사 데이터 요청."""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "data" / "history"  # 일간 랭킹 (주간·월간은 history_path로)
UPDATES_PATH = ROOT / "data" / "ranking_updates.json"
DETAILS_PATH = ROOT / "data" / "product_details.json"
RISE_REASONS_PATH = ROOT / "data" / "rise_reasons.json"  # 순위 급상승 원인 (Claude 조사, rise_reasons.py)
TMP_DIR = ROOT / ".tmp"
DOCS_DIR = ROOT / "docs"

KST = timezone(timedelta(hours=9))

# 랭킹 기간 (2026-09-25: 일간·주간·월간 모두 매일 수집, 리포트는 일간 매일 · 주간 월요일 · 월간 1일)
# 이름 → (무신사 period 값, 한글 이름, 무신사 표시, 이전 비교 말, 다음 말)
PERIODS = {
    "daily": ("DAILY", "일간", "최근 1일", "어제", "내일"),
    "weekly": ("WEEKLY", "주간", "최근 1주일", "지난주", "다음 주"),
    "monthly": ("MONTHLY", "월간", "최근 1개월", "지난달", "다음 달"),
}


def history_dir(period: str = "daily") -> Path:
    return HISTORY_DIR if period == "daily" else ROOT / "data" / f"history_{period}"


def history_path(date: str, period: str = "daily") -> Path:
    return history_dir(period) / f"{date}.csv"

# 봇 위장 없음: 누가 왜 요청하는지 그대로 밝힌다
USER_AGENT = "MusinsaTrendReport/0.2 (personal research; daily, low-volume)"


class BlockedError(Exception):
    """무신사가 요청을 거부함 (401/403/429). 억지로 재시도하지 않는다."""


def get_json(url: str, allow_404: bool = False) -> dict | None:
    """JSON 요청. 거부되면 BlockedError, 일시적 네트워크 오류면 30초 뒤 한 번만 재시도."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise BlockedError(f"HTTP {e.code} — 무신사가 요청을 거부함: {url}") from e
            if e.code == 404 and allow_404:
                return None
            if attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(30)
    raise RuntimeError("unreachable")


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def load_env() -> None:
    """.env의 '이름=값' 줄을 환경변수로 읽음. 이미 설정된 값(클라우드 Secrets)은 덮어쓰지 않음."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
