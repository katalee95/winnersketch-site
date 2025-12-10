import math
import os
import json
import re
import uuid
import sqlite3
from datetime import datetime, timedelta
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote as url_quote

import requests
from flask import Flask, request, Response, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

# ==============================
# 1. 기본 설정 및 DB/메일 설정
# ==============================

app = Flask(__name__)

# 🔑 공공데이터포털 나라장터 API 키
REAL_API_KEY = "7bab15bfb6883de78a3e2720338237530938fbeca5a7f4038ef1dfd0450dca48"

# 📧 SendGrid API 설정 (HTTP API 사용 - SMTP 포트 차단 문제 해결)
# Render 무료 플랜에서는 SMTP 포트(587)가 차단되므로 SendGrid HTTP API 사용

# 💾 데이터베이스 파일명
DB_FILE = "subscribers.db"


# 🚀 캐시 시스템 (메모리 기반) - API 호출 최적화
from threading import Lock
cache_lock = Lock()
api_cache = {}
CACHE_DURATION = 300  # 5분간 캐시 유지


def init_db():
    """DB 테이블 초기화"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 이메일, 최소금액, 최대금액, 관리토큰, 마케팅동의, 생성일
    c.execute('''CREATE TABLE IF NOT EXISTS subscribers
                 (email TEXT PRIMARY KEY, min_fee INTEGER, max_fee INTEGER, 
                  token TEXT, marketing_agreed INTEGER, created_at TEXT)''')
    # 2. [신규] 수동 공고 데이터 테이블 (새로 추가됨)
    c.execute('''CREATE TABLE IF NOT EXISTS manual_items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT, agency TEXT, fee INTEGER, 
                  notice_date TEXT, url TEXT, created_at TEXT)''')
    conn.commit()
    conn.close()

init_db()

def get_manual_data_from_db(keyword=None, min_fee=0, max_fee=999999999999):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = "SELECT * FROM manual_items WHERE fee BETWEEN ? AND ?"
    params = [min_fee, max_fee]
    
    if keyword:
        query += " AND (title LIKE ? OR agency LIKE ?)"
        params.append(f"%{keyword}%")
        params.append(f"%{keyword}%")
        
    query += " ORDER BY notice_date DESC"
    
    rows = c.execute(query, params).fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            "title": row['title'],
            "agency": row['agency'],
            "fee": row['fee'],
            "notice_date": row['notice_date'],
            "url": row['url'],
            "raw_date": row['notice_date'].replace("-", "") # 날짜 포맷 맞춤
        })
    return results


# ==============================
# 2. 유틸리티 함수 (메일, API)
# ==============================

def send_email(to_email, subject, html_content):
    """SendGrid API를 통한 메일 발송 (SMTP 포트 차단 문제 해결)"""
    try:
        api_key = os.environ.get("SENDGRID_API_KEY", "")
        
        # 디버깅
        api_key_length = len(api_key) if api_key else 0
        print(f"[DEBUG] SendGrid API Key length: {api_key_length}")
        
        if not api_key or api_key_length < 10:
            print(f"[ERROR] SendGrid API Key가 설정되지 않았습니다!")
            return False
        
        # SendGrid API 호출
        url = "https://api.sendgrid.com/v3/mail/send"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "personalizations": [
                {
                    "to": [{"email": to_email}],
                    "subject": subject
                }
            ],
            "from": {
                "email": "winnersketch.kr@gmail.com",
                "name": "위너스케치"
            },
            "content": [
                {
                    "type": "text/html",
                    "value": html_content
                }
            ]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 202:
            print(f"[메일발송성공] {to_email}")
            return True
        else:
            print(f"[메일발송실패] Status: {response.status_code}, Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"[메일발송실패] {e}")
        import traceback
        traceback.print_exc()
        return False
def parse_api_response(response):
    try:
        data = response.json()
        body = data.get("response", {}).get("body", {})
        items = body.get("items")
        return items if items else []
    except json.JSONDecodeError:
        pass
    try:
        root = ET.fromstring(response.text)
        items = []
        for item in root.findall(".//item"):
            row = {}
            for child in item:
                row[child.tag] = child.text
            items.append(row)
        return items
    except Exception:
        return []

def fetch_data_from_url(base_url, params, api_key):
    headers = {"User-Agent": "Mozilla/5.0"}
    final_key = api_key if "%" in api_key else url_quote(api_key)
    full_url = f"{base_url}?serviceKey={final_key}"
    try:
        resp = requests.get(full_url, params=params, timeout=20, headers=headers)
        if resp.status_code != 200:
            return [], {"status": resp.status_code}
        parsed = parse_api_response(resp)
        return parsed, {"status": 200}
    except Exception as e:
        return [], {"status": str(e)}

def get_competition_data(keyword, rows=100, strict_mode=False, days=30):
    # 🚀 캐시 확인
    cache_key = f"{keyword}_{rows}_{strict_mode}_{days}"
    with cache_lock:
        if cache_key in api_cache:
            cached_data, cached_time = api_cache[cache_key]
            if time.time() - cached_time < CACHE_DURATION:
                print(f"[캐시 HIT] {keyword} - 캐시된 데이터 사용")
                return cached_data, []
    
    clean_key = REAL_API_KEY.strip()
    if clean_key == "":
        return [], []

    now = datetime.now()
    inqryBgnDt = (now - timedelta(days=days)).strftime("%Y%m%d0000")
    inqryEndDt = now.strftime("%Y%m%d2359")

    params = {
        "numOfRows": str(rows),
        "pageNo": "1",
        "type": "json",
        "inqryDiv": "1",
        "inqryBgnDt": inqryBgnDt,
        "inqryEndDt": inqryEndDt,
    }

    targets = [
        ("https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch", "신버전(조달)"),
        ("https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcOrgnSearch", "신버전(자체)"),
    ]

    all_results = []
    debug_logs = []

    for url, type_label in targets:
        current_params = params.copy()
        current_params["bidNm"] = keyword
        current_params["bidNtceNm"] = keyword
        items, debug = fetch_data_from_url(url, current_params, clean_key)
        for item in items:
            all_results.append(item)

    cleaned = []
    seen_ids = set()
    exclude_keywords = ["철거", "관리", "운영", "개량", "검토", "복원", "임도", "산림", "산불", "예방", "폐기", "설치", "보수", "전기", "사방", "정비", "급수", "교량", "감리", "안전진단", "임차용역"]
    must_have = ["설계공모", "설계 공모", "실시 설계", "실시설계", "건축설계", "리모델링"] if strict_mode else ["설계"]

    for item in all_results:
        bid_id = item.get("bidNtceNo")
        if bid_id in seen_ids: continue

        title = item.get("bidNtceNm", "") or ""
        agency = item.get("ntceInsttNm") or item.get("dminsttNm") or ""

        if not strict_mode and keyword and (keyword not in title and keyword not in agency): continue
        if not any(k in title for k in must_have): continue
        if any(ex in title for ex in exclude_keywords): continue

        seen_ids.add(bid_id)

        price_raw = item.get("presmptPrce", 0) or 0
        try: price = int(price_raw)
        except: price = 0

        notice_date_str = re.sub(r'[^0-9]', '', str(item.get("bidNtceDt", "") or ""))
        if len(notice_date_str) >= 8:
            notice_date = f"{notice_date_str[0:4]}-{notice_date_str[4:6]}-{notice_date_str[6:8]}"
        else:
            notice_date = "-"

        url_link = item.get("bidNtceDtlUrl", "") or item.get("bidNtceUrl", "")
        if not url_link and bid_id:
            bid_ord = item.get("bidNtceOrd", "01")
            url_link = f"https://www.g2b.go.kr:8081/ep/invitation/publish/bidInfoDtl.do?bidno={bid_id}&bidseq={bid_ord}&releaseYn=Y&taskClCd=1"

        cleaned.append({
            "title": title, "agency": agency, "fee": price, 
            "notice_date": notice_date, "url": url_link,
            "raw_date": notice_date_str[:8]
        })

    cleaned.sort(key=lambda x: x["notice_date"], reverse=True)
    
    # 🚀 캐시에 저장
    with cache_lock:
        api_cache[cache_key] = (cleaned, time.time())
        print(f"[캐시 MISS] {keyword} - 새로 조회하여 캐시 저장 (결과: {len(cleaned)}건)")
    
    return cleaned, debug_logs


# ==============================
# 3. 스케줄러 (매일 아침 자동 실행)
# ==============================

def job_send_daily_emails():
    """매일 아침 실행되어 조건에 맞는 공고를 메일로 발송"""
    print(f"[{datetime.now()}] 스케줄러 시작: 일일 구독 메일 발송")
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    subscribers = cursor.execute("SELECT * FROM subscribers").fetchall()
    
    if not subscribers:
        print("구독자가 없습니다.")
        conn.close()
        return

    # 최근 2일치 데이터만 조회
    target_date_limit = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")
    
    keywords = ["건축설계", "설계공모", "리모델링"]
    all_items = []
    seen_ids = set()
    
    for kw in keywords:
        items, _ = get_competition_data(kw, rows=50, strict_mode=True, days=3)
        for item in items:
            uid = f"{item['title']}_{item['agency']}"
            if item['raw_date'] >= target_date_limit and uid not in seen_ids:
                seen_ids.add(uid)
                all_items.append(item)

    print(f"수집된 최신 공고: {len(all_items)}건")

    for user in subscribers:
        user_items = []
        for item in all_items:
            if user['min_fee'] <= item['fee'] <= user['max_fee']:
                user_items.append(item)
        
        if user_items:
            token = user['token']
            manage_link = f"https://www.winnersketch.kr/manage/{token}"
            
            html_body = f"""
            <div style="font-family:'Malgun Gothic', sans-serif; max-width:600px; margin:0 auto; padding:20px; border:1px solid #ddd; border-radius:10px;">
                <h2 style="color:#1E3A8A;">[위너스케치] 오늘의 맞춤 공모 알림</h2>
                <p>설정하신 금액대(<strong>{user['min_fee']//10000}만 ~ {user['max_fee']//10000}만원</strong>)에 해당하는 새로운 공고가 도착했습니다.</p>
                <hr style="border:0; border-top:1px solid #eee; margin:20px 0;">
                <ul style="padding-left:0; list-style:none;">
            """
            
            for item in user_items:
                fee_str = f"{item['fee']:,}원" if item['fee'] > 0 else "미공개"
                html_body += f"""
                <li style="margin-bottom:20px; padding-bottom:20px; border-bottom:1px dashed #eee;">
                    <div style="font-size:16px; font-weight:bold; color:#333;">{item['title']}</div>
                    <div style="font-size:14px; color:#666; margin-top:5px;">
                        발주처: {item['agency']} | <span style="color:#2563EB;">설계비: {fee_str}</span>
                    </div>
                    <div style="margin-top:10px;">
                        <a href="{item['url']}" style="background:#f1f5f9; color:#475569; text-decoration:none; padding:5px 10px; border-radius:5px; font-size:12px;">공고 바로가기 &rarr;</a>
                    </div>
                </li>
                """
            
            html_body += f"""
                </ul>
                <div style="background:#f8fafc; padding:15px; border-radius:8px; font-size:12px; color:#64748b; text-align:center; margin-top:30px;">
                    본 메일은 정보통신망법 준수를 위해 (광고) 표시가 포함될 수 있습니다.<br>
                    더 이상 알림을 원치 않으시거나 조건을 변경하시려면 아래 링크를 클릭하세요.<br>
                    <a href="{manage_link}" style="color:#2563EB; font-weight:bold; text-decoration:underline;">[설정 변경 및 수신거부]</a>
                </div>
            </div>
            """
            
            subject = f"(광고) [위너스케치] 고객님을 위한 {len(user_items)}건의 새로운 공고가 도착했습니다."
            send_email(user['email'], subject, html_body)

    conn.close()
    print("스케줄러 작업 완료")

scheduler = BackgroundScheduler()
scheduler.add_job(func=job_send_daily_emails, trigger="cron", hour=8, minute=30)
scheduler.start()


# ==============================
# 4. HTML 및 라우트
# ==============================

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>위너스케치 - 건축 현상설계 파트너</title>
    <link rel="icon" href="/static/images/favicon.png" type="image/png">
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.8/dist/web/static/pretendard.css" />
    <style>
        body { font-family: 'Pretendard', sans-serif; background-color: #ffffff; color: #111; }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #f1f1f1; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
        .tab-active { color: #1E3A8A; border-bottom: 3px solid #1E3A8A; font-weight: 800; }
        .tab-inactive { color: #94A3B8; border-bottom: 3px solid transparent; font-weight: 600; }
        .tab-inactive:hover { color: #64748B; }
        .price-card { transition: transform 0.2s ease, box-shadow 0.2s ease; }
        .price-card:hover { transform: translateY(-5px); box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1); }
        .feature-card-hover:hover { transform: translateY(-5px); box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04); }
        /* 가로 스크롤바 숨기기 */
        .scrollbar-hide::-webkit-scrollbar {
            display: none;
        }
        .scrollbar-hide {
            -ms-overflow-style: none;
            scrollbar-width: none;
        }
    </style>
</head>
<body class="antialiased">

    <nav class="w-full py-5 px-6 flex justify-between items-center bg-white sticky top-0 z-50 border-b border-slate-100">
        <div class="max-w-7xl mx-auto w-full flex justify-between items-center">
            <div class="text-2xl font-black text-slate-900 tracking-tighter cursor-pointer" onclick="switchToHome()">
                WINNERSKETCH
            </div>
            <div class="flex items-center gap-2 md:gap-8">
                <a href="#" onclick="switchToHome(); return false;" class="text-xs md:text-sm font-bold text-slate-500 hover:text-blue-600 transition whitespace-nowrap">
                    홈
                </a>
                <a href="#" onclick="switchToPortfolio(); return false;" class="text-xs md:text-sm font-bold text-slate-500 hover:text-blue-600 transition whitespace-nowrap">
                    포트폴리오
                </a>
                <a href="javascript:void(0)" onclick="openContactModal()" class="text-xs md:text-sm font-bold text-slate-500 hover:text-blue-600 transition whitespace-nowrap">
                    문의하기
                </a>
            </div>
        </div>
    </nav>

    <div id="home-section">
    <section class="pt-24 pb-16 px-4 text-center bg-white">
        <div class="max-w-5xl mx-auto">
            <p class="text-lg md:text-xl font-bold text-slate-500 mb-6 tracking-tight">현상설계 스케치업의 모든 것</p>
            <h1 class="text-5xl sm:text-6xl md:text-7xl lg:text-8xl font-black text-slate-900 leading-snug mb-8 sm:mb-12 tracking-tight">
                위너스케치에서<br>
                <span class="text-blue-500">쉽고 합리적으로</span>
            </h1>
            <a href="#app-section" class="inline-block bg-blue-500 hover:bg-blue-600 text-white font-bold text-lg py-4 px-12 rounded-full shadow-lg hover:shadow-blue-200 transition transform hover:-translate-y-1">
                견적 확인하러 가기
            </a>
        </div>
    </section>


    <!-- Quote -->
    <section class="py-12 bg-white text-center">
        <div class="max-w-4xl mx-auto px-4">
            <h2 class="text-2xl md:text-3xl font-extrabold text-slate-900 mb-3">"현상설계는 소중한 투자입니다"</h2>
            <p class="text-xl md:text-2xl font-medium text-slate-600">그 가치를 아는 파트너를 만나세요.</p>
        </div>
    </section>

    <!-- Features -->
    <section class="py-20 bg-slate-50/50">
        <div class="max-w-6xl mx-auto px-4">
            <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
                <div class="feature-card-hover bg-white p-10 rounded-[2rem] border border-slate-100 shadow-sm transition duration-300">
                    <div class="w-16 h-16 bg-blue-50 rounded-full flex items-center justify-center text-blue-600 text-2xl mb-8 mx-auto">
                        <i class="fa-solid fa-clock"></i>
                    </div>
                    <div class="text-center">
                        <h3 class="text-xl font-black text-slate-900 mb-4">효율적인 작업을<br>위한 최적의 파트너</h3>
                        <p class="text-slate-500 leading-relaxed text-sm break-keep">
                            8년차 CG 전문 업체의 전문성과 노하우를 바탕으로, 최적의 결과물을 제공합니다.
                        </p>
                    </div>
                </div>

                <div class="feature-card-hover bg-white p-10 rounded-[2rem] border border-slate-100 shadow-sm transition duration-300">
                    <div class="w-16 h-16 bg-blue-50 rounded-full flex items-center justify-center text-blue-600 text-2xl mb-8 mx-auto">
                        <i class="fa-solid fa-chart-simple"></i>
                    </div>
                    <div class="text-center">
                        <h3 class="text-xl font-black text-slate-900 mb-4">데이터 기반의<br>투명한 견적</h3>
                        <p class="text-slate-500 leading-relaxed text-sm break-keep">
                            나라장터 공고 데이터와 프로젝트 규모를 기반으로 산출된, 가장 합리적이고 투명한 표준 가격을 제시합니다.
                        </p>
                    </div>
                </div>

                <div class="feature-card-hover bg-white p-10 rounded-[2rem] border border-slate-100 shadow-sm transition duration-300">
                    <div class="w-16 h-16 bg-blue-50 rounded-full flex items-center justify-center text-blue-600 text-2xl mb-8 mx-auto">
                        <i class="fa-regular fa-lightbulb"></i>
                    </div>
                    <div class="text-center">
                        <h3 class="text-xl font-black text-slate-900 mb-4">설계를 완성시키는<br>감각적 전략</h3>
                        <p class="text-slate-500 leading-relaxed text-sm break-keep">
                            우리는 건축을 전공한 그래픽 디자이너입니다. 건축적 의도를 가장 잘 살린 '이기는 뷰'를 만듭니다.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section id="app-section" class="py-24 bg-white">
        <div class="max-w-6xl mx-auto px-4">
            <div class="text-center mb-16">
                <h2 class="text-2xl md:text-3xl font-black text-slate-900 mb-3">스케치업 3D모델링 지원이 필요한</h2>
                <p class="text-xl md:text-2xl font-bold text-slate-900">건축설계공모를 검색해보세요!</p>
            </div>

            <div class="flex justify-center gap-8 mb-12">
                <button id="tab-search" class="tab-active pb-3 px-2 text-lg transition" onclick="switchTab('search')">
                    <i class="fa-solid fa-magnifying-glass mr-2 text-sm"></i>용역 검색
                </button>
                <button id="tab-recommend" class="tab-inactive pb-3 px-2 text-lg transition" onclick="switchTab('recommend')">
                    <i class="fa-regular fa-file-lines mr-2 text-sm"></i>추천 공모 리스트
                </button>
            </div>

            <div class="w-full">
                <div id="content-search" class="block">
                    <div class="relative mb-10 max-w-2xl mx-auto">
                        <input type="text" id="searchInput" placeholder="공모전 명칭 입력 (예: 실시설계, 리모델링, 도서관)" 
                            class="w-full bg-slate-100 border-none rounded-full py-4 pl-6 pr-16 text-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition placeholder-slate-400">
                        <button onclick="performSearch()" class="absolute right-2 top-2 bottom-2 bg-blue-500 text-white w-12 h-12 rounded-full hover:bg-blue-600 transition flex items-center justify-center">
                            <i class="fa-solid fa-arrow-right"></i>
                        </button>
                    </div>
                    <div id="search-results" class="space-y-4 max-w-4xl mx-auto">
                        <div class="text-center py-20 bg-slate-50 rounded-3xl border border-dashed border-slate-200">
                            <p class="text-slate-400 font-medium">검색어를 입력하여 관련 용역을 찾아보세요.</p>
                            <p class="text-slate-400 text-sm mt-2">(검색 결과가 없는 공고는 문의주시면 친절히 안내해드리겠습니다.)</p>
                        </div>
                    </div>
                </div>

                <div id="content-recommend" class="hidden">
                    <div class="flex flex-col md:flex-row gap-6 mb-8 max-w-5xl mx-auto">
                        <div class="flex-1 bg-slate-50 p-6 rounded-2xl border border-slate-100">
                            <div class="flex items-center gap-2 mb-4">
                                <i class="fa-solid fa-filter text-blue-500"></i>
                                <label class="text-sm font-bold text-slate-700">설계비 범위 검색</label>
                            </div>
                            <div class="flex flex-col md:flex-row items-center gap-2">
                                <div class="w-full md:w-auto relative flex-1">
                                    <input type="number" id="minFee" value="10000" class="w-full p-3 pl-2 bg-white border border-slate-200 rounded-xl text-slate-700 focus:outline-none focus:border-blue-500 transition text-right pr-12">
                                    <span class="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 text-sm">만원</span>
                                </div>
                                <span class="text-slate-300">~</span>
                                <div class="w-full md:w-auto relative flex-1">
                                    <input type="number" id="maxFee" value="15000" class="w-full p-3 pl-2 bg-white border border-slate-200 rounded-xl text-slate-700 focus:outline-none focus:border-blue-500 transition text-right pr-12">
                                    <span class="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 text-sm">만원</span>
                                </div>
                                <button onclick="filterRecommendations()" class="w-full md:w-auto bg-slate-800 text-white px-6 py-3 rounded-xl font-bold hover:bg-slate-900 transition whitespace-nowrap">
                                    조회
                                </button>
                            </div>
                        </div>

                        <div class="w-full md:w-1/3 bg-blue-600 p-6 rounded-2xl text-white flex flex-col justify-between shadow-lg hover:bg-blue-700 transition cursor-pointer" onclick="openSubModal()">
                            <div>
                                <h3 class="font-bold text-lg mb-1"><i class="fa-regular fa-envelope mr-2"></i>매일 아침 알림받기</h3>
                                <p class="text-blue-100 text-sm">설정하신 금액대의 공고가 뜨면<br>메일로 알려드립니다.</p>
                            </div>
                            <div class="mt-4 text-right">
                                <span class="bg-white/20 px-4 py-2 rounded-full text-xs font-bold backdrop-blur-sm">구독하기 &rarr;</span>
                            </div>
                        </div>
                    </div>

                    <div id="recommend-results" class="space-y-4 max-w-4xl mx-auto"></div>
                </div>
            </div>
        </div>
    </section>

    <footer class="bg-white border-t border-slate-100 py-20 text-center mt-20">
        <div class="max-w-4xl mx-auto px-4">
            <h3 class="text-2xl md:text-3xl font-black text-slate-900 mb-6">위너스케치에서 쉽고 합리적으로.</h3>
            <p class="mb-10 text-slate-500">건축 현상설계 당선을 위한 최적의 파트너</p>
            <div class="text-xs text-slate-400 border-t border-slate-100 pt-10">
                <p class="mb-2">오에스케이스튜디오 | 대표: 이주훈 | 사업자등록번호: 208-12-72095</p>
                <p>문의: winnersketch.kr@gmail.com | Copyright © WinnerSketch. All rights reserved.</p>
            </div>
        </div>
    </footer>
    </div>

<div id="portfolio-section" class="hidden">
        <section class="pt-20 pb-20 px-4 bg-white">
            <div class="max-w-7xl mx-auto">
                <div class="text-center mb-20">
                    <h1 class="text-3xl md:text-5xl font-black text-slate-900 mb-4">포트폴리오</h1>
                    <p class="text-lg text-slate-600">위너스케치의 주요 프로젝트를 소개합니다</p>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 01</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">홍릉 첨단의료기기개발센터 및 바이오헬스센터 복합 건립 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2024 / Seoul / Competition</p>
                    </div>

                    <div class="relative group">
                        <div id="slider-1" class="flex overflow-x-auto gap-4 snap-x snap-mandatory scrollbar-hide scroll-smooth pb-4">
                            
                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-1.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-3.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-4.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-5.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-6.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-7.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-8.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-9.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-10.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/A-11.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>
                        </div>

                        <button onclick="scrollSlider('slider-1', 'left')" class="absolute left-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <button onclick="scrollSlider('slider-1', 'right')" class="absolute right-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 02</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">양주 종합사회복지센터 건립 건축 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2022 / Yangju / Competition</p>
                    </div>

                    <div class="relative group">
                        <div id="slider-2" class="flex overflow-x-auto gap-4 snap-x snap-mandatory scrollbar-hide scroll-smooth pb-4">
                            
                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/B-1.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/B-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/B-3.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                             <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/B-4.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                             <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/B-5.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                             <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/B-6.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>
                        </div>

                        <button onclick="scrollSlider('slider-2', 'left')" class="absolute left-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <button onclick="scrollSlider('slider-2', 'right')" class="absolute right-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>

                                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 03</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">연수구 보훈회관 건립 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2023 / Incheon / Competition</p>
                    </div>

                    <div class="relative group">
                        <div id="slider-3" class="flex overflow-x-auto gap-4 snap-x snap-mandatory scrollbar-hide scroll-smooth pb-4">
                            
                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/C-1.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/C-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/C-3.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/C-4.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>
                        </div>

                        <button onclick="scrollSlider('slider-3', 'left')" class="absolute left-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <button onclick="scrollSlider('slider-3', 'right')" class="absolute right-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 04</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">장평 복지회관 실시설계</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2024 / Jangheung / Visualization</p>
                    </div>

                    <div class="relative w-full px-[5%] md:px-0">
                        <div class="rounded-xl overflow-hidden shadow-2xl border border-slate-100">
                            <img src="/static/images/portfolio/D-1.jpg" onclick="openLightbox(this.src)" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" loading="lazy">
                        </div>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 05</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">영암군 농업기계 안전교육 보관시설 건립사업 건축설계 공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2024 / Yeong-am / Competition</p>
                    </div>

                    <div class="relative group">
                        <div id="slider-5" class="flex overflow-x-auto gap-4 snap-x snap-mandatory scrollbar-hide scroll-smooth pb-4">
                            
                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/E-1.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/E-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>
                        </div>

                        <button onclick="scrollSlider('slider-5', 'left')" class="absolute left-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <button onclick="scrollSlider('slider-5', 'right')" class="absolute right-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 06</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">충북생명산업고 교사 증축공사 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2023 / Boeun / Competition</p>
                    </div>

                    <div class="relative group">
                        <div id="slider-6" class="flex overflow-x-auto gap-4 snap-x snap-mandatory scrollbar-hide scroll-smooth pb-4">
                            
                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/F-1.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/F-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/F-3.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/F-4.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/F-5.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>
                        </div>

                        <button onclick="scrollSlider('slider-6', 'left')" class="absolute left-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <button onclick="scrollSlider('slider-6', 'right')" class="absolute right-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>

                 <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 07</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">청주중앙여중 본관 및 후관 공간재구조화 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2025 / Cheongju / Competition</p>
                    </div>

                    <div class="relative group">
                        <div id="slider-7" class="flex overflow-x-auto gap-4 snap-x snap-mandatory scrollbar-hide scroll-smooth pb-4">
                            
                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/G-1.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/G-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/G-3.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/G-4.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/G-5.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/G-6.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/G-7.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/G-8.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/G-9.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/G-10.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>
                        </div>

                        <button onclick="scrollSlider('slider-7', 'left')" class="absolute left-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <button onclick="scrollSlider('slider-7', 'right')" class="absolute right-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 08</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">충주남산초 공간재구조화 리모델링 및 증축공사 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2025 / Chungju / Competition</p>
                    </div>

                    <div class="relative group">
                        <div id="slider-8" class="flex overflow-x-auto gap-4 snap-x snap-mandatory scrollbar-hide scroll-smooth pb-4">
                            
                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/H-1.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/H-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/H-3.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/H-4.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>
                        </div>

                        <button onclick="scrollSlider('slider-8', 'left')" class="absolute left-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <button onclick="scrollSlider('slider-8', 'right')" class="absolute right-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 09</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">대소 공영주차장 조성사업 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2024 / Eumseong / Competition</p>
                    </div>

                    <div class="relative group">
                        <div id="slider-9" class="flex overflow-x-auto gap-4 snap-x snap-mandatory scrollbar-hide scroll-smooth pb-4">
                            
                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/I-1.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/I-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>
                        </div>

                        <button onclick="scrollSlider('slider-9', 'left')" class="absolute left-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <button onclick="scrollSlider('slider-9', 'right')" class="absolute right-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 10</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">광명시민건강 체육센터 건립공사 기본 및 실시설계용역</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2024 / Gwangmyeong / Competition</p>
                    </div>

                    <div class="relative w-full px-[5%] md:px-0">
                        <div class="rounded-xl overflow-hidden shadow-2xl border border-slate-100">
                            <img src="/static/images/portfolio/Z-1.jpg" onclick="openLightbox(this.src)" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" loading="lazy">
                        </div>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 11</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">중랑구 천문과학관 건립 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2024 / Seoul / Competition</p>
                    </div>

                    <div class="relative group">
                        <div id="slider-11" class="flex overflow-x-auto gap-4 snap-x snap-mandatory scrollbar-hide scroll-smooth pb-4">
                            
                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/X-1.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/X-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>
                        </div>

                        <button onclick="scrollSlider('slider-11', 'left')" class="absolute left-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <button onclick="scrollSlider('slider-11', 'right')" class="absolute right-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 12</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">청산초중 그린스마트 미래학교 층축공사 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2023 / Okcheon / Competition</p>
                    </div>

                    <div class="relative w-full px-[5%] md:px-0">
                        <div class="rounded-xl overflow-hidden shadow-2xl border border-slate-100">
                            <img src="/static/images/portfolio/J-1.jpg" onclick="openLightbox(this.src)" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" loading="lazy">
                        </div>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 13</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">진주시 신안동 복합 스포츠타운 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2022 / Jinju / Competition</p>
                    </div>

                    <div class="relative group">
                        <div id="slider-13" class="flex overflow-x-auto gap-4 snap-x snap-mandatory scrollbar-hide scroll-smooth pb-4">
                            
                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/K-1.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/K-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>

                            <div class="min-w-[90%] md:min-w-[60%] snap-center relative rounded-xl overflow-hidden shadow-lg border border-slate-100">
                                <img src="/static/images/portfolio/K-2.jpg" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" onclick="openLightbox(this.src)" loading="lazy">
                            </div>
                        </div>

                        <button onclick="scrollSlider('slider-13', 'left')" class="absolute left-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <button onclick="scrollSlider('slider-13', 'right')" class="absolute right-4 top-1/2 -translate-y-1/2 bg-white/80 hover:bg-white text-slate-900 w-12 h-12 rounded-full shadow-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition duration-300 hidden md:flex z-10">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>
                </div>

                <div class="mb-32">
                    <div class="flex flex-col md:flex-row md:items-end justify-between mb-6 px-2">
                        <div>
                            <span class="text-blue-600 font-bold text-sm tracking-widest">PROJECT 14</span>
                            <h2 class="text-3xl font-black text-slate-900 mt-1">청주 다회용기 공공세척장 설계공모</h2>
                        </div>
                        <p class="text-slate-500 text-sm mt-2 md:mt-0">2022 / Cheongju / Competition</p>
                    </div>

                    <div class="relative w-full px-[5%] md:px-0">
                        <div class="rounded-xl overflow-hidden shadow-2xl border border-slate-100">
                            <img src="/static/images/portfolio/Y-1.jpg" onclick="openLightbox(this.src)" class="w-full h-[400px] md:h-[600px] object-cover cursor-pointer hover:opacity-95 transition" loading="lazy">
                        </div>
                    </div>
                </div>


                </div>
        </section>
    </div>

    <div id="home-section">

    <div id="pricing-modal" class="fixed inset-0 bg-black/60 z-[100] hidden flex items-center justify-center p-4 backdrop-blur-sm">
        <div class="bg-white rounded-3xl w-full max-w-6xl relative shadow-2xl flex flex-col max-h-[90vh]">
            
            <div class="flex justify-end p-4 md:p-6 border-b border-slate-100 shrink-0 sticky top-0 bg-white rounded-t-3xl z-10">
                <button onclick="document.getElementById('pricing-modal').classList.add('hidden')" 
                    class="text-slate-300 hover:text-slate-800 text-3xl w-10 h-10 flex items-center justify-center rounded-full hover:bg-slate-100 transition">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>

            <div class="p-6 md:p-12 overflow-y-auto">
                <div class="text-center mb-12">
                    <h3 id="modal-title" class="text-2xl md:text-3xl font-black text-slate-900 mb-3 break-keep">공모전 제목</h3>
                    <div class="flex items-center justify-center gap-2 text-slate-500">
                        <span>공고 설계비:</span>
                        <span id="modal-fee" class="font-bold text-slate-800 text-lg">0원</span>
                    </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-3 gap-6 pb-4">
                    <div class="price-card border border-slate-100 rounded-2xl p-8 text-center relative bg-white hover:border-blue-200">
                        <h4 class="text-lg font-bold text-slate-900 mb-1">BASIC</h4>
                        <div id="price-basic" class="text-3xl font-black text-blue-600 mb-2 font-mono">0원</div>
                        <p class="text-xs text-slate-400 mb-8 font-medium">실속형 패키지</p>
                        <div class="space-y-4 text-left text-sm text-slate-600 mb-10 pl-2">
                            <div class="flex items-center"><i class="fa-solid fa-check text-blue-500 w-6"></i> <span>작업 기간: <b>2주</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-blue-500 w-6"></i> <span>컷 장수: <b>총 5컷 이내</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-blue-500 w-6"></i> <span>수정 횟수: <b>2회</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-blue-500 w-6"></i> <span>3D 원본 / 고해상도 제공</span></div>
                            <div class="flex items-center opacity-40"><i class="fa-solid fa-xmark text-slate-400 w-6"></i> <span>3D 영상 작업</span></div>
                            <div class="flex items-center opacity-40"><i class="fa-solid fa-xmark text-slate-400 w-6"></i> <span>긴급 작업 지원</span></div>
                        </div>
                        <a id="link-basic" href="#" target="_blank" class="block w-full py-4 bg-slate-50 text-slate-900 font-bold rounded-xl hover:bg-slate-100 transition border border-slate-200" onclick="event.preventDefault(); const result = calculateFeesFrontend(parseFloat(document.getElementById('modal-fee').innerText.replace(/[^0-9]/g, ''))); openQuoteModal(document.getElementById('modal-title').innerText, parseFloat(document.getElementById('modal-fee').innerText.replace(/[^0-9]/g, '')), 'BASIC', result.plans.basic); return false;">선택하기</a>
                    </div>
                    <div class="price-card border-2 border-red-500 bg-white rounded-2xl p-8 text-center relative shadow-xl transform md:-translate-y-4 z-10">
                        <div class="absolute -top-4 left-1/2 transform -translate-x-1/2 bg-red-500 text-white text-xs font-bold px-4 py-1.5 rounded-full shadow-md uppercase tracking-wider">
                            👑 Premium
                        </div>
                        <h4 class="text-lg font-bold text-red-500 mb-1 mt-2">PREMIUM</h4>
                        <div id="price-premium" class="text-3xl font-black text-red-500 mb-2 font-mono">0원</div>
                        <p class="text-xs text-red-400/80 mb-8 font-medium">표준형 패키지</p>
                        <div class="space-y-4 text-left text-sm text-slate-700 mb-10 pl-2">
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> <span>작업 기간: <b>1주</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> <span>컷 장수: <b>무제한</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> <span>수정 횟수: <b>무제한</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> <span>3D 원본 / 고해상도 제공</span></div>
                            <div class="flex items-center font-bold text-red-600"><i class="fa-solid fa-check text-red-500 w-6"></i> <span>3D 영상 작업 포함</span></div>
                            <div class="flex items-center opacity-40"><i class="fa-solid fa-xmark text-slate-400 w-6"></i> <span>긴급 작업 지원</span></div>
                        </div>
                        <a id="link-premium" href="#" target="_blank" class="block w-full py-4 bg-red-500 text-white font-bold rounded-xl hover:bg-red-600 transition shadow-lg hover:shadow-red-200" onclick="event.preventDefault(); const result = calculateFeesFrontend(parseFloat(document.getElementById('modal-fee').innerText.replace(/[^0-9]/g, ''))); openQuoteModal(document.getElementById('modal-title').innerText, parseFloat(document.getElementById('modal-fee').innerText.replace(/[^0-9]/g, '')), 'PREMIUM', result.plans.premium); return false;">선택하기</a>
                    </div>
                    <div class="price-card border-2 border-yellow-400 rounded-2xl p-8 text-center relative bg-white hover:border-yellow-500 shadow-lg">
                        <div class="absolute -top-4 left-1/2 transform -translate-x-1/2 bg-yellow-400 text-slate-900 text-xs font-bold px-4 py-1.5 rounded-full shadow-md uppercase tracking-wider flex items-center gap-1">
                            <i class="fa-solid fa-bolt"></i> Express
                        </div>
                        <h4 class="text-lg font-bold text-yellow-600 mb-1 mt-2">EXPRESS</h4>
                        <div id="price-express" class="text-3xl font-black text-yellow-600 mb-2 font-mono">0원</div>
                        <p class="text-xs text-yellow-600/80 mb-8 font-medium">긴급형 패키지</p>
                        <div class="space-y-4 text-left text-sm text-slate-600 mb-10 pl-2">
                            <div class="flex items-center"><i class="fa-solid fa-bolt text-yellow-500 w-6"></i> <span>작업 기간: <b>4일 이내</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-yellow-500 w-6"></i> <span>컷 장수: <b>무제한</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-yellow-500 w-6"></i> <span>수정 횟수: <b>무제한</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-yellow-500 w-6"></i> <span>3D 원본 / 고해상도 제공</span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-yellow-500 w-6"></i> <span>3D 영상 작업 포함</span></div>
                            <div class="flex items-center font-bold text-yellow-600"><i class="fa-solid fa-bolt text-yellow-500 w-6"></i> <span>긴급 작업 지원</span></div>
                        </div>
                        <a id="link-express" href="#" target="_blank" class="block w-full py-4 bg-yellow-400 text-slate-900 font-bold rounded-xl hover:bg-yellow-500 transition shadow-lg hover:shadow-yellow-200" onclick="event.preventDefault(); const result = calculateFeesFrontend(parseFloat(document.getElementById('modal-fee').innerText.replace(/[^0-9]/g, ''))); openQuoteModal(document.getElementById('modal-title').innerText, parseFloat(document.getElementById('modal-fee').innerText.replace(/[^0-9]/g, '')), 'EXPRESS', result.plans.express); return false;">선택하기</a>
                    </div>
                </div>
            </div>
            
        </div>
    </div>

    <div id="contact-modal" class="fixed inset-0 bg-black/60 z-[110] hidden flex items-center justify-center p-4 backdrop-blur-sm overflow-y-auto">
        <div class="bg-white rounded-2xl w-full max-w-md p-8 relative shadow-2xl my-auto">
            <button onclick="document.getElementById('contact-modal').classList.add('hidden')" class="sticky top-4 float-right text-slate-400 hover:text-slate-800">
                <i class="fa-solid fa-xmark text-xl"></i>
            </button>
            <h3 class="text-2xl font-black text-slate-900 mb-2">💬 문의하기</h3>
            <p class="text-slate-500 mb-6 text-sm">궁금한 점을 알려주세요. 빠르게 응대하겠습니다.</p>
            
            <div class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">성명</label>
                    <input type="text" id="contactName" placeholder="이름을 입력해주세요" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">이메일</label>
                    <input type="email" id="contactEmail" placeholder="example@company.com" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">전화번호</label>
                    <input type="tel" id="contactPhone" placeholder="010-0000-0000" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">문의 내용</label>
                    <textarea id="contactMessage" placeholder="문의 내용을 입력해주세요" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition h-24 resize-none"></textarea>
                </div>
                
                <div class="bg-blue-50 p-3 rounded-lg border border-blue-200">
                    <p class="text-xs text-blue-800"><strong>빠른 응대가 필요하신가요?</strong><br>
                    <i class="fa-solid fa-phone text-blue-600"></i> <strong>070-4647-1706</strong>으로 전화주세요!</p>
                </div>

                <button onclick="submitContactRequest()" class="w-full bg-blue-600 text-white py-4 rounded-xl font-bold hover:bg-blue-700 transition shadow-lg mt-2">
                    문의 전송하기
                </button>
            </div>
        </div>
    </div>

    <div id="quote-modal" class="fixed inset-0 bg-black/60 z-[110] hidden flex items-center justify-center p-4 backdrop-blur-sm overflow-y-auto">
        <div class="bg-white rounded-2xl w-full max-w-md p-8 relative shadow-2xl my-auto">
            <button onclick="document.getElementById('quote-modal').classList.add('hidden')" class="sticky top-4 float-right text-slate-400 hover:text-slate-800">
                <i class="fa-solid fa-xmark text-xl"></i>
            </button>
            <h3 class="text-2xl font-black text-slate-900 mb-2">🎨 작업 요청</h3>
            <p class="text-slate-500 mb-6 text-sm">고객정보를 입력해주세요. 빠른 응대가 필요하면 전화주세요!</p>
            
            <div class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">프로젝트명</label>
                    <input type="text" id="quoteProject" readonly class="w-full p-3 bg-slate-100 border border-slate-200 rounded-xl text-slate-700 text-sm">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">예상 견적가</label>
                    <input type="text" id="quotePrice" readonly class="w-full p-3 bg-slate-100 border border-slate-200 rounded-xl text-slate-700 font-bold text-sm">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">선택 플랜</label>
                    <input type="text" id="quotePlan" readonly class="w-full p-3 bg-slate-100 border border-slate-200 rounded-xl text-slate-700 font-bold text-sm">
                </div>
                
                <hr class="my-3 border-slate-200">
                
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">성명</label>
                    <input type="text" id="quoteName" placeholder="이름을 입력해주세요" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">이메일</label>
                    <input type="email" id="quoteEmail" placeholder="example@company.com" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">전화번호</label>
                    <input type="tel" id="quotePhone" placeholder="010-0000-0000" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">추가 요청사항</label>
                    <textarea id="quoteMessage" placeholder="특별한 요청사항이 있으시면 입력해주세요" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition h-20 resize-none"></textarea>
                </div>
                
                <div class="bg-blue-50 p-3 rounded-lg border border-blue-200">
                    <p class="text-xs text-blue-800"><strong>빠른 응대가 필요하신가요?</strong><br>
                    <i class="fa-solid fa-phone text-blue-600"></i> <strong>070-4647-1706</strong>으로 전화주세요!</p>
                </div>

                <button onclick="submitQuoteRequest()" class="w-full bg-blue-600 text-white py-4 rounded-xl font-bold hover:bg-blue-700 transition shadow-lg mt-2">
                    작업 요청 보내기
                </button>
            </div>
        </div>
    </div>

    <div id="sub-modal" class="fixed inset-0 bg-black/60 z-[110] hidden flex items-center justify-center p-4 backdrop-blur-sm">
        <div class="bg-white rounded-2xl w-full max-w-md p-8 relative shadow-2xl">
            <button onclick="document.getElementById('sub-modal').classList.add('hidden')" class="absolute top-4 right-4 text-slate-400 hover:text-slate-800">
                <i class="fa-solid fa-xmark text-xl"></i>
            </button>
            <h3 class="text-2xl font-black text-slate-900 mb-2">📬 맞춤 공모 알림</h3>
            <p class="text-slate-500 mb-6 text-sm">원하시는 금액대의 공고가 올라오면<br>매일 아침 이메일로 보내드립니다.</p>
            
            <div class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-600 mb-1">이메일 주소</label>
                    <input type="email" id="subEmail" placeholder="example@company.com" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition">
                </div>
                <div class="flex gap-2">
                    <div class="w-1/2">
                        <label class="block text-xs font-bold text-slate-600 mb-1">최소 설계비(만원)</label>
                        <input type="number" id="subMin" value="5000" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition">
                    </div>
                    <div class="w-1/2">
                        <label class="block text-xs font-bold text-slate-600 mb-1">최대 설계비(만원)</label>
                        <input type="number" id="subMax" value="50000" class="w-full p-3 border border-slate-200 rounded-xl focus:border-blue-500 outline-none transition">
                    </div>
                </div>
                
                <div class="bg-slate-50 p-3 rounded-lg flex items-start gap-2 mt-2">
                    <input type="checkbox" id="subConsent" class="mt-1 w-4 h-4 text-blue-600">
                    <label for="subConsent" class="text-xs text-slate-500 leading-snug cursor-pointer select-none">
                        <strong>(필수)</strong> 개인정보 수집 및 광고성 정보 수신에 동의합니다. 수집된 이메일은 맞춤 공고 알림 발송 용도로만 사용되며, 메일 하단 링크를 통해 언제든 수신 거부할 수 있습니다.
                    </label>
                </div>

                <button onclick="submitSubscription()" class="w-full bg-slate-900 text-white py-4 rounded-xl font-bold hover:bg-black transition shadow-lg mt-2">
                    무료로 구독하기
                </button>
            </div>
        </div>
    </div>

    <script>
        const OWNER_EMAIL = "winnersketch.kr@gmail.com";

        function switchToHome() {
            document.getElementById('home-section').classList.remove('hidden');
            document.getElementById('portfolio-section').classList.add('hidden');
            window.scrollTo(0, 0);
        }

        function switchToPortfolio() {
            document.getElementById('home-section').classList.add('hidden');
            document.getElementById('portfolio-section').classList.remove('hidden');
            window.scrollTo(0, 0);
        }

        function calculateFeesFrontend(fee) {
            let rate = 1.0;
            let note = "기본 요율";
            let rawQuote = 0;
            if (fee < 1000000000) {
                if (fee >= 300000000) {
                    const base = 300000000;
                    const steps = Math.floor((fee - base) / 10000000);
                    const discount = steps * 0.01;
                    rate = 1.0 - discount;
                    if (rate < 0.5) rate = 0.5;
                    rate = parseFloat(rate.toFixed(2));
                    note = `규모 할인 (${rate}%)`;
                    rawQuote = fee * (rate / 100.0);
                } else {
                    rate = 1.0;
                    rawQuote = fee * 0.01;
                }
            } else {
                rate = 0.8;
                note = "대형 프로젝트 (0.8%)";
                rawQuote = fee * 0.008;
            }
            let finalQuote = rawQuote;
            if (rawQuote <= 500000) finalQuote = rawQuote + 500000;
            else if (rawQuote < 1000000) finalQuote = 1000000;
            const baseQuote = Math.floor(finalQuote / 10000) * 10000;
            return {
                base: baseQuote, rate: rate, note: note,
                plans: {
                    basic: Math.floor((baseQuote * 0.8) / 10000) * 10000,
                    premium: baseQuote,
                    express: Math.floor((baseQuote * 1.2) / 10000) * 10000
                }
            };
        }

        function switchTab(tabName) {
            const searchContent = document.getElementById('content-search');
            const recoContent = document.getElementById('content-recommend');
            const searchTab = document.getElementById('tab-search');
            const recoTab = document.getElementById('tab-recommend');

            if (tabName === 'search') {
                searchContent.classList.remove('hidden');
                recoContent.classList.add('hidden');
                searchTab.className = "tab-active pb-3 px-2 text-lg transition";
                recoTab.className = "tab-inactive pb-3 px-2 text-lg transition";
            } else {
                searchContent.classList.add('hidden');
                recoContent.classList.remove('hidden');
                searchTab.className = "tab-inactive pb-3 px-2 text-lg transition";
                recoTab.className = "tab-active pb-3 px-2 text-lg transition";
                filterRecommendations();
            }
        }

        function renderList(items, containerId) {
            const container = document.getElementById(containerId);
            container.innerHTML = "";
            if (!items || items.length === 0) {
                container.innerHTML = `
                    <div class="text-center py-20 bg-slate-50 rounded-3xl border border-dashed border-slate-200">
                        <p class="text-slate-400 font-medium mb-4">조건에 맞는 공고가 없습니다.</p>
                        <p class="text-slate-400 text-sm mb-6">원하시는 조건의 공고가 있는지 직접 문의해보세요.</p>
                        <button onclick="openContactModal()" class="inline-block bg-blue-600 text-white px-6 py-2 rounded-lg font-bold hover:bg-blue-700 transition text-sm">
                            <i class="fa-solid fa-envelope mr-2"></i>문의하기
                        </button>
                        <p class="text-slate-500 text-xs mt-4">또는 <strong>070-4647-1706</strong>으로 전화주세요</p>
                    </div>
                `;
                return;
            }
            items.forEach(item => {
                const feeText = item.fee > 0 ? item.fee.toLocaleString() + "원" : "설계비 미공개";
                const isPriceAvailable = item.fee > 0;
                const safeTitle = item.title.replace(/"/g, '&quot;');
                const urlButton = item.url ? `<a href="${item.url}" target="_blank" class="w-full text-center px-6 py-3 rounded-xl font-bold text-sm border border-slate-300 text-slate-600 hover:bg-slate-50 transition flex items-center justify-center gap-2 mb-2">공고 원문 보기 <i class="fa-solid fa-arrow-up-right-from-square text-xs"></i></a>` : '';
                const quoteButton = isPriceAvailable ? 
                    `<button onclick="openPricingModal('${safeTitle}', ${item.fee})" class="w-full bg-blue-50 text-blue-600 hover:bg-blue-100 px-6 py-3 rounded-xl font-bold text-sm transition flex items-center justify-center gap-2">3D 견적확인 <i class="fa-solid fa-chevron-right"></i></button>` : 
                    `<button class="w-full bg-slate-50 text-slate-400 px-6 py-3 rounded-xl font-bold text-sm cursor-not-allowed">견적 불가</button>`;

                const html = `
                    <div class="bg-white border border-slate-100 rounded-2xl p-8 flex flex-col md:flex-row justify-between items-start md:items-center shadow-sm hover:shadow-md transition group">
                        <div class="mb-4 md:mb-0 md:flex-1 md:pr-8">
                            <div class="flex items-center gap-3 mb-2">
                                <span class="bg-slate-100 text-slate-600 text-xs font-bold px-2 py-1 rounded">공고</span>
                                <h4 class="text-xl font-bold text-slate-800 group-hover:text-blue-600 transition line-clamp-1">📄 ${item.title}</h4>
                            </div>
                            <p class="text-sm text-slate-500 font-medium flex items-center gap-2">
                                <span>${item.agency}</span><span class="w-1 h-1 bg-slate-300 rounded-full"></span><span>공고일: ${item.notice_date}</span>
                            </p>
                            <p class="text-slate-900 font-extrabold mt-3 text-lg">💰 설계비: ${feeText}</p>
                        </div>
                        <div class="w-full md:w-auto flex flex-col gap-1 min-w-[180px]">${urlButton}${quoteButton}</div>
                    </div>`;
                container.innerHTML += html;
            });
        }

        async function performSearch() {
            const query = document.getElementById('searchInput').value.trim();
            const container = document.getElementById('search-results');
            container.innerHTML = `<div class="text-center py-10 text-slate-400"><i class="fa-solid fa-spinner animate-spin text-3xl mb-3"></i><p>검색 중입니다...</p></div>`;
            try {
                const resp = await fetch('/api/search?q=' + encodeURIComponent(query));
                const data = await resp.json();
                renderList(data.items || [], 'search-results');
            } catch (e) {
                container.innerHTML = `<div class="text-center py-10 text-red-400">오류가 발생했습니다.</div>`;
            }
        }

        async function filterRecommendations() {
            const min = (parseInt(document.getElementById('minFee').value) || 0) * 10000;
            const max = (parseInt(document.getElementById('maxFee').value) || 999999) * 10000;
            const container = document.getElementById('recommend-results');
            container.innerHTML = `<div class="text-center py-10 text-slate-400"><i class="fa-solid fa-spinner animate-spin text-3xl mb-3"></i><p>추천 공모를 불러오는 중입니다...</p></div>`;
            try {
                const params = new URLSearchParams({ min: String(min), max: String(max) });
                const resp = await fetch('/api/recommend?' + params.toString());
                const data = await resp.json();
                renderList(data.items || [], 'recommend-results');
            } catch (e) {
                container.innerHTML = `<div class="text-center py-10 text-red-400">오류가 발생했습니다.</div>`;
            }
        }

        function openPricingModal(title, fee) {
            const result = calculateFeesFrontend(fee);
            document.getElementById('modal-title').innerText = title;
            document.getElementById('modal-fee').innerText = fee.toLocaleString() + "원";
            document.getElementById('price-basic').innerText = result.plans.basic.toLocaleString() + "원";
            document.getElementById('price-premium').innerText = result.plans.premium.toLocaleString() + "원";
            document.getElementById('price-express').innerText = result.plans.express.toLocaleString() + "원";

            const createLink = (planName, price) => {
                const subject = `[견적의뢰] ${title} - ${planName} 플랜`;
                const body = `안녕하세요, 위너스케치 견적 시스템을 통해 문의드립니다.\n\n1. 프로젝트명: ${title}\n2. 공고 설계비: ${fee.toLocaleString()}원\n3. 선택 플랜: ${planName}\n4. 예상 견적가: ${price.toLocaleString()}원\n\n[추가 요청 사항]\n`;
                return `mailto:${OWNER_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
            };

            document.getElementById('link-basic').href = createLink("BASIC", result.plans.basic);
            document.getElementById('link-premium').href = createLink("PREMIUM", result.plans.premium);
            document.getElementById('link-express').href = createLink("EXPRESS", result.plans.express);
            document.getElementById('pricing-modal').classList.remove('hidden');
        }

        function openQuoteModal(title, fee, planName, price) {
            document.getElementById('quoteProject').value = title;
            document.getElementById('quotePrice').value = price.toLocaleString() + "원";
            document.getElementById('quotePlan').value = planName;
            document.getElementById('quoteName').value = "";
            document.getElementById('quoteEmail').value = "";
            document.getElementById('quotePhone').value = "";
            document.getElementById('quoteMessage').value = "";
            document.getElementById('quote-modal').classList.remove('hidden');
        }

        async function submitQuoteRequest() {
            const name = document.getElementById('quoteName').value.trim();
            const email = document.getElementById('quoteEmail').value.trim();
            const phone = document.getElementById('quotePhone').value.trim();
            const message = document.getElementById('quoteMessage').value.trim();
            const project = document.getElementById('quoteProject').value;
            const plan = document.getElementById('quotePlan').value;
            const price = document.getElementById('quotePrice').value;

            if (!name) {
                alert('성명을 입력해주세요.');
                return;
            }
            if (!email || !email.includes('@')) {
                alert('유효한 이메일 주소를 입력해주세요.');
                return;
            }
            if (!phone) {
                alert('전화번호를 입력해주세요.');
                return;
            }

            const btn = document.querySelector('#quote-modal button');
            const originalText = btn.innerText;
            btn.innerText = "전송 중...";
            btn.disabled = true;

            try {
                const resp = await fetch('/api/quote-request', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        name: name,
                        email: email,
                        phone: phone,
                        message: message,
                        project: project,
                        plan: plan,
                        price: price
                    })
                });
                const data = await resp.json();
                
                if(data.success) {
                    alert('작업 요청이 전송되었습니다! 곧 연락드리겠습니다.');
                    document.getElementById('quote-modal').classList.add('hidden');
                } else {
                    alert('오류: ' + data.msg);
                }
            } catch(e) {
                alert('전송 오류가 발생했습니다.');
            } finally {
                btn.innerText = originalText;
                btn.disabled = false;
            }
        }

        function openContactModal() {
            document.getElementById('contactName').value = "";
            document.getElementById('contactEmail').value = "";
            document.getElementById('contactPhone').value = "";
            document.getElementById('contactMessage').value = "";
            document.getElementById('contact-modal').classList.remove('hidden');
        }

        async function submitContactRequest() {
            const name = document.getElementById('contactName').value.trim();
            const email = document.getElementById('contactEmail').value.trim();
            const phone = document.getElementById('contactPhone').value.trim();
            const message = document.getElementById('contactMessage').value.trim();

            if (!name) {
                alert('성명을 입력해주세요.');
                return;
            }
            if (!email || !email.includes('@')) {
                alert('유효한 이메일 주소를 입력해주세요.');
                return;
            }
            if (!phone) {
                alert('전화번호를 입력해주세요.');
                return;
            }
            if (!message) {
                alert('문의 내용을 입력해주세요.');
                return;
            }

            const btn = document.querySelector('#contact-modal button');
            const originalText = btn.innerText;
            btn.innerText = "전송 중...";
            btn.disabled = true;

            try {
                const resp = await fetch('/api/contact-request', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        name: name,
                        email: email,
                        phone: phone,
                        message: message
                    })
                });
                const data = await resp.json();
                
                if(data.success) {
                    alert('문의가 전송되었습니다! 곧 연락드리겠습니다.');
                    document.getElementById('contact-modal').classList.add('hidden');
                } else {
                    alert('오류: ' + data.msg);
                }
            } catch(e) {
                alert('전송 오류가 발생했습니다.');
            } finally {
                btn.innerText = originalText;
                btn.disabled = false;
            }
        }

        function openSubModal() {
            document.getElementById('subMin').value = document.getElementById('minFee').value;
            document.getElementById('subMax').value = document.getElementById('maxFee').value;
            document.getElementById('sub-modal').classList.remove('hidden');
        }

        async function submitSubscription() {
            const email = document.getElementById('subEmail').value;
            const min = document.getElementById('subMin').value * 10000;
            const max = document.getElementById('subMax').value * 10000;
            const consent = document.getElementById('subConsent').checked;

            if(!email || !email.includes('@')) {
                alert('유효한 이메일 주소를 입력해주세요.');
                return;
            }
            if(!consent) {
                alert('개인정보 수집 및 정보 수신에 동의해야 합니다.');
                return;
            }

            const btn = document.querySelector('#sub-modal button');
            const originalText = btn.innerText;
            btn.innerText = "처리 중...";
            btn.disabled = true;

            try {
                const resp = await fetch('/api/subscribe', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email: email, min_fee: min, max_fee: max, marketing: true})
                });
                const data = await resp.json();
                
                if(data.success) {
                    alert('구독이 완료되었습니다! 입력하신 이메일로 확인 메일을 보냈습니다.');
                    document.getElementById('sub-modal').classList.add('hidden');
                } else {
                    alert('오류: ' + data.msg);
                }
            } catch(e) {
                alert('통신 오류가 발생했습니다.');
            } finally {
                btn.innerText = originalText;
                btn.disabled = false;
            }
        }
        function scrollSlider(elementId, direction) {
            const container = document.getElementById(elementId);
            const scrollAmount = container.clientWidth * 0.6; // 화면 너비의 60%만큼 이동
            
            if (direction === 'left') {
                container.scrollLeft -= scrollAmount;
            } else {
                container.scrollLeft += scrollAmount;
            }
        }
        // 라이트박스 열기
        function openLightbox(imageSrc) {
            const modal = document.getElementById('lightbox-modal');
            const img = document.getElementById('lightbox-img');
            
            img.src = imageSrc;
            modal.classList.remove('hidden');
            document.body.style.overflow = 'hidden'; // 배경 스크롤 막기
        }

        // 라이트박스 닫기
        function closeLightbox() {
            const modal = document.getElementById('lightbox-modal');
            modal.classList.add('hidden');
            document.body.style.overflow = ''; // 스크롤 다시 허용
            setTimeout(() => { document.getElementById('lightbox-img').src = ''; }, 200);
        }
        
        // ESC 키 누르면 닫기
        document.addEventListener('keydown', function(event) {
            if (event.key === "Escape") {
                closeLightbox();
            }
        });
    </script>
    <div id="lightbox-modal" class="fixed inset-0 z-[200] bg-black/95 hidden flex items-center justify-center p-4 backdrop-blur-sm transition-opacity duration-300" onclick="closeLightbox()">
        <button class="absolute top-6 right-6 text-white/50 hover:text-white text-5xl transition transform hover:scale-110" onclick="closeLightbox()">
            <i class="fa-solid fa-xmark"></i>
        </button>
        <img id="lightbox-img" src="" class="max-w-full max-h-[90vh] object-contain rounded-md shadow-2xl cursor-default" onclick="event.stopPropagation()">
    </div>
</body>
</html>
"""

# ==============================
# [신규] 관리자 페이지 (수동 등록)
# ==============================

@app.route("/admin")
def admin_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>관리자 - 공고 수동 등록</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100 p-10">
        <div class="max-w-xl mx-auto bg-white p-8 rounded-lg shadow">
            <h1 class="text-2xl font-bold mb-6">📝 공고 수동 등록</h1>
            <form action="/api/add_manual" method="POST" class="space-y-4">
                <div>
                    <label class="block font-bold mb-1">공고명 (Title)</label>
                    <input type="text" name="title" required class="w-full border p-2 rounded">
                </div>
                <div>
                    <label class="block font-bold mb-1">발주처 (Agency)</label>
                    <input type="text" name="agency" required class="w-full border p-2 rounded">
                </div>
                <div>
                    <label class="block font-bold mb-1">설계비 (원)</label>
                    <input type="number" name="fee" required class="w-full border p-2 rounded">
                </div>
                <div>
                    <label class="block font-bold mb-1">공고일 (YYYY-MM-DD)</label>
                    <input type="date" name="notice_date" required class="w-full border p-2 rounded">
                </div>
                <div>
                    <label class="block font-bold mb-1">링크 (URL)</label>
                    <input type="text" name="url" placeholder="https://..." class="w-full border p-2 rounded">
                </div>
                <button type="submit" class="w-full bg-blue-600 text-white p-3 rounded font-bold hover:bg-blue-700">등록하기</button>
            </form>
            <div class="mt-4 text-sm text-gray-500">
                * 등록된 데이터는 검색 결과 최상단에 노출됩니다.
            </div>
        </div>
    </body>
    </html>
    """

@app.post("/api/add_manual")
def api_add_manual():
    title = request.form.get("title")
    agency = request.form.get("agency")
    fee = request.form.get("fee")
    notice_date = request.form.get("notice_date")
    url = request.form.get("url") or "#"
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO manual_items (title, agency, fee, notice_date, url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
              (title, agency, fee, notice_date, url, created_at))
    conn.commit()
    conn.close()
    
    return "<script>alert('등록되었습니다!'); window.location.href='/admin';</script>"

@app.route("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html")


@app.get("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    
    # 1. API 데이터 가져오기
    api_items, _ = get_competition_data(q, rows=100, strict_mode=False) if q else ([], [])
    
    # 2. 수동 데이터 가져오기 (검색어 포함)
    manual_items = get_manual_data_from_db(keyword=q)
    
    # 3. 합치기 (수동 데이터를 위로)
    final_items = manual_items + api_items
    
    return jsonify({"items": final_items})


@app.get("/api/recommend")
def api_recommend():
    try: min_fee = int(request.args.get("min", "0") or 0)
    except: min_fee = 0
    try: max_fee = int(request.args.get("max", "999999999999") or 999999999999)
    except: max_fee = 999999999999

    # 1. 수동 데이터 먼저 조회
    manual_items = get_manual_data_from_db(min_fee=min_fee, max_fee=max_fee)

    # 2. API 데이터 조회 (기존 로직 유지)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    keywords = ["건축설계", "설계공모", "실시설계", "리모델링"]
    api_results = []
    seen = set()

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_kw = {executor.submit(get_competition_data, kw, 100, True, 30): kw for kw in keywords}
        
        for future in as_completed(future_to_kw):
            try:
                res, _ = future.result()
                for item in res:
                    uid = f"{item['title']}_{item['agency']}"
                    if uid in seen: continue
                    seen.add(uid)
                    if not (min_fee <= item["fee"] <= max_fee): continue
                    api_results.append(item)
            except Exception:
                pass

    api_results.sort(key=lambda x: x["notice_date"], reverse=True)
    
    # 3. 합치기 (수동 데이터 + API 데이터)
    final_items = manual_items + api_results
    
    return jsonify({"items": final_items})


@app.post("/api/subscribe")
def api_subscribe():
    data = request.json
    email = data.get("email")
    min_fee = int(data.get("min_fee", 0))
    max_fee = int(data.get("max_fee", 999999999999))
    marketing = 1 if data.get("marketing", False) else 0
    
    if not email:
        return jsonify({"success": False, "msg": "이메일을 입력해주세요."})
    
    token = str(uuid.uuid4())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""INSERT OR REPLACE INTO subscribers 
                     (email, min_fee, max_fee, token, marketing_agreed, created_at) 
                     VALUES (?, ?, ?, ?, ?, ?)""", 
                  (email, min_fee, max_fee, token, marketing, now))
        conn.commit()
        conn.close()
        
        manage_link = f"https://www.winnersketch.kr/manage/{token}"
        send_email(email, "[위너스케치] 구독이 완료되었습니다.", 
                   f"""
                   <h2>환영합니다!</h2>
                   <p>위너스케치 공모 알림 구독이 완료되었습니다.</p>
                   <p>설정하신 조건: <strong>{min_fee//10000}만 ~ {max_fee//10000}만원</strong></p>
                   <p>내일부터 매일 아침 08:30에 조건에 맞는 새로운 공고를 보내드립니다.</p>
                   <hr>
                   <a href='{manage_link}'>구독 설정 관리하기</a>
                   """)
        
        return jsonify({"success": True, "msg": "구독이 완료되었습니다."})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})


@app.get("/manage/<token>")
def manage_page(token):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    user = c.execute("SELECT * FROM subscribers WHERE token=?", (token,)).fetchone()
    conn.close()
    
    if not user:
        return "<h3>유효하지 않거나 만료된 링크입니다.</h3>"
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>구독 관리</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-50 flex items-center justify-center min-h-screen p-4">
        <div class="bg-white p-8 rounded-2xl shadow-lg max-w-md w-full">
            <h2 class="text-2xl font-bold mb-6 text-slate-800">구독 설정 변경</h2>
            <div class="mb-6 p-4 bg-blue-50 text-blue-800 rounded-lg text-sm">
                현재 이메일: <strong>{user['email']}</strong>
            </div>
            
            <form action="/api/update_subscription" method="POST" class="space-y-4">
                <input type="hidden" name="token" value="{token}">
                <div>
                    <label class="block text-sm font-bold text-slate-600 mb-1">최소 설계비 (원)</label>
                    <input type="number" name="min_fee" value="{user['min_fee']}" class="w-full p-3 border rounded-lg">
                </div>
                <div>
                    <label class="block text-sm font-bold text-slate-600 mb-1">최대 설계비 (원)</label>
                    <input type="number" name="max_fee" value="{user['max_fee']}" class="w-full p-3 border rounded-lg">
                </div>
                <button type="submit" class="w-full bg-blue-600 text-white py-3 rounded-lg font-bold hover:bg-blue-700">설정 저장하기</button>
            </form>
            
            <hr class="my-8">
            
            <form action="/api/unsubscribe" method="POST" onsubmit="return confirm('정말 구독을 취소하시겠습니까?');">
                <input type="hidden" name="token" value="{token}">
                <button type="submit" class="w-full text-red-500 text-sm font-bold hover:underline">
                    더 이상 메일을 받지 않겠습니다 (구독 취소)
                </button>
            </form>
            
            <div class="mt-6 text-center">
                <a href="/" class="text-slate-400 text-sm hover:text-slate-600">홈으로 돌아가기</a>
            </div>
        </div>
    </body>
    </html>
    """

@app.post("/api/update_subscription")
def update_subscription():
    token = request.form.get("token")
    min_fee = request.form.get("min_fee")
    max_fee = request.form.get("max_fee")
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE subscribers SET min_fee=?, max_fee=? WHERE token=?", (min_fee, max_fee, token))
    conn.commit()
    conn.close()
    return "<script>alert('수정되었습니다.'); window.location.href='/manage/" + token + "';</script>"


@app.post("/api/unsubscribe")
def unsubscribe():
    token = request.form.get("token")
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM subscribers WHERE token=?", (token,))
    conn.commit()
    conn.close()
    return """
    <div style="text-align:center; padding-top:50px;">
        <h2>구독이 취소되었습니다.</h2>
        <p>그동안 이용해주셔서 감사합니다.</p>
        <a href="/">홈으로 가기</a>
    </div>
    """


@app.post("/api/quote-request")
def quote_request():
    data = request.json
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    message = data.get("message", "").strip()
    project = data.get("project", "").strip()
    plan = data.get("plan", "").strip()
    price = data.get("price", "").strip()
    
    if not all([name, email, phone]):
        return jsonify({"success": False, "msg": "필수 정보를 입력해주세요."})
    
    try:
        # 고객에게 발송
        customer_subject = f"[위너스케치] 작업 요청이 접수되었습니다"
        customer_html = f"""
        <div style="font-family:'Malgun Gothic', sans-serif; max-width:600px; margin:0 auto; padding:20px; border:1px solid #ddd; border-radius:10px;">
            <h2 style="color:#1E3A8A;">[위너스케치] 작업 요청 접수 완료</h2>
            <p>안녕하세요 {name}님,</p>
            <p>작업 요청이 정상 접수되었습니다. 빠른 시간 내에 연락드리겠습니다.</p>
            
            <div style="background:#f8fafc; padding:15px; border-radius:8px; margin:20px 0;">
                <p><strong>프로젝트:</strong> {project}</p>
                <p><strong>선택 플랜:</strong> {plan}</p>
                <p><strong>예상 견적가:</strong> {price}</p>
                <p><strong>연락처:</strong> {phone}</p>
            </div>
            
            <p>빠른 응대가 필요하신 경우 아래번호로 전화주세요!</p>
            <p style="font-size:18px; color:#2563EB; font-weight:bold;">📞 070-4647-1706</p>
            
            <hr style="border:0; border-top:1px solid #eee; margin:20px 0;">
            <p style="font-size:12px; color:#64748b; text-align:center;">위너스케치 | winnersketch.kr@gmail.com</p>
        </div>
        """
        send_email(email, customer_subject, customer_html)
        
        # 관리자에게 발송
        admin_subject = f"[신규 작업 요청] {project} - {plan}"
        admin_html = f"""
        <div style="font-family:'Malgun Gothic', sans-serif; max-width:600px; margin:0 auto; padding:20px; border:1px solid #ddd; border-radius:10px; background:#fff3cd;">
            <h2 style="color:#856404;">🔔 신규 작업 요청 알림</h2>
            
            <div style="background:#ffffff; padding:15px; border-radius:8px; margin:20px 0; border-left:4px solid #ffc107;">
                <p><strong>성명:</strong> {name}</p>
                <p><strong>이메일:</strong> {email}</p>
                <p><strong>전화:</strong> {phone}</p>
                <p><strong>프로젝트:</strong> {project}</p>
                <p><strong>선택 플랜:</strong> {plan}</p>
                <p><strong>예상 견적가:</strong> {price}</p>
                {f'<p><strong>추가 요청:</strong><br>{message}</p>' if message else ''}
            </div>
            
            <p style="color:#856404;"><strong>즉시 응대 필요!</strong></p>
        </div>
        """
        send_email("winnersketch.kr@gmail.com", admin_subject, admin_html)
        
        return jsonify({"success": True, "msg": "작업 요청이 전송되었습니다."})
    except Exception as e:
        print(f"[ERROR] 작업 요청 실패: {e}")
        return jsonify({"success": False, "msg": str(e)})


@app.post("/api/contact-request")
def contact_request():
    data = request.json
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    message = data.get("message", "").strip()
    
    if not all([name, email, phone, message]):
        return jsonify({"success": False, "msg": "필수 정보를 입력해주세요."})
    
    try:
        # 고객에게 발송
        customer_subject = f"[위너스케치] 문의가 접수되었습니다"
        customer_html = f"""
        <div style="font-family:'Malgun Gothic', sans-serif; max-width:600px; margin:0 auto; padding:20px; border:1px solid #ddd; border-radius:10px;">
            <h2 style="color:#1E3A8A;">[위너스케치] 문의 접수 완료</h2>
            <p>안녕하세요 {name}님,</p>
            <p>문의사항이 정상 접수되었습니다. 빠른 시간 내에 연락드리겠습니다.</p>
            
            <div style="background:#f8fafc; padding:15px; border-radius:8px; margin:20px 0;">
                <p><strong>문의 내용:</strong></p>
                <p style="white-space: pre-wrap;">{message}</p>
                <p style="margin-top:15px;"><strong>연락처:</strong> {phone}</p>
            </div>
            
            <p>빠른 응대가 필요하신 경우 아래번호로 전화주세요!</p>
            <p style="font-size:18px; color:#2563EB; font-weight:bold;">📞 070-4647-1706</p>
            
            <hr style="border:0; border-top:1px solid #eee; margin:20px 0;">
            <p style="font-size:12px; color:#64748b; text-align:center;">위너스케치 | winnersketch.kr@gmail.com</p>
        </div>
        """
        send_email(email, customer_subject, customer_html)
        
        # 관리자에게 발송
        admin_subject = f"[신규 문의] {name}"
        admin_html = f"""
        <div style="font-family:'Malgun Gothic', sans-serif; max-width:600px; margin:0 auto; padding:20px; border:1px solid #ddd; border-radius:10px; background:#fff3cd;">
            <h2 style="color:#856404;">🔔 신규 문의 알림</h2>
            
            <div style="background:#ffffff; padding:15px; border-radius:8px; margin:20px 0; border-left:4px solid #ffc107;">
                <p><strong>성명:</strong> {name}</p>
                <p><strong>이메일:</strong> {email}</p>
                <p><strong>전화:</strong> {phone}</p>
                <p><strong>문의 내용:</strong></p>
                <p style="white-space: pre-wrap; background:#f5f5f5; padding:10px; border-radius:5px;">{message}</p>
            </div>
            
            <p style="color:#856404;"><strong>즉시 응대 필요!</strong></p>
        </div>
        """
        send_email("winnersketch.kr@gmail.com", admin_subject, admin_html)
        
        return jsonify({"success": True, "msg": "문의가 전송되었습니다."})
    except Exception as e:
        print(f"[ERROR] 문의 요청 실패: {e}")
        return jsonify({"success": False, "msg": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)