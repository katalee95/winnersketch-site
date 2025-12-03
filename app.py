import math
import json
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
from urllib.parse import quote as url_quote

import requests
from flask import Flask, request, Response, jsonify

# ==============================
# 1. 기본 설정
# ==============================

app = Flask(__name__)

# 🔑 공공데이터포털 나라장터 API 키
#   - 당장은 하드코딩해두고, 나중에 환경변수로 빼는 걸 추천
REAL_API_KEY = "7bab15bfb6883de78a3e2720338237530938fbeca5a7f4038ef1dfd0450dca48"  # <- 이 줄만 너 키로 바꾸기

# ✅ [수동 데이터 추가] 프로젝트 서울 등 외부 공모전 데이터베이스
# 이곳에 원하는 공모전을 계속 추가하면 추천 리스트에 자동으로 뜹니다.
MANUAL_DATA = [
    {
        "title": "서리풀 보이는 수장고 국제설계공모",
        "agency": "서울특별시",
        "fee": 5800000000,  # 콤마 없이 숫자만
        "deadline": "2025-12-31"
    },
    {
        "title": "서울형 키즈카페 건립 설계공모",
        "agency": "서울시",
        "fee": 250000000,
        "deadline": "2025-10-15"
    },
    {
        "title": "노들섬 디자인 공모 (글로벌)",
        "agency": "서울특별시 도시공간기획과",
        "fee": 1500000000,
        "deadline": "2025-11-20"
    }
]


# ==============================
# 2. 나라장터 API 유틸 함수
# ==============================

def parse_api_response(response):
    """JSON 또는 XML 응답을 items 리스트로 변환"""
    # 1) JSON 시도
    try:
        data = response.json()
        body = data.get("response", {}).get("body", {})
        items = body.get("items")
        return items if items else []
    except json.JSONDecodeError:
        pass

    # 2) XML 시도
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

    if "%" in api_key:
        final_key = api_key
    else:
        final_key = url_quote(api_key)

    full_url = f"{base_url}?serviceKey={final_key}"

    try:
        resp = requests.get(
            full_url,
            params=params,
            timeout=20,
            headers=headers,
        )
        if resp.status_code != 200:
            return [], {"status": resp.status_code, "response": "Error"}
        parsed = parse_api_response(resp)
        return parsed, {"status": 200, "response": "Success"}
    except Exception as e:
        return [], {"status": "Exception", "response": str(e)}


def get_competition_data(keyword, rows=100, strict_mode=False):
    """
    keyword: 검색어
    strict_mode:
        - False: '설계' 포함 + 불필터 키워드 제외 + 제목/기관에 keyword 포함
        - True : 설계공모/실시설계/리모델링 등만 더 강하게 필터
    """
    clean_key = REAL_API_KEY.strip()
    if clean_key == "":
        return [], []

    now = datetime.now()
    days_to_fetch = 30
    inqryBgnDt = (now - timedelta(days=days_to_fetch)).strftime("%Y%m%d0000")
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
        ("https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch", "구버전(조달)"),
        ("https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcOrgnSearch", "구버전(자체)"),
    ]

    all_results = []
    debug_logs = []

    for url, type_label in targets:
        current_params = params.copy()
        current_params["bidNm"] = keyword
        current_params["bidNtceNm"] = keyword
        items, debug = fetch_data_from_url(url, current_params, clean_key)
        debug_logs.append(f"[{type_label}] {debug['response']}")
        for item in items:
            item["type_label"] = type_label
            all_results.append(item)

    if not all_results:
        return [], debug_logs

    cleaned = []
    seen_ids = set()

    exclude_keywords = [
        "철거", "관리", "운영", "개량", "검토", "복원", "임도",
        "산림", "산불", "예방", "폐기", "설치", "보수", "전기",
        "사방", "정비", "급수", "교량", "지표", "고도화",
        "감리", "안전진단",
    ]

    if strict_mode:
        must_have = ["설계공모", "설계 공모", "실시 설계", "실시설계", "건축설계", "리모델링"]
    else:
        must_have = ["설계"]

    for item in all_results:
        bid_id = item.get("bidNtceNo")
        if bid_id in seen_ids:
            continue

        title = item.get("bidNtceNm", "") or ""
        agency = item.get("ntceInsttNm") or item.get("dminsttNm") or ""

        if not strict_mode:
            if keyword and (keyword not in title and keyword not in agency):
                continue

        if not any(k in title for k in must_have):
            continue
        if any(ex in title for ex in exclude_keywords):
            continue

        seen_ids.add(bid_id)

        price_raw = item.get("presmptPrce", 0) or 0
        try:
            price = int(price_raw)
        except Exception:
            price = 0

        deadline_raw = item.get("bidClseDt", "-") or "-"
        # "YYYYMMDDHHMM" → "YYYY-MM-DD" 정도로 단순 포맷
        if len(deadline_raw) >= 8:
            deadline = f"{deadline_raw[0:4]}-{deadline_raw[4:6]}-{deadline_raw[6:8]}"
        else:
            deadline = "-"

        cleaned.append(
            {
                "title": title,
                "agency": agency,
                "fee": price,
                "deadline": deadline,
            }
        )

    # 마감일 기준 정렬 (최신/가까운 순)
    cleaned.sort(
        key=lambda x: x["deadline"] if x["deadline"] != "-" else "0000-00-00",
        reverse=False,
    )

    return cleaned, debug_logs


# ==============================
# 3. HTML 템플릿 (네가 준 디자인)
#    - JS 부분은 mockData 제거하고, /api/search /api/recommend 호출하게 수정
# ==============================

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>위너스케치 - 건축 현상설계 파트너</title>
    
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>

    <!-- Font Awesome -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">

    <!-- Pretendard Font -->
    <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.8/dist/web/static/pretendard.css" />

    <style>
        body {
            font-family: 'Pretendard', sans-serif;
            background-color: #ffffff;
            color: #111;
        }
        
        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #f1f1f1; 
        }
        ::-webkit-scrollbar-thumb {
            background: #cbd5e1; 
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #94a3b8; 
        }

        .tab-active {
            color: #1E3A8A;
            border-bottom: 3px solid #1E3A8A;
            font-weight: 800;
        }
        .tab-inactive {
            color: #94A3B8;
            border-bottom: 3px solid transparent;
            font-weight: 600;
        }
        .tab-inactive:hover {
            color: #64748B;
        }

        .price-card {
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .price-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
        }
        
        .feature-card-hover:hover {
            transform: translateY(-5px);
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
        }
    </style>
</head>
<body class="antialiased">

    <!-- Navigation -->
    <nav class="w-full py-5 px-6 flex justify-between items-center bg-white sticky top-0 z-50 border-b border-slate-100">
        <div class="max-w-7xl mx-auto w-full flex justify-between items-center">
            <div class="text-2xl font-black text-slate-900 tracking-tighter cursor-pointer" onclick="window.scrollTo(0,0)">
                WINNERSKETCH
            </div>
            <a href="mailto:altjr1643@gmail.com" class="text-sm font-bold text-slate-500 hover:text-blue-600 transition">
                문의하기
            </a>
        </div>
    </nav>

    <!-- Hero -->
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

    <!-- Quote -->
    <section class="py-24 bg-white text-center">
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
                            1인 프리랜서의 기동성과 전문 업체의 시스템을 결합하여, 소장님의 소중한 시간을 아껴드립니다.
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
                        <h3 class="text-xl font-black text-slate-900 mb-4">설계를 완성시키는<br>전략</h3>
                        <p class="text-slate-500 leading-relaxed text-sm break-keep">
                            우리는 건축을 전공한 그래픽 디자이너입니다. 건축적 의도를 가장 잘 살린 '이기는 뷰'를 만듭니다.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <!-- App Section -->
    <section id="app-section" class="py-24 bg-white">
        <div class="max-w-6xl mx-auto px-4">
            <div class="text-center mb-16">
                <h2 class="text-2xl md:text-3xl font-black text-slate-900 mb-3">3D 전문 모델링 지원이 필요한 설계공모 리스트를</h2>
                <p class="text-xl md:text-2xl font-bold text-slate-900">검색하고 위너스케치의 작업 견적을 확인해보세요.</p>
            </div>

            <!-- Tabs -->
            <div class="flex justify-center gap-8 mb-12">
                <button id="tab-search" class="tab-active pb-3 px-2 text-lg transition" onclick="switchTab('search')">
                    <i class="fa-solid fa-magnifying-glass mr-2 text-sm"></i>용역 검색
                </button>
                <button id="tab-recommend" class="tab-inactive pb-3 px-2 text-lg transition" onclick="switchTab('recommend')">
                    <i class="fa-regular fa-file-lines mr-2 text-sm"></i>추천 공모 리스트
                </button>
            </div>

            <!-- Contents -->
            <div class="w-full">
                <!-- Search Tab -->
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

                <!-- Recommend Tab -->
                <div id="content-recommend" class="hidden">
                    <div class="bg-slate-50 p-6 rounded-2xl mb-8 border border-slate-100 max-w-3xl mx-auto">
                        <div class="flex items-center gap-2 mb-4">
                            <i class="fa-solid fa-filter text-blue-500"></i>
                            <label class="text-sm font-bold text-slate-700">설계비 범위로 좁혀보기</label>
                        </div>
                        <div class="flex flex-col md:flex-row items-center gap-4">
                            <div class="w-full md:w-1/2 relative">
                                <span class="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-sm">최소</span>
                                <input type="number" id="minFee" value="0" class="w-full p-3 pl-12 bg-white border border-slate-200 rounded-xl text-slate-700 focus:outline-none focus:border-blue-500 transition" placeholder="0">
                            </div>
                            <span class="text-slate-300 font-light hidden md:block">~</span>
                            <div class="w-full md:w-1/2 relative">
                                <span class="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-sm">최대</span>
                                <input type="number" id="maxFee" value="5000000000" class="w-full p-3 pl-12 bg-white border border-slate-200 rounded-xl text-slate-700 focus:outline-none focus:border-blue-500 transition" placeholder="MAX">
                            </div>
                            <button onclick="filterRecommendations()" class="w-full md:w-auto bg-slate-800 text-white px-6 py-3 rounded-xl font-bold hover:bg-slate-900 transition whitespace-nowrap">
                                적용하기
                            </button>
                        </div>
                    </div>

                    <div id="recommend-results" class="space-y-4 max-w-4xl mx-auto"></div>
                </div>
            </div>
        </div>
    </section>

    <!-- Footer -->
    <footer class="bg-white border-t border-slate-100 py-20 text-center mt-20">
        <div class="max-w-4xl mx-auto px-4">
            <h3 class="text-2xl md:text-3xl font-black text-slate-900 mb-6">위너스케치에서 쉽고 합리적으로.</h3>
            <p class="mb-10 text-slate-500">건축 현상설계 당선을 위한 최적의 파트너</p>
            
            <div class="flex justify-center gap-4 mb-16">
                <button onclick="switchTab('search'); document.getElementById('app-section').scrollIntoView({behavior: 'smooth'})" class="px-6 py-3 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full font-bold text-sm transition">
                    다시 검색하기
                </button>
                <a href="mailto:altjr1643@gmail.com" class="px-6 py-3 bg-slate-900 hover:bg-black text-white rounded-full font-bold text-sm transition">
                    문의하기
                </a>
            </div>

            <div class="text-xs text-slate-400 border-t border-slate-100 pt-10">
                <p class="mb-2">위너스케치 | 대표: 홍길동 | 사업자등록번호: 000-00-00000</p>
                <p>문의: altjr1643@gmail.com | Copyright © WinnerSketch. All rights reserved.</p>
            </div>
        </div>
    </footer>

    <!-- Pricing Modal -->
    <div id="pricing-modal" class="fixed inset-0 bg-black/60 z-[100] hidden flex items-center justify-center p-4 backdrop-blur-sm overflow-y-auto">
        <div class="bg-white rounded-3xl w-full max-w-6xl my-8 relative shadow-2xl transform transition-all scale-100">
            <button onclick="closeModal()" class="absolute top-6 right-6 text-slate-300 hover:text-slate-800 text-2xl z-10 w-10 h-10 flex items-center justify-center rounded-full hover:bg-slate-100 transition">
                <i class="fa-solid fa-xmark"></i>
            </button>
            
            <div class="p-8 md:p-12">
                <div class="text-center mb-12">
                    <div class="inline-block bg-blue-50 text-blue-600 text-xs font-extrabold px-3 py-1 rounded-full uppercase tracking-wide mb-4">Estimated Quote</div>
                    <h3 id="modal-title" class="text-2xl md:text-3xl font-black text-slate-900 mb-3 break-keep">공모전 제목</h3>
                    <div class="flex items-center justify-center gap-2 text-slate-500">
                        <i class="fa-solid fa-coins text-yellow-500"></i>
                        <span>공고 설계비:</span>
                        <span id="modal-fee" class="font-bold text-slate-800 text-lg">0원</span>
                    </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="price-card border border-slate-100 rounded-2xl p-8 text-center relative bg-white hover:border-blue-200">
                        <h4 class="text-lg font-bold text-slate-900 mb-1">BASIC</h4>
                        <div id="price-basic" class="text-3xl font-black text-blue-600 mb-2 font-mono">0원</div>
                        <p class="text-xs text-slate-400 mb-8 font-medium">실속형 패키지 (80%)</p>
                        <div class="space-y-4 text-left text-sm text-slate-600 mb-10 pl-2">
                            <div class="flex items-center"><i class="fa-solid fa-check text-blue-500 w-6"></i> <span>작업 기간: <b>2주</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-blue-500 w-6"></i> <span>컷 장수: <b>총 5컷 이내</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-blue-500 w-6"></i> <span>수정 횟수: <b>2회</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-blue-500 w-6"></i> <span>3D 원본 / 고해상도 제공</span></div>
                            <div class="flex items-center opacity-40"><i class="fa-solid fa-xmark text-slate-400 w-6"></i> <span>3D 영상 작업</span></div>
                            <div class="flex items-center opacity-40"><i class="fa-solid fa-xmark text-slate-400 w-6"></i> <span>긴급 작업 지원</span></div>
                        </div>
                        <a id="link-basic" href="#" target="_blank" class="block w-full py-4 bg-slate-50 text-slate-900 font-bold rounded-xl hover:bg-slate-100 transition border border-slate-200">선택하기</a>
                    </div>

                    <div class="price-card border-2 border-red-500 bg-white rounded-2xl p-8 text-center relative shadow-xl transform md:-translate-y-4 z-10">
                        <div class="absolute -top-4 left-1/2 transform -translate-x-1/2 bg-red-500 text-white text-xs font-bold px-4 py-1.5 rounded-full shadow-md uppercase tracking-wider">
                            👑 Premium
                        </div>
                        <h4 class="text-lg font-bold text-red-500 mb-1 mt-2">PREMIUM</h4>
                        <div id="price-premium" class="text-3xl font-black text-red-500 mb-2 font-mono">0원</div>
                        <p class="text-xs text-red-400/80 mb-8 font-medium">표준형 패키지 (100%)</p>
                        <div class="space-y-4 text-left text-sm text-slate-700 mb-10 pl-2">
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> <span>작업 기간: <b>1주</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> <span>컷 장수: <b>무제한</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> <span>수정 횟수: <b>무제한</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> <span>3D 원본 / 고해상도 제공</span></div>
                            <div class="flex items-center font-bold text-red-600"><i class="fa-solid fa-check text-red-500 w-6"></i> <span>3D 영상 작업 포함</span></div>
                            <div class="flex items-center opacity-40"><i class="fa-solid fa-xmark text-slate-400 w-6"></i> <span>긴급 작업 지원</span></div>
                        </div>
                        <a id="link-premium" href="#" target="_blank" class="block w-full py-4 bg-red-500 text-white font-bold rounded-xl hover:bg-red-600 transition shadow-lg hover:shadow-red-200">선택하기</a>
                    </div>

                    <div class="price-card border border-slate-100 rounded-2xl p-8 text-center relative bg-white hover:border-blue-200">
                        <h4 class="text-lg font-bold text-slate-900 mb-1">EXPRESS</h4>
                        <div id="price-express" class="text-3xl font-black text-blue-600 mb-2 font-mono">0원</div>
                        <p class="text-xs text-slate-400 mb-8 font-medium">긴급형 패키지 (120%)</p>
                        <div class="space-y-4 text-left text-sm text-slate-600 mb-10 pl-2">
                            <div class="flex items-center"><i class="fa-solid fa-bolt text-blue-500 w-6"></i> <span>작업 기간: <b>4일 이내</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> <span>컷 장수: <b>무제한</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> <span>수정 횟수: <b>무제한</b></span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> <span>3D 원본 / 고해상도 제공</span></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> <span>3D 영상 작업 포함</span></div>
                            <div class="flex items-center font-bold text-blue-600"><i class="fa-solid fa-check text-blue-500 w-6"></i> <span>긴급 작업 지원</span></div>
                        </div>
                        <a id="link-express" href="#" target="_blank" class="block w-full py-4 bg-slate-100 text-slate-800 font-bold rounded-xl hover:bg-slate-200 transition border border-slate-200">선택하기</a>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- JS: Python API와 연동 -->
    <script>
        const OWNER_EMAIL = "altjr1643@gmail.com";

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
            if (rawQuote <= 500000) {
                finalQuote = rawQuote + 500000;
            } else if (rawQuote < 1000000) {
                finalQuote = 1000000;
            }

            const baseQuote = Math.floor(finalQuote / 10000) * 10000;

            return {
                base: baseQuote,
                rate: rate,
                note: note,
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
                        <p class="text-slate-400 font-medium">조건에 맞는 공고가 없습니다.</p>
                    </div>`;
                return;
            }

            items.forEach(item => {
                const feeText = item.fee > 0 ? item.fee.toLocaleString() + "원" : "설계비 미공개";
                const isPriceAvailable = item.fee > 0;
                const safeTitle = item.title.replace(/"/g, '&quot;');

                const html = `
                    <div class="bg-white border border-slate-100 rounded-2xl p-8 flex flex-col md:flex-row justify-between items-start md:items-center shadow-sm hover:shadow-md transition group">
                        <div class="mb-4 md:mb-0">
                            <div class="flex items-center gap-3 mb-2">
                                <span class="bg-slate-100 text-slate-600 text-xs font-bold px-2 py-1 rounded">공고</span>
                                <h4 class="text-xl font-bold text-slate-800 group-hover:text-blue-600 transition">📄 ${item.title}</h4>
                            </div>
                            <p class="text-sm text-slate-500 font-medium flex items-center gap-2">
                                <span>${item.agency}</span>
                                <span class="w-1 h-1 bg-slate-300 rounded-full"></span>
                                <span>마감: ${item.deadline}</span>
                            </p>
                            <p class="text-slate-900 font-extrabold mt-3 text-lg">💰 설계비: ${feeText}</p>
                        </div>
                        <div>
                            ${
                                isPriceAvailable
                                ? `<button onclick="openPricingModal('${safeTitle}', ${item.fee})" class="bg-blue-50 text-blue-600 hover:bg-blue-100 px-6 py-3 rounded-xl font-bold text-sm transition flex items-center gap-2">
                                        가격제안보기 <i class="fa-solid fa-chevron-down"></i>
                                   </button>`
                                : `<button class="bg-slate-50 text-slate-400 px-6 py-3 rounded-xl font-bold text-sm cursor-not-allowed">
                                        견적 불가
                                   </button>`
                            }
                        </div>
                    </div>
                `;
                container.innerHTML += html;
            });
        }

        async function performSearch() {
            const query = document.getElementById('searchInput').value.trim();
            const container = document.getElementById('search-results');
            container.innerHTML = `
                <div class="text-center py-10 text-slate-400">
                    <i class="fa-solid fa-spinner animate-spin text-3xl mb-3"></i>
                    <p>검색 중입니다...</p>
                </div>
            `;
            try {
                const resp = await fetch('/api/search?q=' + encodeURIComponent(query));
                const data = await resp.json();
                renderList(data.items || [], 'search-results');
            } catch (e) {
                container.innerHTML = `
                    <div class="text-center py-10 text-red-400">
                        검색 중 오류가 발생했습니다.
                    </div>
                `;
            }
        }

        async function filterRecommendations() {
            const min = parseInt(document.getElementById('minFee').value) || 0;
            const max = parseInt(document.getElementById('maxFee').value) || 999999999999;
            const container = document.getElementById('recommend-results');
            container.innerHTML = `
                <div class="text-center py-10 text-slate-400">
                    <i class="fa-solid fa-spinner animate-spin text-3xl mb-3"></i>
                    <p>추천 공모를 불러오는 중입니다...</p>
                </div>
            `;
            try {
                const params = new URLSearchParams({ min: String(min), max: String(max) });
                const resp = await fetch('/api/recommend?' + params.toString());
                const data = await resp.json();
                renderList(data.items || [], 'recommend-results');
            } catch (e) {
                container.innerHTML = `
                    <div class="text-center py-10 text-red-400">
                        추천 리스트 로딩 중 오류가 발생했습니다.
                    </div>
                `;
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
                const body = `안녕하세요, 위너스케치 견적 시스템을 통해 문의드립니다.\n\n1. 프로젝트명: ${title}\n2. 공고 설계비: ${fee.toLocaleString()}원\n3. 선택 플랜: ${planName}\n4. 예상 견적가: ${price.toLocaleString()}원 (적용 요율 ${result.rate}%)\n5. 비고: ${result.note}\n\n--------------------------------------------------\n[추가 요청 사항]\n(이곳에 원하시는 작업 범위나 일정을 적어주세요.)\n--------------------------------------------------`;
                return `mailto:${OWNER_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
            };

            document.getElementById('link-basic').href = createLink("BASIC", result.plans.basic);
            document.getElementById('link-premium').href = createLink("PREMIUM", result.plans.premium);
            document.getElementById('link-express').href = createLink("EXPRESS", result.plans.express);

            document.getElementById('pricing-modal').classList.remove('hidden');
        }

        function closeModal() {
            document.getElementById('pricing-modal').classList.add('hidden');
        }

        window.onclick = function(event) {
            const modal = document.getElementById('pricing-modal');
            if (event.target == modal) {
                closeModal();
            }
        }
    </script>
</body>
</html>
"""


# ==============================
# 4. Flask 라우트
# ==============================

@app.route("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html")


@app.get("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    # q가 없으면 빈 리스트 반환
    if not q:
        return jsonify({"items": []})

    items, _logs = get_competition_data(q, rows=100, strict_mode=False)

    # [추가됨] 수동 데이터 검색
    for manual_item in MANUAL_DATA:
        if q in manual_item["title"] or q in manual_item["agency"]:
            # 중복 체크
            is_duplicate = False
            for api_item in items:
                if (api_item["title"] == manual_item["title"] and 
                    api_item["agency"] == manual_item["agency"]):
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                items.append(manual_item)

    # 날짜순 정렬
    items.sort(
        key=lambda x: x["deadline"] if x["deadline"] != "-" else "0000-00-00",
        reverse=False,
    )

    return jsonify({"items": items})


@app.get("/api/recommend")
def api_recommend():
    # ... (min_fee, max_fee 파라미터 파싱 부분 생략) ...
    try:
        min_fee = int(request.args.get("min", "0") or 0)
    except ValueError:
        min_fee = 0

    try:
        max_fee = int(request.args.get("max", "999999999999") or 999999999999)
    except ValueError:
        max_fee = 999999999999

    # 1. 나라장터 데이터 수집 (기존 로직)
    keywords = ["건축설계", "설계공모", "실시설계", "리모델링"]
    merged = []
    seen = set()

    for kw in keywords:
        res, _ = get_competition_data(kw, rows=200, strict_mode=True)
        for item in res:
            uid = f"{item['title']}_{item['agency']}"
            if uid in seen:
                continue
            seen.add(uid)
            if not (min_fee <= item["fee"] <= max_fee):
                continue
            merged.append(item)

    # ✅ [추가됨] 2. 수동 데이터(MANUAL_DATA) 합치기
    for item in MANUAL_DATA:
        uid = f"{item['title']}_{item['agency']}"
        
        # 이미 리스트에 있으면 패스
        if uid in seen:
            continue
        
        # 금액 필터링 적용 (범위에 안 맞으면 패스)
        if not (min_fee <= item["fee"] <= max_fee):
            continue
            
        merged.append(item)
        seen.add(uid)

    # 정렬 및 반환
    merged.sort(
        key=lambda x: x["deadline"] if x["deadline"] != "-" else "0000-00-00",
        reverse=False,
    )

    return jsonify({"items": merged})