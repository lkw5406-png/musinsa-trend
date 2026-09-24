"""Gmail 발송 Tool — 자동 실행에 문제가 생겼을 때 알림.

(리포트는 고정 주소 하나에 날짜별로 쌓이므로 매일 링크 메일은 보내지 않는다.)

필요한 설정 (.env 또는 GitHub Secrets):
  GMAIL_ADDRESS       보내는 Gmail 주소
  GMAIL_APP_PASSWORD  Gmail 앱 비밀번호 (16자리, 일반 비밀번호 아님)
  REPORT_TO           받는 주소 (쉼표로 여러 명 가능, 비우면 GMAIL_ADDRESS로)

사용법: python tools/send_email.py --alert "무슨 일이 있었는지"
"""
import argparse
import os
import smtplib
import sys
from email.message import EmailMessage

from common import load_env, today_kst


def send(subject: str, text: str) -> None:
    load_env()
    sender = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not sender or not password:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD 설정이 없음 (.env 또는 GitHub Secrets)")
    to = [a.strip() for a in (os.environ.get("REPORT_TO") or sender).split(",") if a.strip()]

    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(to)
    msg.set_content(text + "\n\nClaude에게 이 메일 내용을 보여주면 원인을 찾아 고칩니다.")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    print(f"메일 발송 완료 → {', '.join(to)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alert", required=True)
    parser.add_argument("--date", default=today_kst())
    args = parser.parse_args()
    send(f"[무신사 트렌드] ⚠ {args.date} 자동 실행 문제", args.alert)
    return 0


if __name__ == "__main__":
    sys.exit(main())
