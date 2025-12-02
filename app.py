import streamlit as st
import streamlit.components.v1 as components

# 앱 기본 설정
st.set_page_config(
    page_title="위너스케치 - 건축 현상설계 파트너",
    page_icon="🏆",
    layout="wide"
)

# 여기부터는 네가 준 HTML을 그대로 붙인다
html = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>위너스케치 - 건축 현상설계 파트너</title>
    
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    
    <!-- Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

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
        
        /* 커스텀 스크롤바 */
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

        .hero-gradient {
            background: linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%);
        }

        .tab-active {
            color: #1E3A8A;
            border-bottom: 2px solid #1E3A8A;
            font-weight: 700;
        }
        .tab-inactive {
            color: #64748B;
            border-bottom: 2px solid transparent;
        }
        .tab-inactive:hover {
            color: #1E3A8A;
        }

        /* 가격 카드 호버 효과 */
        .price-card {
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .price-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
        }

        /* 반응형 차트 컨테이너 */
        .chart-container {
            position: relative;
            width: 100%;
            max-width: 600px;
            height: 300px;
            margin: 0 auto;
        }
    </style>
</head>
<body class="antialiased">

    <!-- Navigation -->
    <nav class="w-full py-4 px-6 flex justify-between items-center border-b border-slate-100 sticky top-0 bg-white/90 backdrop-blur-sm z-50">
        <div class="text-2xl font-black text-blue-900 tracking-tighter cursor-pointer" onclick="window.scrollTo(0,0)">
            WINNERSKETCH
        </div>
        <a href="mailto:altjr1643@gmail.com" class="text-sm font-semibold text-slate-600 hover:text-blue-900 transition">
            문의하기
        </a>
    </nav>

    <!-- 1. Main Hero Section -->
    <section class="hero-gradient pt-20 pb-16 px-4 text-center">
        <div class="max-w-4xl mx-auto">
            <h1 class="text-4xl md:text-6xl font-black text-slate-900 leading-tight mb-6 break-keep">
                현상설계는 소중한 투자입니다.<br>
                <span class="text-blue-700">그 가치를 아는 파트너를 만나세요.</span>
            </h1>
            <p class="text-lg md:text-xl text-slate-600 mb-10 max-w-2xl mx-auto leading-relaxed break-keep">
                7년차 전문 CG 팀의 노하우와 데이터 기반의 투명한 견적 시스템.<br>
                불확실한 결과 앞에서도 후회 없는 선택이 되도록, 최적의 솔루션을 제안합니다.
            </p>
            <a href="#app-section" class="inline-block bg-blue-600 hover:bg-blue-700 text-white font-bold text-lg py-4 px-10 rounded-full shadow-lg hover:shadow-xl transition transform hover:-translate-y-1">
                내 프로젝트 맞춤 견적 확인하기 👉
            </a>
        </div>
    </section>

    <!-- 2. Problem & Solution (Key Features) -->
    <section class="py-20 bg-white">
        <div class="max-w-6xl mx-auto px-4">
            <div class="text-center mb-16">
                <h2 class="text-3xl font-bold text-slate-900 mb-4">당선과 탈락 사이, 가장 합리적인 전략</h2>
                <p class="text-slate-500">전문가의 퀄리티와 합리적인 시스템을 결합했습니다.</p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
                <!-- Feature 1 -->
                <div class="bg-slate-50 p-8 rounded-2xl hover:bg-slate-100 transition border border-slate-100">
                    <div class="w-14 h-14 bg-blue-100 rounded-full flex items-center justify-center text-blue-600 text-2xl mb-6">
                        <i class="fa-solid fa-users-gear"></i>
                    </div>
                    <h3 class="text-xl font-bold text-slate-900 mb-3">Professional</h3>
                    <p class="text-slate-600 leading-relaxed text-sm break-keep">
                        <b>검증된 7년의 팀워크.</b> 우리는 1인 프리랜서가 아닙니다. 전문 CG 기업의 프로세스 그대로 도면을 완벽히 해석하고 건축의 언어로 소통합니다.
                    </p>
                </div>

                <!-- Feature 2 -->
                <div class="bg-slate-50 p-8 rounded-2xl hover:bg-slate-100 transition border border-slate-100">
                    <div class="w-14 h-14 bg-blue-100 rounded-full flex items-center justify-center text-blue-600 text-2xl mb-6">
                        <i class="fa-solid fa-chart-pie"></i>
                    </div>
                    <h3 class="text-xl font-bold text-slate-900 mb-3">Rational</h3>
                    <p class="text-slate-600 leading-relaxed text-sm break-keep">
                        <b>데이터 기반 스마트 견적.</b> 나라장터 공고 데이터와 프로젝트 규모를 기반으로 산출된 투명한 표준 가격을 제시합니다.
                    </p>
                </div>

                <!-- Feature 3 -->
                <div class="bg-slate-50 p-8 rounded-2xl hover:bg-slate-100 transition border border-slate-100">
                    <div class="w-14 h-14 bg-blue-100 rounded-full flex items-center justify-center text-blue-600 text-2xl mb-6">
                        <i class="fa-solid fa-lightbulb"></i>
                    </div>
                    <h3 class="text-xl font-bold text-slate-900 mb-3">Strategic</h3>
                    <p class="text-slate-600 leading-relaxed text-sm break-keep">
                        <b>심사위원을 설득하는 뷰.</b> 건축을 전공한 그래픽 디자이너가 건축적 의도를 가장 잘 살린 구도와 분위기로 '이기는 그림'을 완성합니다.
                    </p>
                </div>
            </div>
        </div>
    </section>

    <!-- 3. Interactive App Section -->
    <section id="app-section" class="py-20 bg-slate-50 border-t border-slate-200">
        <div class="max-w-3xl mx-auto px-4">
            
            <div class="text-center mb-10">
                <h2 class="text-3xl font-black text-slate-900 mb-2">위너스케치 견적 시스템</h2>
                <p class="text-slate-500 text-sm">새로운 공모들을 만나보고, 즉시 견적을 확인하세요.</p>
            </div>

            <!-- Tabs -->
            <div class="flex justify-center mb-8 border-b border-slate-200">
                <button id="tab-search" class="tab-active px-6 py-3 transition text-lg" onclick="switchTab('search')">
                    <i class="fa-solid fa-magnifying-glass mr-2"></i>용역 검색
                </button>
                <button id="tab-recommend" class="tab-inactive px-6 py-3 transition text-lg" onclick="switchTab('recommend')">
                    <i class="fa-solid fa-thumbs-up mr-2"></i>추천 공모 리스트
                </button>
            </div>

            <!-- Content Area -->
            <div class="bg-white rounded-2xl shadow-xl p-6 md:p-8 min-h-[400px]">
                
                <!-- Tab 1: General Search -->
                <div id="content-search" class="block">
                    <div class="relative mb-6">
                        <input type="text" id="searchInput" placeholder="공모전 명칭 입력 (예: 해미면, 태화강, 도서관)" 
                            class="w-full bg-slate-50 border border-slate-200 rounded-xl py-4 pl-12 pr-4 text-lg focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition">
                        <i class="fa-solid fa-search absolute left-4 top-1/2 transform -translate-y-1/2 text-slate-400"></i>
                        <button onclick="performSearch()" class="absolute right-2 top-2 bottom-2 bg-blue-600 text-white px-6 rounded-lg font-bold hover:bg-blue-700 transition">
                            검색
                        </button>
                    </div>
                    <div id="search-results" class="space-y-4">
                        <div class="text-center py-10 text-slate-400">
                            <i class="fa-regular fa-folder-open text-4xl mb-3"></i>
                            <p>'설계' 키워드가 포함된 용역만 검색됩니다.</p>
                        </div>
                    </div>
                </div>

                <!-- Tab 2: Recommended List -->
                <div id="content-recommend" class="hidden">
                    
                    <!-- Filter -->
                    <div class="bg-slate-50 p-4 rounded-xl mb-6 border border-slate-100">
                        <label class="block text-xs font-bold text-slate-500 mb-2 uppercase tracking-wide">설계비 범위 설정</label>
                        <div class="flex items-center gap-4">
                            <div class="flex-1">
                                <input type="number" id="minFee" value="0" class="w-full p-2 border border-slate-200 rounded text-sm" placeholder="최소금액">
                            </div>
                            <span class="text-slate-400">~</span>
                            <div class="flex-1">
                                <input type="number" id="maxFee" value="5000000000" class="w-full p-2 border border-slate-200 rounded text-sm" placeholder="최대금액">
                            </div>
                            <button onclick="filterRecommendations()" class="bg-slate-800 text-white px-4 py-2 rounded text-sm hover:bg-slate-900 transition">
                                적용
                            </button>
                        </div>
                    </div>

                    <div id="recommend-results" class="space-y-4"></div>
                </div>

            </div>
        </div>
    </section>

    <!-- Pricing Modal Overlay -->
    <div id="pricing-modal" class="fixed inset-0 bg-black/50 z-[100] hidden flex items-center justify-center p-4 backdrop-blur-sm overflow-y-auto">
        <div class="bg-white rounded-2xl w-full max-w-5xl my-8 relative shadow-2xl">
            <button onclick="closeModal()" class="absolute top-4 right-4 text-slate-400 hover:text-slate-800 text-2xl z-10">
                <i class="fa-solid fa-xmark"></i>
            </button>
            
            <div class="p-8">
                <div class="text-center mb-10">
                    <span class="bg-blue-100 text-blue-700 text-xs font-bold px-3 py-1 rounded-full uppercase tracking-wide mb-2 inline-block">Project Quote</span>
                    <h3 id="modal-title" class="text-2xl font-bold text-slate-900 mb-2">공모전 제목</h3>
                    <p class="text-slate-500">공고 설계비: <span id="modal-fee" class="font-bold text-slate-800">0원</span></p>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <!-- Basic Plan -->
                    <div class="price-card border border-slate-200 rounded-xl p-6 text-center relative bg-white">
                        <h4 class="text-xl font-bold text-slate-700 mb-2">BASIC</h4>
                        <div id="price-basic" class="text-3xl font-black text-slate-800 mb-2">0원</div>
                        <p class="text-xs text-slate-400 mb-6">실속형 패키지 (80%)</p>
                        
                        <div class="space-y-3 text-left text-sm text-slate-600 mb-8">
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> 작업 기간: <b>2주</b></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> 컷 장수: 5컷 이내</div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> 수정 횟수: 2회</div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> 3D 원본 제공</div>
                            <div class="flex items-center opacity-50"><i class="fa-solid fa-xmark text-red-400 w-6"></i> 3D 영상 작업</div>
                            <div class="flex items-center opacity-50"><i class="fa-solid fa-xmark text-red-400 w-6"></i> 긴급 작업 지원</div>
                        </div>
                        <a id="link-basic" href="#" target="_blank" class="block w-full py-3 bg-slate-100 text-slate-800 font-bold rounded-lg hover:bg-slate-200 transition">선택하기</a>
                    </div>

                    <!-- Premium Plan -->
                    <div class="price-card border-2 border-red-500 bg-red-50/10 rounded-xl p-6 text-center relative transform md:-translate-y-4 shadow-xl">
                        <div class="absolute top-0 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-red-500 text-white text-xs font-bold px-3 py-1 rounded-full shadow-sm">
                            BEST CHOICE
                        </div>
                        <h4 class="text-xl font-bold text-red-500 mb-2">PREMIUM</h4>
                        <div id="price-premium" class="text-3xl font-black text-red-500 mb-2">0원</div>
                        <p class="text-xs text-red-400/80 mb-6">표준형 패키지 (100%)</p>
                        
                        <div class="space-y-3 text-left text-sm text-slate-700 mb-8">
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> 작업 기간: <b>1주</b></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> 컷 장수: <b>무제한</b></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> 수정 횟수: <b>무제한</b></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-red-500 w-6"></i> 3D 원본 제공</div>
                            <div class="flex items-center font-bold text-red-600 bg-red-50 p-1 rounded"><i class="fa-solid fa-check text-red-500 w-6"></i> 3D 영상 작업 포함</div>
                            <div class="flex items-center opacity-50"><i class="fa-solid fa-xmark text-red-400 w-6"></i> 긴급 작업 지원</div>
                        </div>
                        <a id="link-premium" href="#" target="_blank" class="block w-full py-3 bg-red-500 text-white font-bold rounded-lg hover:bg-red-600 transition shadow-md hover:shadow-lg">선택하기</a>
                    </div>

                    <!-- Express Plan -->
                    <div class="price-card border border-slate-200 rounded-xl p-6 text-center relative bg-white">
                        <h4 class="text-xl font-bold text-blue-600 mb-2">EXPRESS</h4>
                        <div id="price-express" class="text-3xl font-black text-blue-600 mb-2">0원</div>
                        <p class="text-xs text-slate-400 mb-6">긴급형 패키지 (120%)</p>
                        
                        <div class="space-y-3 text-left text-sm text-slate-600 mb-8">
                            <div class="flex items-center"><i class="fa-solid fa-bolt text-blue-500 w-6"></i> 작업 기간: <b>4일 이내</b></div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> 컷 장수: 무제한</div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> 수정 횟수: 무제한</div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> 3D 원본 제공</div>
                            <div class="flex items-center"><i class="fa-solid fa-check text-green-500 w-6"></i> 3D 영상 작업 포함</div>
                            <div class="flex items-center font-bold text-blue-600 bg-blue-50 p-1 rounded"><i class="fa-solid fa-check text-blue-500 w-6"></i> 긴급 작업 우선순위</div>
                        </div>
                        <a id="link-express" href="#" target="_blank" class="block w-full py-3 bg-slate-100 text-slate-800 font-bold rounded-lg hover:bg-slate-200 transition">선택하기</a>
                    </div>

                </div>
            </div>
        </div>
    </div>

    <!-- Footer -->
    <footer class="bg-slate-900 text-slate-400 py-12 text-center mt-20">
        <h3 class="text-white font-bold text-lg mb-2">위너스케치에서 쉽고 합리적으로.</h3>
        <p class="mb-6 text-sm">건축 현상설계 당선을 위한 최적의 파트너</p>
        <p class="text-xs border-t border-slate-800 pt-6 mt-6 max-w-xl mx-auto">
            위너스케치 | 대표: 홍길동 | 사업자등록번호: 000-00-00000<br>
            문의: altjr1643@gmail.com | Copyright © WinnerSketch. All rights reserved.
        </p>
    </footer>

    <!-- JavaScript Logic -->
    <script>
        const OWNER_EMAIL = "altjr1643@gmail.com";

        const mockData = [
            { id: 1, title: "태화강 친환경 목조전망대 건립공사 건축설계 공모", agency: "울산광역시", fee: 2503539000, deadline: "2025-12-01" },
            { id: 2, title: "해미면 농촌중심지활성화사업 다가치일상센터 건립 실시설계용역", agency: "충청남도 서산시", fee: 323201818, deadline: "2025-11-24" },
            { id: 3, title: "서울 시립 도서관 건립 설계공모", agency: "서울특별시", fee: 450000000, deadline: "2025-06-30" },
            { id: 4, title: "부산 에코델타시티 체육센터 건립 설계공모", agency: "부산광역시", fee: 320000000, deadline: "2025-07-15" },
            { id: 5, title: "대전 제2테크노밸리 혁신센터 설계공모", agency: "경기주택도시공사", fee: 1200000000, deadline: "2025-08-01" },
            { id: 6, title: "서산시 국민체육센터 건립 설계용역", agency: "서산시", fee: 88154545, deadline: "2025-12-12" },
            { id: 7, title: "강남구 노인복지관 리모델링 제안공모", agency: "서울특별시 강남구", fee: 55000000, deadline: "2025-09-05" },
            { id: 8, title: "우이신설도시철도 LTE-R 구축 실시설계 용역", agency: "우이신설경전철운영", fee: 0, deadline: "2025-12-05" }
        ];

        function calculateFees(fee) {
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
                searchTab.className = "tab-active px-6 py-3 transition text-lg";
                recoTab.className = "tab-inactive px-6 py-3 transition text-lg";
            } else {
                searchContent.classList.add('hidden');
                recoContent.classList.remove('hidden');
                searchTab.className = "tab-inactive px-6 py-3 transition text-lg";
                recoTab.className = "tab-active px-6 py-3 transition text-lg";
                filterRecommendations();
            }
        }

        function renderList(items, containerId) {
            const container = document.getElementById(containerId);
            container.innerHTML = "";

            if (items.length === 0) {
                container.innerHTML = `
                    <div class="text-center py-10 bg-slate-50 rounded-xl border border-dashed border-slate-300">
                        <p class="text-slate-500">조건에 맞는 공고가 없습니다.</p>
                    </div>`;
                return;
            }

            items.forEach(item => {
                const feeText = item.fee > 0 ? `${item.fee.toLocaleString()}원` : "설계비 미공개";
                const isPriceAvailable = item.fee > 0;
                
                const html = `
                    <div class="bg-white border border-slate-200 rounded-xl p-6 flex flex-col md:flex-row justify-between items-start md:items-center hover:shadow-md transition">
                        <div class="mb-4 md:mb-0">
                            <h4 class="text-lg font-bold text-slate-800 mb-1">📄 ${item.title}</h4>
                            <p class="text-sm text-slate-500">${item.agency} | 마감: ${item.deadline}</p>
                            <p class="text-blue-600 font-bold mt-2">💰 공고 설계비: ${feeText}</p>
                        </div>
                        <div>
                            ${isPriceAvailable ? 
                                `<button onclick="openPricingModal('${item.title.replace(/'/g, "\\'")}', ${item.fee})" class="bg-slate-100 text-slate-700 hover:bg-slate-200 px-5 py-2 rounded-lg font-bold text-sm transition">
                                    가격제안보기 👇
                                </button>` : 
                                `<button class="bg-slate-50 text-slate-400 px-5 py-2 rounded-lg font-bold text-sm cursor-not-allowed">
                                    견적 불가
                                </button>`
                            }
                        </div>
                    </div>
                `;
                container.innerHTML += html;
            });
        }

        function performSearch() {
            const query = document.getElementById('searchInput').value.trim();
            const badKeywords = ["철거", "관리", "운영", "개량", "검토", "복원", "임도", "산림", "산불", "예방", "폐기", "설치", "보수", "전기", "사방", "정비", "급수", "교량", "지표", "고도화", "감리", "안전진단"];
            
            const results = mockData.filter(item => {
                const title = item.title;
                if (!title.includes("설계")) return false;
                if (badKeywords.some(bad => title.includes(bad))) return false;
                if (query && !title.includes(query) && !item.agency.includes(query)) return false;
                return true;
            });

            renderList(results, 'search-results');
        }

        function filterRecommendations() {
            const min = parseInt(document.getElementById('minFee').value) || 0;
            const max = parseInt(document.getElementById('maxFee').value) || 999999999999;
            
            const goodKeywords = ["설계공모", "설계 공모", "실시설계", "실시 설계", "리모델링"];
            const badKeywords = ["철거", "관리", "운영", "개량", "검토", "복원", "임도", "산림", "산불", "예방", "폐기", "설치", "보수", "전기", "사방", "정비", "급수", "교량", "지표", "고도화", "감리", "안전진단"];

            const results = mockData.filter(item => {
                const title = item.title;
                if (!goodKeywords.some(good => title.includes(good))) return false;
                if (badKeywords.some(bad => title.includes(bad))) return false;
                if (item.fee < min || item.fee > max) return false;
                return true;
            });

            renderList(results, 'recommend-results');
        }

        function openPricingModal(title, fee) {
            const result = calculateFees(fee);
            
            document.getElementById('modal-title').innerText = title;
            document.getElementById('modal-fee').innerText = fee.toLocaleString() + "원";
            
            document.getElementById('price-basic').innerText = result.plans.basic.toLocaleString() + "원";
            document.getElementById('price-premium').innerText = result.plans.premium.toLocaleString() + "원";
            document.getElementById('price-express').innerText = result.plans.express.toLocaleString() + "원";

            const createLink = (planName, price) => {
                const subject = `[견적의뢰] ${title} - ${planName} 플랜`;
                const body = `안녕하세요, 위너스케치 견적 시스템을 통해 문의드립니다.\\n\\n1. 프로젝트명: ${title}\\n2. 공고 설계비: ${fee.toLocaleString()}원\\n3. 선택 플랜: ${planName}\\n4. 예상 견적가: ${price.toLocaleString()}원 (적용 요율 ${result.rate}%)\\n5. 비고: ${result.note}\\n\\n--------------------------------------------------\\n[추가 요청 사항]\\n(이곳에 원하시는 작업 범위나 일정을 적어주세요.)\\n--------------------------------------------------`;
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

# HTML 전체를 Streamlit 안에 임베드
components.html(html, height=2200, scrolling=True)
