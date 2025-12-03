import math
import json
import re
import uuid
import sqlite3
import smtplib
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
from urllib.parse import quote as url_quote
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from flask import Flask, request, Response, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

# ==============================
# 1. 기본 설정 및 DB/메일 설정
# ==============================

app = Flask(__name__)

# 🔑 공공데이터포털 나라장터 API 키
REAL_API_KEY = "7bab15bfb6883de78a3e2720338237530938fbeca5a7f4038ef1dfd0450dca48"

# 📧 Gmail 설정 (변경됨)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "winnersketch.kr@gmail.com"  # 🟢 새로 만드신 계정
SMTP_PASSWORD = "ooedozuheenpwwxd"  # 🔴🔴🔴 (띄어쓰기 없이 입력하세요)

# 💾 데이터베이스 파일명
DB_FILE = "subscribers.db"


def init_db():
    """DB 테이블 초기화"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 이메일, 최소금액, 최대금액, 관리토큰, 마케팅동의, 생성일
    c.execute('''CREATE TABLE IF NOT EXISTS subscribers
                 (email TEXT PRIMARY KEY, min_fee INTEGER, max_fee INTEGER, 
                  token TEXT, marketing_agreed INTEGER, created_at TEXT)''')
    conn.commit()
    conn.close()

init_db()


# ==============================
# 2. 유틸리티 함수 (메일, API)
# ==============================

def send_email(to_email, subject, html_content):
    """Gmail 발송 함수 (TLS 587 포트 사용)"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"위너스케치 <{SMTP_USER}>"
        msg["To"] = to_email

        part = MIMEText(html_content, "html")
        msg.attach(part)

        # Gmail 접속 및 발송
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()  # 보안 연결 시작
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
            
        print(f"[메일발송성공] {to_email}")
        return True
    except Exception as e:
        print(f"[메일발송실패] {e}")
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
            manage_link = f"http://localhost:8000/manage/{token}"
            
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
    </style>
</head>
<body class="antialiased">

    <nav class="w-full py-5 px-6 flex justify-between items-center bg-white sticky top-0 z-50 border-b border-slate-100">
        <div class="max-w-7xl mx-auto w-full flex justify-between items-center">
            <div class="text-2xl font-black text-slate-900 tracking-tighter cursor-pointer" onclick="window.scrollTo(0,0)">
                WINNERSKETCH
            </div>
            <a href="mailto:winnersketch.kr@gmail.com" class="text-sm font-bold text-slate-500 hover:text-blue-600 transition">
                문의하기
            </a>
        </div>
    </nav>

    <section class="pt-24 pb-32 px-4 text-center bg-white">
        <div class="max-w-5xl mx-auto">
            <p class="text-lg md:text-xl font-bold text-slate-500 mb-6 tracking-tight">현상설계 스케치업의 모든 것</p>
            <h1 class="text-4xl md:text-6xl font-black text-slate-900 leading-tight mb-12 tracking-tight whitespace-nowrap">
                위너스케치에서 쉽고 합리적으로.
            </h1>
            <a href="#app-section" class="inline-block bg-blue-500 hover:bg-blue-600 text-white font-bold text-lg py-4 px-12 rounded-full shadow-lg hover:shadow-blue-200 transition transform hover:-translate-y-1">
                견적 확인하러 가기
            </a>
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
                        <input type="text" id="searchInput" placeholder="공모전 명칭 입력 (예: 해미면, 태화강, 도서관)" 
                            class="w-full bg-slate-100 border-none rounded-full py-4 pl-6 pr-16 text-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition placeholder-slate-400">
                        <button onclick="performSearch()" class="absolute right-2 top-2 bottom-2 bg-blue-500 text-white w-12 h-12 rounded-full hover:bg-blue-600 transition flex items-center justify-center">
                            <i class="fa-solid fa-arrow-right"></i>
                        </button>
                    </div>
                    <div id="search-results" class="space-y-4 max-w-4xl mx-auto">
                        <div class="text-center py-20 bg-slate-50 rounded-3xl border border-dashed border-slate-200">
                            <p class="text-slate-400 font-medium">검색어를 입력하여 관련 용역을 찾아보세요.</p>
                            <p class="text-slate-400 text-sm mt-2">('설계' 키워드가 포함된 공고만 검색됩니다)</p>
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
                <p class="mb-2">위너스케치 | 문의: winnersketch.kr@gmail.com</p>
                <p>Copyright © WinnerSketch. All rights reserved.</p>
            </div>
        </div>
    </footer>

    <div id="pricing-modal" class="fixed inset-0 bg-black/60 z-[100] hidden flex items-center justify-center p-4 backdrop-blur-sm overflow-y-auto">
        <div class="bg-white rounded-3xl w-full max-w-6xl my-8 relative shadow-2xl">
            <button onclick="document.getElementById('pricing-modal').classList.add('hidden')" class="absolute top-6 right-6 text-slate-300 hover:text-slate-800 text-2xl w-10 h-10 flex items-center justify-center rounded-full hover:bg-slate-100 transition">
                <i class="fa-solid fa-xmark"></i>
            </button>
            <div class="p-8 md:p-12">
                <div class="text-center mb-12">
                    <h3 id="modal-title" class="text-2xl md:text-3xl font-black text-slate-900 mb-3 break-keep">공모전 제목</h3>
                    <div class="flex items-center justify-center gap-2 text-slate-500">
                        <span>공고 설계비:</span>
                        <span id="modal-fee" class="font-bold text-slate-800 text-lg">0원</span>
                    </div>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="price-card border border-slate-100 rounded-2xl p-8 text-center">
                        <h4 class="text-lg font-bold text-slate-900 mb-1">BASIC</h4>
                        <div id="price-basic" class="text-3xl font-black text-blue-600 mb-2 font-mono">0원</div>
                        <p class="text-xs text-slate-400 mb-8">실속형 패키지 (80%)</p>
                        <a id="link-basic" href="#" target="_blank" class="block w-full py-4 bg-slate-50 text-slate-900 font-bold rounded-xl hover:bg-slate-100 transition border border-slate-200">선택하기</a>
                    </div>
                    <div class="price-card border-2 border-red-500 bg-white rounded-2xl p-8 text-center shadow-xl transform md:-translate-y-4">
                        <div class="text-red-500 text-xs font-bold mb-2 uppercase">👑 Premium</div>
                        <h4 class="text-lg font-bold text-red-500 mb-1">PREMIUM</h4>
                        <div id="price-premium" class="text-3xl font-black text-red-500 mb-2 font-mono">0원</div>
                        <p class="text-xs text-red-400 mb-8">표준형 패키지 (100%)</p>
                        <a id="link-premium" href="#" target="_blank" class="block w-full py-4 bg-red-500 text-white font-bold rounded-xl hover:bg-red-600 transition">선택하기</a>
                    </div>
                    <div class="price-card border border-slate-100 rounded-2xl p-8 text-center">
                        <h4 class="text-lg font-bold text-slate-900 mb-1">EXPRESS</h4>
                        <div id="price-express" class="text-3xl font-black text-blue-600 mb-2 font-mono">0원</div>
                        <p class="text-xs text-slate-400 mb-8">긴급형 패키지 (120%)</p>
                        <a id="link-express" href="#" target="_blank" class="block w-full py-4 bg-slate-100 text-slate-800 font-bold rounded-xl hover:bg-slate-200 transition border border-slate-200">선택하기</a>
                    </div>
                </div>
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
                container.innerHTML = `<div class="text-center py-20 bg-slate-50 rounded-3xl border border-dashed border-slate-200"><p class="text-slate-400 font-medium">조건에 맞는 공고가 없습니다.</p></div>`;
                return;
            }
            items.forEach(item => {
                const feeText = item.fee > 0 ? item.fee.toLocaleString() + "원 (" + Math.floor(item.fee / 10000).toLocaleString() + "만원)" : "설계비 미공개";
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
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html")


@app.get("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q: return jsonify({"items": []})
    items, _ = get_competition_data(q, rows=100, strict_mode=False)
    return jsonify({"items": items})


@app.get("/api/recommend")
def api_recommend():
    try: min_fee = int(request.args.get("min", "0") or 0)
    except: min_fee = 0
    try: max_fee = int(request.args.get("max", "999999999999") or 999999999999)
    except: max_fee = 999999999999

    keywords = ["건축설계", "설계공모", "실시설계", "리모델링"]
    merged = []
    seen = set()

    for kw in keywords:
        res, _ = get_competition_data(kw, rows=100, strict_mode=True, days=30)
        for item in res:
            uid = f"{item['title']}_{item['agency']}"
            if uid in seen: continue
            seen.add(uid)
            if not (min_fee <= item["fee"] <= max_fee): continue
            merged.append(item)

    merged.sort(key=lambda x: x["notice_date"], reverse=True)
    return jsonify({"items": merged})


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
        
        manage_link = f"http://localhost:8000/manage/{token}"
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)