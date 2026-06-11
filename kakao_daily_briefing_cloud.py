# -*- coding: utf-8 -*-
"""
SK아카데미 일일 이슈 브리핑 - GitHub Actions 클라우드 자동 발송
- 환경 변수에서 API 키 / refresh_token 로드
- 토큰은 GitHub Secrets에 안전하게 저장됨
- 발송 후 갱신된 refresh_token은 GitHub Actions 로그에 출력 (수동 업데이트)

사용법:
  python kakao_daily_briefing_cloud.py [오전|오후|저녁|테스트]
"""

import json
import os
import sys
import requests
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET

# ===== KST 시간 =====
KST = timezone(timedelta(hours=9))

def now_kst():
    return datetime.now(KST)

def log(msg):
    print(f"[{now_kst().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

# ===== 환경 변수 =====
def get_credentials():
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    if not api_key or not refresh_token:
        log("ERROR: KAKAO_REST_API_KEY 또는 KAKAO_REFRESH_TOKEN 환경 변수 없음")
        log("       GitHub Secrets에 등록되어 있는지 확인하세요.")
        sys.exit(1)
    return api_key, refresh_token

# ===== 토큰 갱신 =====
def refresh_access_token(api_key, refresh_token):
    res = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": api_key,
            "refresh_token": refresh_token
        },
        timeout=10
    )
    if res.status_code != 200:
        log(f"ERROR: 토큰 갱신 실패 - {res.status_code}: {res.text}")
        sys.exit(1)
    new = res.json()
    log("INFO: access_token 갱신 완료")

    # refresh_token도 갱신되면 출력 (관리자가 GitHub Secrets에 수동 업데이트)
    if "refresh_token" in new:
        log("=" * 60)
        log("⚠️ 새 refresh_token이 발급되었습니다.")
        log("   GitHub Secrets의 KAKAO_REFRESH_TOKEN을 다음 값으로 업데이트하세요:")
        log(f"   {new['refresh_token']}")
        log("=" * 60)

    return new["access_token"]

# ===== 시장 데이터 =====
def fetch_market_indices():
    indices = []
    try:
        url = "https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:KOSPI,KOSDAQ,FX_USDKRW"
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = res.json()
        name_map = {"KOSPI": ("코스피", 2), "KOSDAQ": ("코스닥", 2), "FX_USDKRW": ("원/달러", 1)}
        for area in data.get("result", {}).get("areas", []):
            for d in area.get("datas", []):
                code = d.get("cd", "")
                if code in name_map:
                    name, decimals = name_map[code]
                    val = d.get("nv", 0) / 100
                    chg = d.get("cv", 0) / 100
                    pct = d.get("cr", 0)
                    sign = "▲" if chg > 0 else ("▼" if chg < 0 else "─")
                    indices.append({
                        "name": name,
                        "value": f"{val:,.{decimals}f}",
                        "change": f"{sign}{abs(pct):.2f}%"
                    })
    except Exception as e:
        log(f"WARN: 시장지표 수집 실패: {e}")
    return indices

def fetch_stock_price(code):
    try:
        url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = res.json()
        for area in data.get("result", {}).get("areas", []):
            for d in area.get("datas", []):
                if d.get("cd") == code:
                    return {
                        "name": d.get("nm", ""),
                        "price": d.get("nv", 0),
                        "change_pct": d.get("cr", 0)
                    }
    except Exception as e:
        log(f"WARN: 종목 {code} 수집 실패: {e}")
    return None

def fetch_sk_stocks():
    sk_codes = {"000660": "SK하이닉스", "017670": "SK텔레콤"}
    results = []
    for code in sk_codes:
        info = fetch_stock_price(code)
        if info:
            sign = "▲" if info["change_pct"] > 0 else ("▼" if info["change_pct"] < 0 else "─")
            results.append({
                "name": info["name"],
                "price": f"{info['price']:,}",
                "change": f"{sign}{abs(info['change_pct']):.2f}%"
            })
    return results

def fetch_market_movers():
    movers = {"up": [], "down": [], "volume": []}
    urls = {
        "up": "https://finance.naver.com/sise/sise_rise.naver?sosok=0",
        "down": "https://finance.naver.com/sise/sise_fall.naver?sosok=0",
        "volume": "https://finance.naver.com/sise/sise_quant.naver?sosok=0"
    }
    import re
    for category, url in urls.items():
        try:
            res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            res.encoding = 'euc-kr'
            pattern = r'<a\s+href="/item/main\.naver\?code=(\d{6})"[^>]*>([^<]+)</a>'
            matches = re.findall(pattern, res.text)
            seen = set()
            for code, name in matches:
                if code in seen:
                    continue
                seen.add(code)
                info = fetch_stock_price(code)
                if info:
                    sign = "▲" if info["change_pct"] > 0 else "▼"
                    movers[category].append({
                        "name": info["name"],
                        "change": f"{sign}{abs(info['change_pct']):.2f}%"
                    })
                if len(movers[category]) >= 3:
                    break
        except Exception as e:
            log(f"WARN: {category} 수집 실패: {e}")
    return movers

# ===== 뉴스 RSS =====
def fetch_rss(url, max_items=3):
    try:
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(res.content)
        items = []
        for item in root.iter("item"):
            title_el = item.find("title")
            title = title_el.text if title_el is not None else ""
            if title:
                title = title.strip()
                title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                if len(title) > 45:
                    title = title[:42] + "..."
                items.append(title)
            if len(items) >= max_items:
                break
        return items
    except Exception as e:
        log(f"WARN: RSS 실패 ({url}): {e}")
        return []

def collect_headlines():
    sources = {
        "정치": "https://rss.donga.com/politics.xml",
        "경제": "https://rss.donga.com/economy.xml",
        "사회": "https://rss.donga.com/national.xml",
        "국제": "https://rss.donga.com/international.xml",
        "IT": "https://rss.donga.com/science.xml",
    }
    return {cat: fetch_rss(url, 3) for cat, url in sources.items()}

# ===== 메시지 작성 =====
def build_message(headlines, indices, sk_stocks, movers, slot_label=""):
    now = now_kst()
    days = ["월","화","수","목","금","토","일"]
    date_str = f"{now.year}.{now.month:02d}.{now.day:02d} ({days[now.weekday()]})"
    time_str = f"{now.hour:02d}:{now.minute:02d}"

    P = []
    title_suffix = f" [{slot_label}]" if slot_label else ""
    P.append(f"📰 일일 이슈 브리핑{title_suffix}")
    P.append("━━━━━━━━━━━━━━━")
    P.append(f"📅 {date_str} {time_str}")
    P.append("")

    if indices:
        P.append("📊 시장 지표")
        for idx in indices:
            P.append(f"  ▶ {idx['name']:6s} {idx['value']:>12s}  {idx['change']}")
        P.append("")

    if sk_stocks:
        P.append("🏢 SK그룹 주요 종목")
        for s in sk_stocks:
            name_padded = s['name'][:8].ljust(9)
            P.append(f"  ▶ {name_padded} {s['price']:>10s}  {s['change']}")
        P.append("")

    if movers.get("up"):
        P.append("🔺 상승률 TOP 3 (코스피)")
        for i, m in enumerate(movers["up"][:3], 1):
            P.append(f"  {i}. {m['name'][:10].ljust(11)} {m['change']}")
        P.append("")

    if movers.get("down"):
        P.append("🔻 하락률 TOP 3 (코스피)")
        for i, m in enumerate(movers["down"][:3], 1):
            P.append(f"  {i}. {m['name'][:10].ljust(11)} {m['change']}")
        P.append("")

    if movers.get("volume"):
        P.append("📈 거래량 급증 TOP 3")
        for i, m in enumerate(movers["volume"][:3], 1):
            P.append(f"  {i}. {m['name'][:10].ljust(11)} {m['change']}")
        P.append("")

    icon_map = {"정치": "🏛️", "경제": "💼", "사회": "👥", "국제": "🌏", "IT": "💻"}
    P.append("━━━━━━━━━━━━━━━")
    P.append("📰 주요 뉴스")
    P.append("")
    for cat, items in headlines.items():
        if items:
            P.append(f"{icon_map.get(cat, '📌')} {cat}")
            for title in items:
                P.append(f"  • {title}")
            P.append("")

    P.append("━━━━━━━━━━━━━━━")
    P.append("⚠️ 종목 정보는 단순 시세입니다")
    P.append("   투자 판단의 근거가 아닙니다")
    P.append("")
    P.append("※ Claude AI · GitHub Actions 자동 발송")
    return "\n".join(P)

# ===== 발송 =====
def send_to_me(access_token, message):
    res = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        },
        data={
            "template_object": json.dumps({
                "object_type": "text",
                "text": message[:1900],
                "link": {"web_url": "https://finance.naver.com",
                         "mobile_web_url": "https://finance.naver.com"},
                "button_title": "네이버 금융"
            }, ensure_ascii=False)
        },
        timeout=10
    )
    return res.status_code, res.text

def main():
    slot_label = sys.argv[1] if len(sys.argv) > 1 else ""
    log(f"=== 발송 시작 ({slot_label or '수동'}) ===")

    api_key, refresh_token = get_credentials()
    access_token = refresh_access_token(api_key, refresh_token)

    log("INFO: 시장 데이터 수집 중...")
    indices = fetch_market_indices()
    sk_stocks = fetch_sk_stocks()
    movers = fetch_market_movers()
    headlines = collect_headlines()

    log(f"INFO: 지표 {len(indices)}, SK {len(sk_stocks)}, 상승 {len(movers['up'])}, 헤드라인 {sum(len(v) for v in headlines.values())}")

    message = build_message(headlines, indices, sk_stocks, movers, slot_label)
    log(f"INFO: 메시지 길이 {len(message)}자")

    status, body = send_to_me(access_token, message)
    if status == 200:
        log("[OK] 발송 성공")
    else:
        log(f"[FAIL] {status}: {body}")
        sys.exit(1)

    log("=== 종료 ===")

if __name__ == "__main__":
    main()
