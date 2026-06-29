# -*- coding: utf-8 -*-
"""
SK아카데미 일일 이슈 브리핑 v8
변경:
1. 카톡 1번에 서울 + 분당 날씨 모두 포함
2. 카톡 2번 버튼도 대시보드 링크로
3. 종목 인코딩 안전성 강화 (한글 깨짐 방지)
4. 세계 지표: 네이버 우선, Yahoo 백업
5. 버전 표시 추가 (적용 확인용)
"""

SCRIPT_VERSION = "v8.0 - 2026-06-25"

import json
import os
import sys
import time
import requests
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET
import re

KST = timezone(timedelta(hours=9))

def now_kst():
    return datetime.now(KST)

def log(msg):
    print(f"[{now_kst().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

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
        log("=" * 60)
        log("새 refresh_token 발급됨. GitHub Secrets 업데이트 필요:")
        log(f"   {new['refresh_token']}")
        log("=" * 60)
    return new["access_token"]

def fetch_weather(lat, lon, name="서울"):
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
            f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            f"&timezone=Asia%2FSeoul&forecast_days=4"
        )
        res = requests.get(url, timeout=10)
        data = res.json()
        wmo_map = {
            0: ("☀️","맑음"),1:("🌤️","대체로 맑음"),2:("⛅","구름 조금"),3:("☁️","흐림"),
            45:("🌫️","안개"),48:("🌫️","짙은 안개"),
            51:("🌦️","약한 이슬비"),53:("🌦️","이슬비"),55:("🌦️","강한 이슬비"),
            61:("🌧️","약한 비"),63:("🌧️","비"),65:("🌧️","강한 비"),
            71:("🌨️","약한 눈"),73:("🌨️","눈"),75:("❄️","강한 눈"),
            80:("🌦️","소나기"),81:("🌧️","강한 소나기"),82:("⛈️","매우 강한 소나기"),
            95:("⛈️","천둥번개"),96:("⛈️","천둥번개+우박"),99:("⛈️","강한 천둥번개"),
        }
        def desc(c):
            return wmo_map.get(c, ("🌡️", f"코드 {c}"))
        result = {"location": name}
        cur = data.get("current", {})
        icon, label = desc(cur.get("weather_code", 0))
        result["current"] = {
            "icon": icon, "label": label,
            "temp": round(cur.get("temperature_2m", 0), 1),
            "humidity": cur.get("relative_humidity_2m", 0),
            "wind": round(cur.get("wind_speed_10m", 0), 1)
        }
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        codes = daily.get("weather_code", [])
        max_t = daily.get("temperature_2m_max", [])
        min_t = daily.get("temperature_2m_min", [])
        rains = daily.get("precipitation_probability_max", [])
        days_kor = ["월","화","수","목","금","토","일"]
        result["daily"] = []
        for i in range(min(4, len(dates))):
            d = datetime.fromisoformat(dates[i])
            icon, label = desc(codes[i])
            result["daily"].append({
                "date": d.strftime("%m/%d"), "weekday": days_kor[d.weekday()],
                "icon": icon, "label": label,
                "max": round(max_t[i], 0), "min": round(min_t[i], 0),
                "rain": rains[i] if i < len(rains) else 0
            })
        return result
    except Exception as e:
        log(f"WARN: 날씨 수집 실패 ({name}): {e}")
        return None

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
                    indices.append({"name": name, "value": f"{val:,.{decimals}f}", "change": f"{sign}{abs(pct):.2f}%"})
        log(f"INFO: 한국 시장 지표 {len(indices)}개 수집")
    except Exception as e:
        log(f"WARN: 한국 시장지표 실패: {e}")
    return indices

def fetch_global_indices():
    indices = []
    try:
        url = "https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:DJI@DJI,NAS@IXIC,SPI@SPX"
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = res.json()
        name_map = {"DJI@DJI": ("다우존스", 2), "NAS@IXIC": ("나스닥", 2), "SPI@SPX": ("S&P 500", 2)}
        for area in data.get("result", {}).get("areas", []):
            for d in area.get("datas", []):
                code = d.get("cd", "")
                if code in name_map:
                    name, decimals = name_map[code]
                    val = d.get("nv", 0) / 100
                    chg = d.get("cv", 0) / 100
                    pct = d.get("cr", 0)
                    sign = "▲" if chg > 0 else ("▼" if chg < 0 else "─")
                    indices.append({"name": name, "value": f"{val:,.{decimals}f}", "change": f"{sign}{abs(pct):.2f}%"})
        log(f"INFO: 네이버 금융 해외 지수 {len(indices)}개 수집")
    except Exception as e:
        log(f"WARN: 네이버 해외 지수 실패: {e}")
    if len(indices) == 0:
        log("INFO: Yahoo Finance로 재시도...")
        symbols = [("^DJI", "다우존스", 2), ("^IXIC", "나스닥", 2), ("^GSPC", "S&P 500", 2)]
        for symbol, name, decimals in symbols:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
                res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                data = res.json()
                result = data["chart"]["result"][0]
                meta = result["meta"]
                price = meta.get("regularMarketPrice")
                prev = meta.get("chartPreviousClose") or meta.get("previousClose")
                if price is None or prev is None:
                    continue
                chg = price - prev
                pct = (chg / prev) * 100
                sign = "▲" if chg > 0 else ("▼" if chg < 0 else "─")
                indices.append({"name": name, "value": f"{price:,.{decimals}f}", "change": f"{sign}{abs(pct):.2f}%"})
            except Exception as e:
                log(f"WARN: Yahoo {name} 실패: {e}")
        log(f"INFO: Yahoo Finance 총 {len(indices)}개 수집")
    return indices

def fetch_stock_price(code):
    try:
        url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = res.json()
        for area in data.get("result", {}).get("areas", []):
            for d in area.get("datas", []):
                if d.get("cd") == code:
                    return {"name": d.get("nm", ""), "price": d.get("nv", 0), "change_pct": d.get("cr", 0)}
    except Exception as e:
        log(f"WARN: 종목 {code}: {e}")
    return None

def fetch_market_movers():
    movers = {"up": [], "down": [], "volume": []}
    urls = {
        "up": "https://finance.naver.com/sise/sise_rise.naver?sosok=0",
        "down": "https://finance.naver.com/sise/sise_fall.naver?sosok=0",
        "volume": "https://finance.naver.com/sise/sise_quant.naver?sosok=0"
    }
    for category, url in urls.items():
        try:
            res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            # 종목코드만 추출 (한글 종목명은 polling API에서 안전하게 조회)
            pattern = r'/item/main\.naver\?code=(\d{6})'
            codes = re.findall(pattern, res.text)
            seen = set()
            unique_codes = []
            for code in codes:
                if code not in seen:
                    seen.add(code)
                    unique_codes.append(code)
            log(f"INFO: {category} - 코드 {len(unique_codes)}개 추출")
            for code in unique_codes[:10]:
                info = fetch_stock_price(code)
                if info and info["name"]:
                    sign = "▲" if info["change_pct"] > 0 else "▼"
                    movers[category].append({
                        "code": code,
                        "name": info["name"],
                        "change": f"{sign}{abs(info['change_pct']):.2f}%"
                    })
                if len(movers[category]) >= 3:
                    break
            log(f"INFO: {category} - {len(movers[category])}개 수집")
        except Exception as e:
            log(f"WARN: {category} 실패: {e}")
    return movers

def fetch_rss(url, max_items=4):
    try:
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(res.content)
        items = []
        for item in root.iter("item"):
            title_el = item.find("title")
            title = title_el.text if title_el is not None else ""
            if title:
                title = title.strip().replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                if len(title) > 45:
                    title = title[:42] + "..."
                items.append(title)
            if len(items) >= max_items:
                break
        return items
    except Exception as e:
        log(f"WARN: RSS ({url}): {e}")
        return []

def collect_headlines():
    sources = {
        "정치": "https://rss.donga.com/politics.xml",
        "경제": "https://rss.donga.com/economy.xml",
        "사회": "https://rss.donga.com/national.xml",
        "국제": "https://rss.donga.com/international.xml",
        "IT": "https://rss.donga.com/science.xml",
    }
    return {cat: fetch_rss(url, 4) for cat, url in sources.items()}

def build_message_1(weather_seoul, weather_bundang, indices, movers, slot_label=""):
    now = now_kst()
    days = ["월","화","수","목","금","토","일"]
    date_str = f"{now.year}.{now.month:02d}.{now.day:02d} ({days[now.weekday()]})"
    time_str = f"{now.hour:02d}:{now.minute:02d}"
    P = []
    title_suffix = f" [{slot_label}]" if slot_label else ""
    P.append(f"📰 일일 이슈 브리핑{title_suffix} (1/2)")
    P.append("━━━━━━━━━━━━━━━")
    P.append(f"📅 {date_str} {time_str}")
    P.append("")
    if weather_seoul:
        P.append("🏙️ 서울 날씨")
        cur = weather_seoul["current"]
        P.append(f"  {cur['icon']} 현재: {cur['temp']}°C  {cur['label']}")
        P.append(f"     습도 {cur['humidity']}%  바람 {cur['wind']}m/s")
        if weather_seoul.get("daily"):
            today = weather_seoul["daily"][0]
            P.append(f"  📅 오늘: {today['max']:.0f}°/{today['min']:.0f}°  ☔{today['rain']:.0f}%")
        P.append("")
    if weather_bundang:
        P.append("🏘️ 분당(성남) 날씨")
        cur = weather_bundang["current"]
        P.append(f"  {cur['icon']} 현재: {cur['temp']}°C  {cur['label']}")
        P.append(f"     습도 {cur['humidity']}%  바람 {cur['wind']}m/s")
        if weather_bundang.get("daily"):
            today = weather_bundang["daily"][0]
            P.append(f"  📅 오늘: {today['max']:.0f}°/{today['min']:.0f}°  ☔{today['rain']:.0f}%")
        P.append("")
    P.append("━━━━━━━━━━━━━━━")
    P.append("💹 주식 정보")
    P.append("")
    if indices:
        P.append("📊 시장 지표")
        for idx in indices:
            P.append(f"  ▶ {idx['name']:6s} {idx['value']:>12s}  {idx['change']}")
        P.append("")
    if movers.get("up"):
        P.append("🔺 상승률 TOP 3")
        for i, m in enumerate(movers["up"][:3], 1):
            P.append(f"  {i}. {m['name'][:10].ljust(11)} {m['change']}")
        P.append("")
    if movers.get("down"):
        P.append("🔻 하락률 TOP 3")
        for i, m in enumerate(movers["down"][:3], 1):
            P.append(f"  {i}. {m['name'][:10].ljust(11)} {m['change']}")
        P.append("")
    if movers.get("volume"):
        P.append("📈 거래량 TOP 3")
        for i, m in enumerate(movers["volume"][:3], 1):
            P.append(f"  {i}. {m['name'][:10].ljust(11)} {m['change']}")
        P.append("")
    P.append("━━━━━━━━━━━━━━━")
    P.append("⚠️ 종목 정보는 단순 시세이며")
    P.append("   투자 판단의 근거가 아닙니다")
    P.append("")
    P.append("📰 주요 뉴스는 잠시 후 도착")
    return "\n".join(P)

def build_message_2(headlines, slot_label=""):
    now = now_kst()
    days = ["월","화","수","목","금","토","일"]
    date_str = f"{now.year}.{now.month:02d}.{now.day:02d} ({days[now.weekday()]})"
    time_str = f"{now.hour:02d}:{now.minute:02d}"
    P = []
    title_suffix = f" [{slot_label}]" if slot_label else ""
    P.append(f"📰 주요 뉴스{title_suffix} (2/2)")
    P.append("━━━━━━━━━━━━━━━")
    P.append(f"📅 {date_str} {time_str}")
    P.append("")
    icon_map = {"정치": "🏛️", "경제": "💼", "사회": "👥", "국제": "🌏", "IT": "💻"}
    for cat, items in headlines.items():
        if items:
            P.append(f"{icon_map.get(cat, '📌')} {cat}")
            for title in items:
                P.append(f"  • {title}")
            P.append("")
    P.append("━━━━━━━━━━━━━━━")
    P.append("📊 대시보드에서 더 자세히 보기")
    P.append("   분당 날씨·세계 지표·종목 차트")
    P.append("")
    P.append("※ Claude AI · GitHub Actions 자동 발송")
    return "\n".join(P)

def save_dashboard_json(weather_seoul, weather_bundang, indices, global_indices, movers, headlines):
    dashboard_data = {
        "updated_at": now_kst().isoformat(),
        "updated_at_display": now_kst().strftime("%Y-%m-%d %H:%M:%S KST"),
        "script_version": SCRIPT_VERSION,
        "weather": weather_seoul,
        "weather_seoul": weather_seoul,
        "weather_bundang": weather_bundang,
        "indices": indices,
        "global_indices": global_indices,
        "movers": movers,
        "headlines": headlines
    }
    try:
        with open("data.json", "w", encoding="utf-8") as f:
            json.dump(dashboard_data, f, ensure_ascii=False, indent=2)
        log(f"INFO: data.json 저장 완료 ({SCRIPT_VERSION})")
    except Exception as e:
        log(f"WARN: data.json 저장 실패: {e}")

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
    slot_label = sys.argv[1] if len(sys.argv) > 1 else ""
    log("=" * 60)
    log(f"=== {SCRIPT_VERSION} 시작 ({slot_label or '수동'}) ===")
    log("=" * 60)
    api_key, refresh_token = get_credentials()
    access_token = refresh_access_token(api_key, refresh_token)
    log("INFO: 서울 날씨...")
    weather_seoul = fetch_weather(37.5665, 126.9780, "서울")
    log("INFO: 분당 날씨...")
    weather_bundang = fetch_weather(37.3595, 127.1052, "분당")
    log("INFO: 뉴스 수집...")
    headlines = collect_headlines()
    log("INFO: 한국 시장 지표...")
    indices = fetch_market_indices()
    log("INFO: 세계 시장 지표...")
    global_indices = fetch_global_indices()
    log("INFO: TOP 종목...")
    movers = fetch_market_movers()
    log(f"INFO: === 데이터 요약 ===")
    log(f"  한국지표 {len(indices)}, 세계지표 {len(global_indices)}")
    log(f"  상승 {len(movers['up'])}, 하락 {len(movers['down'])}, 거래량 {len(movers['volume'])}")
    log(f"  뉴스 {sum(len(v) for v in headlines.values())}")
    save_dashboard_json(weather_seoul, weather_bundang, indices, global_indices, movers, headlines)
    dashboard_url = os.environ.get("DASHBOARD_URL", "https://sigamsixx-netizen.github.io/kakao-daily-briefing/dashboard.html")
    log("INFO: 메시지 1 작성...")
    msg1 = build_message_1(weather_seoul, weather_bundang, indices, movers, slot_label)
    log(f"INFO: 메시지 1 길이 {len(msg1)}자")
    status1, body1 = send_to_me(access_token, msg1, dashboard_url, "📊 대시보드 열기")
    if status1 == 200:
        log("[OK] 메시지 1 발송 성공")
    else:
        log(f"[FAIL] 메시지 1 실패 - {status1}: {body1}")
        sys.exit(1)
    log("INFO: 5초 대기...")
    time.sleep(5)
    log("INFO: 메시지 2 작성...")
    msg2 = build_message_2(headlines, slot_label)
    log(f"INFO: 메시지 2 길이 {len(msg2)}자")
    # 카톡 2도 대시보드로
    status2, body2 = send_to_me(access_token, msg2, dashboard_url, "📊 대시보드 열기")
    if status2 == 200:
        log("[OK] 메시지 2 발송 성공")
    else:
        log(f"[FAIL] 메시지 2 실패 - {status2}: {body2}")
        sys.exit(1)
    log("=" * 60)
    log(f"=== 전체 발송 완료 ({SCRIPT_VERSION}) ===")
    log("=" * 60)

if __name__ == "__main__":
    main()
