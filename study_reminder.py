# -*- coding: utf-8 -*-
"""
SK아카데미 학습 리마인더 v1
========================
저녁에 발송되는 별도 카톡 (학습 시간 알람용)
- cron-job.org 또는 GitHub Actions로 매일 저녁 9시 발송 권장
- 5분 학습 = 큰 변화의 시작
- 자격증 시험일 카운트다운 포함
"""
SCRIPT_VERSION = "study_reminder v1.0"

import json
import os
import sys
import requests
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
def now_kst(): return datetime.now(KST)
def log(msg): print(f"[{now_kst().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

# 시험 일정 (study.html과 동일)
CERT_EXAMS = [
    {"name": "배관기능사", "date": "2026-08-15"},
    {"name": "산업안전보건기사", "date": "2026-10-19"}
]

def days_until(date_str):
    target = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=KST)
    today = now_kst().replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (target - today).days
    return max(0, delta)

def get_credentials():
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    if not api_key or not refresh_token:
        log("ERROR: 환경 변수 없음")
        sys.exit(1)
    return api_key, refresh_token

def refresh_access_token(api_key, refresh_token):
    res = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={"grant_type": "refresh_token", "client_id": api_key, "refresh_token": refresh_token},
        timeout=10
    )
    if res.status_code != 200:
        log(f"ERROR: 토큰 갱신 실패 - {res.status_code}: {res.text}")
        sys.exit(1)
    new = res.json()
    log("INFO: access_token 갱신 완료")
    if "refresh_token" in new:
        log("새 refresh_token 발급됨. GitHub Secrets 업데이트 필요:")
        log(f"   {new['refresh_token']}")
    return new["access_token"]

def build_reminder():
    now = now_kst()
    days = ["월","화","수","목","금","토","일"]
    date_str = f"{now.year}.{now.month:02d}.{now.day:02d} ({days[now.weekday()]})"

    P = []
    P.append("📚 자기 발전 시간!")
    P.append("━━━━━━━━━━━━━━━")
    P.append(f"📅 {date_str} {now.hour:02d}:{now.minute:02d}")
    P.append("")
    P.append("💪 오늘도 5분만 투자해볼까요?")
    P.append("")
    P.append("✅ 오늘의 추천 학습")
    P.append("  • 🌏 영어 5문장 (3분)")
    P.append("  • 🇯🇵 일본어 5문장 (3분)")
    P.append("  • 🔧 배관 5문제 (5분)")
    P.append("  • ⛑️ 산업안전 5문제 (5분)")
    P.append("")
    P.append("⏰ 자격증 시험 카운트다운")
    for cert in CERT_EXAMS:
        d = days_until(cert["date"])
        emoji = "🔥" if d <= 30 else "📌"
        P.append(f"  {emoji} {cert['name']}: D-{d}일 ({cert['date']})")
    P.append("")
    P.append("💡 오늘의 학습 팁")
    P.append("  잠자기 직전 5분 복습이")
    P.append("  뇌에 가장 잘 저장됩니다.")
    P.append("  딱 5분만, SRS가 도와줄게요!")
    P.append("")
    P.append("━━━━━━━━━━━━━━━")
    P.append("🪙 코인 적립 + 레벨업도 잊지 마세요")
    P.append("매일 한 번이면 연속 학습일 +1")

    return "\n".join(P)

def send_to_me(access_token, message, link_url, button_title):
    res = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"template_object": json.dumps({
            "object_type": "text",
            "text": message[:1900],
            "link": {"web_url": link_url, "mobile_web_url": link_url},
            "button_title": button_title
        }, ensure_ascii=False)},
        timeout=10
    )
    return res.status_code, res.text

def main():
    log("=" * 60)
    log(f"=== {SCRIPT_VERSION} 시작 ===")
    log("=" * 60)
    api_key, refresh_token = get_credentials()
    access_token = refresh_access_token(api_key, refresh_token)
    msg = build_reminder()
    log(f"INFO: 리마인더 메시지 {len(msg)}자")
    study_url = os.environ.get("STUDY_URL", "https://sigamsixx-netizen.github.io/kakao-daily-briefing/study.html")
    status, body = send_to_me(access_token, msg, study_url, "📚 학습 시작!")
    if status == 200:
        log("[OK] 학습 리마인더 발송 성공")
    else:
        log(f"[FAIL] 발송 실패 - {status}: {body}")
        sys.exit(1)
    log("=== 완료 ===")

if __name__ == "__main__":
    main()
