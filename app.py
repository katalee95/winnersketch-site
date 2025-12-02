import streamlit as st
import pandas as pd
import math
import re
from datetime import datetime, timedelta
import requests
import json
import urllib3
import xml.etree.ElementTree as ET
from urllib.parse import unquote, quote as url_quote

# SSL 경고 숨기기
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 0. 필수 설정 (API 키, 이메일은 secrets에서 읽기)
# ==========================================
# Streamlit Cloud에서 Settings → Secrets에 아래 키 추가 예정:
# REAL_API_KEY = "실제_공공데이터_API_키"
# OWNER_EMAIL = "altjr1643@gmail.com"

def get_secret(name: str, default: str = "") -> str:
    """
    1순위: st.secrets[name] (로컬 .streamlit/secrets.toml, Streamlit Cloud)
    2순위: 환경변수 (Render, 기타 서버)
    3순위: 기본값
    """
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)

REAL_API_KEY = get_secret("REAL_API_KEY", "")
OWNER_EMAIL = get_secret("OWNER_EMAIL", "altjr1643@gmail.com")

# ==========================================
# 1. 공통 디자인 (CSS)
# ==========================================
def apply_custom_design():
    st.markdown("""
        <style>
        @import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.8/dist/web/static/pretendard.css");
        html, body, [class*="css"] {
            font-family: 'Pretendard', sans-serif;
        }
        .main-title {
            font-size: 3rem !important;
            font-weight: 800 !important;
            color: #1E3A8A;
            margin-bottom: 0px !important;
        }
        .main-subtitle {
            font-size: 1.2rem !important;
            color: #555;
            font-weight: 500;
            margin-top: 10px;
            margin-bottom: 30px;
        }
        .highlight-box {
            background-color: #F8FAFC;
            border-left: 5px solid #1E3A8A;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .list-item-box {
            border: 1px solid #E2E8F0;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 15px;
            background-color: white;
        }
        .list-title { font-size: 1.3rem; font-weight: 700; color: #0F172A; }
        .list-meta { color: #64748B; font-size: 0.9rem; margin-top: 5px; }
        .list-price { font-size: 1.1rem; font-weight: 700; color: #2563EB; margin-top: 10px; }

        .pricing-container {
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            justify-content: center;
            margin-top: 20px;
        }
        .price-card {
            flex: 1;
            min-width: 300px;
            max-width: 400px;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 25px;
            background: white;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            transition: transform 0.2s;
            display: flex;
            flex-direction: column;
        }
        .price-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.15);
        }
        .price-card.premium {
            border: 2px solid #EF4444;
            background-color: #FFF5F5;
            position: relative;
        }
        .plan-name { font-size: 1.3rem; font-weight: 800; text-align: center; margin-bottom: 10px; }
        .plan-price { font-size: 1.8rem; font-weight: 900; text-align: center; color: #1E3A8A; margin-bottom: 15px; }
        .plan-desc { text-align: center; color: #64748B; font-size: 0.9rem; margin-bottom: 20px; }
        .feature-list { flex-grow: 1; margin-bottom: 20px; }
        .feature-item { font-size: 0.95rem; margin-bottom: 10px; color: #334155; display: flex; align-items: center; }
        .check-icon { color: #10B981; margin-right: 10px; font-weight: bold; }
        .cross-icon { color: #EF4444; margin-right: 10px; font-weight: bold; opacity: 0.5; }
        .card-btn {
            display: block;
            width: 100%;
            padding: 12px 0;
            text-align: center;
            border-radius: 8px;
            text-decoration: none;
            font-weight: bold;
            transition: background 0.3s;
        }
        @media (max-width: 768px) {
            .main-title { font-size: 2rem !important; }
            .pricing-container { flex-direction: column; align-items: center; }
            .price-card { width: 100%; max-width: 100%; }
        }
        </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. 견적 계산 관련 함수들 (기존 코드에서 그대로 복붙)
# ==========================================

def calculate_base_fee(design_fee):
    # 👉 여기부터 ~ get_competition_data, render_price_cards까지
    #    네가 올렸던 코드 그대로 가져오면 됩니다.
    if not design_fee: return 0, 0, "정보 없음"
    try:
        if isinstance(design_fee, str): design_fee = int(design_fee.replace(',', ''))
        fee_val = float(design_fee)
        
        if fee_val < 1000000000: 
            if fee_val >= 300000000:
                base_fee = 300000000
                step_unit = 10000000 
                steps = (fee_val - base_fee) // step_unit
                discount = steps * 0.01
                rate_percent = 1.0 - discount
                if rate_percent < 0.5: rate_percent = 0.5
                rate_percent = round(rate_percent, 2)
                raw_quote = fee_val * (rate_percent / 100.0)
                note = f"규모 할인 ({rate_percent}%)"
            else:
                rate_percent = 1.0
                raw_quote = fee_val * 0.01
                note = "기본 요율 (1.0%)"
        else:
            rate_percent = 0.8
            raw_quote = fee_val * 0.008
            note = "대형 프로젝트 (0.8%)"

        final_quote = raw_quote
        if raw_quote <= 500000:
            final_quote = raw_quote + 500000
            note = "최소 작업비용 보정"
        elif raw_quote < 1000000:
            final_quote = 1000000
            note = "최소 견적 하한선 적용"

        final_rate = round((final_quote / fee_val) * 100, 2)
        base_quote = math.floor(final_quote / 10000) * 10000
        return int(base_quote), final_rate, note
    except Exception:
        return 0, 0, "계산 오류"

def calculate_plan_prices(base_quote):
    return {
        "BASIC": int(math.floor((base_quote * 0.8) / 10000) * 10000),
        "PREMIUM": int(base_quote),
        "EXPRESS": int(math.floor((base_quote * 1.2) / 10000) * 10000)
    }

def create_mailto_link(project_name, design_fee, plan_name, plan_price, rate, note):
    subject = f"[견적의뢰] {project_name} - {plan_name} 플랜"
    body = f"""
안녕하세요, 위너스케치 견적 시스템을 통해 문의드립니다.

1. 프로젝트명: {project_name}
2. 공고 설계비: {format(design_fee, ',')}원
3. 선택 플랜: {plan_name}
4. 예상 견적가: {format(plan_price, ',')}원 (적용 요율 {rate}%)
5. 비고: {note}

--------------------------------------------------
[추가 요청 사항]
(이곳에 원하시는 작업 범위나 일정을 적어주세요.)
--------------------------------------------------
    """
    safe_subject = url_quote(subject)
    safe_body = url_quote(body)
    return f"mailto:{OWNER_EMAIL}?subject={safe_subject}&body={safe_body}"

def parse_api_response(response, source_name):
    try:
        data = response.json()
        body = data.get('response', {}).get('body', {})
        items = body.get('items')
        return items if items else []
    except json.JSONDecodeError:
        try:
            root = ET.fromstring(response.text)
            items = []
            for item in root.findall('.//item'):
                row = {}
                for child in item:
                    row[child.tag] = child.text
                items.append(row)
            if items: return items
            else: return []
        except Exception:
            return []

def fetch_data_from_url(base_url, params, api_key):
    headers = {'User-Agent': 'Mozilla/5.0'}
    if "%" in api_key: final_key = api_key
    else: final_key = url_quote(api_key)
    full_url = f"{base_url}?serviceKey={final_key}"
    try:
        response = requests.get(full_url, params=params, verify=False, timeout=20, headers=headers)
        if response.status_code != 200:
            return [], {"status": response.status_code, "response": "Error"}
        parsed_data = parse_api_response(response, "API")
        return parsed_data, {"status": 200, "response": "Success"}
    except Exception as e:
        return [], {"status": "Exception", "response": str(e)}

def get_competition_data(keyword, rows=100, strict_mode=False):
    clean_key = REAL_API_KEY.strip()
    if clean_key == "": return [], []

    now = datetime.now()
    days_to_fetch = 30
    inqryBgnDt = (now - timedelta(days=days_to_fetch)).strftime("%Y%m%d0000")
    inqryEndDt = now.strftime("%Y%m%d2359")

    params = {
        'numOfRows': str(rows),
        'pageNo': '1',
        'type': 'json',
        'inqryDiv': '1',
        'inqryBgnDt': inqryBgnDt,
        'inqryEndDt': inqryEndDt
    }

    targets = [
        ("https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch", "신버전(조달)"),
        ("https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcOrgnSearch", "신버전(자체)"),
        ("https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch", "구버전(조달)"),
        ("https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcOrgnSearch", "구버전(자체)")
    ]

    all_results, all_debugs = [], []
    for url, type_label in targets:
        current_params = params.copy()
        current_params['bidNm'] = keyword
        current_params['bidNtceNm'] = keyword
        items, debug_log = fetch_data_from_url(url, current_params, clean_key)
        all_debugs.append(f"[{type_label}] {debug_log['response']}")
        for item in items:
            item['type_label'] = type_label
            all_results.append(item)

    if not all_results: return [], all_debugs

    cleaned_results, seen_ids = [], set()
    exclude_keywords = ["철거", "관리", "운영", "개량", "검토", "복원", "임도", "산림", "산불", "예방", "폐기", "설치", "보수", "전기", "사방", "정비", "급수", "교량", "지표", "고도화", "감리", "안전진단"]
    if strict_mode:
        must_have_keywords = ["설계공모", "설계 공모", "실시 설계", "실시설계", "건축설계", "리모델링"]
    else:
        must_have_keywords = ["설계"]

    for item in all_results:
        bid_id = item.get('bidNtceNo')
        if bid_id in seen_ids: continue
        title = item.get('bidNtceNm', '')
        agency = item.get('ntceInsttNm') or item.get('dminsttNm') or ""

        if not strict_mode:
            if keyword not in title and keyword not in agency: continue
        if not any(mk in title for mk in must_have_keywords): continue
        if any(ex in title for ex in exclude_keywords): continue

        seen_ids.add(bid_id)
        price = item.get('presmptPrce', 0)
        if price: price = int(price)
        cleaned_results.append({
            "공고명": title,
            "공고기관": agency,
            "설계비": price,
            "마감일": item.get('bidClseDt', '-')[:16]
        })

    cleaned_results.sort(
        key=lambda x: x['마감일'] if x['마감일'] != '-' else '0000',
        reverse=True
    )
    return cleaned_results, all_debugs

def render_price_cards(project_name, design_fee, base_quote, base_rate, note):
    plans = calculate_plan_prices(base_quote)

    link_basic = create_mailto_link(project_name, design_fee, "BASIC", plans['BASIC'], base_rate, note)
    link_premium = create_mailto_link(project_name, design_fee, "PREMIUM", plans['PREMIUM'], base_rate, note)
    link_express = create_mailto_link(project_name, design_fee, "EXPRESS", plans['EXPRESS'], base_rate, note)

    html_code = f"""
    <div class="pricing-container">
        <div class="price-card">
            <div class="plan-name" style="color:#1E3A8A">BASIC</div>
            <div class="plan-price" style="color:#1E3A8A">{format(plans['BASIC'], ',')}원</div>
            <div class="plan-desc">실속형 패키지 (80%)</div>
            <hr style="margin: 15px 0; border: 0; border-top: 1px solid #ddd;">
            <div class="feature-list">
                <div class="feature-item"><span class="check-icon">✔</span> 작업 기간: <b>2주</b></div>
                <div class="feature-item"><span class="check-icon">✔</span> 컷 장수: 5컷 이내</div>
                <div class="feature-item"><span class="check-icon">✔</span> 수정 횟수: 2회</div>
                <div class="feature-item"><span class="check-icon">✔</span> 3D 원본 제공</div>
                <div class="feature-item"><span class="cross-icon">✘</span> 3D 영상 작업</div>
                <div class="feature-item"><span class="cross-icon">✘</span> 긴급 작업 지원</div>
            </div>
            <a href="{link_basic}" target="_blank" class="card-btn" style="background-color:#F1F5F9; color:#1E293B; border:1px solid #CBD5E1;">선택하기</a>
        </div>

        <div class="price-card premium">
            <div class="plan-name" style="color:#EF4444">👑 PREMIUM</div>
            <div class="plan-price" style="color:#EF4444">{format(plans['PREMIUM'], ',')}원</div>
            <div class="plan-desc">표준형 패키지 (100%)</div>
            <hr style="margin: 15px 0; border: 0; border-top: 1px solid #EF4444;">
            <div class="feature-list">
                <div class="feature-item"><span class="check-icon">✔</span> 작업 기간: <b>1주</b></div>
                <div class="feature-item"><span class="check-icon">✔</span> 컷 장수: <b>무제한</b></div>
                <div class="feature-item"><span class="check-icon">✔</span> 수정 횟수: <b>무제한</b></div>
                <div class="feature-item"><span class="check-icon">✔</span> 3D 원본 제공</div>
                <div class="feature-item"><span class="check-icon">✔</span> <b>3D 영상 작업 포함</b></div>
                <div class="feature-item"><span class="cross-icon">✘</span> 긴급 작업 지원</div>
            </div>
            <a href="{link_premium}" target="_blank" class="card-btn" style="background-color:#EF4444; color:white;">선택하기</a>
        </div>

        <div class="price-card">
            <div class="plan-name" style="color:#1E3A8A">EXPRESS</div>
            <div class="plan-price" style="color:#1E3A8A">{format(plans['EXPRESS'], ',')}원</div>
            <div class="plan-desc">긴급형 패키지 (120%)</div>
            <hr style="margin: 15px 0; border: 0; border-top: 1px solid #ddd;">
            <div class="feature-list">
                <div class="feature-item"><span class="check-icon">✔</span> 작업 기간: <b>4일 이내</b></div>
                <div class="feature-item"><span class="check-icon">✔</span> 컷 장수: <b>무제한</b></div>
                <div class="feature-item"><span class="check-icon">✔</span> 수정 횟수: <b>무제한</b></div>
                <div class="feature-item"><span class="check-icon">✔</span> 3D 원본 제공</div>
                <div class="feature-item"><span class="check-icon">✔</span> 3D 영상 작업 포함</div>
                <div class="feature-item"><span class="check-icon">✔</span> <b>긴급 작업 지원</b></div>
            </div>
            <a href="{link_express}" target="_blank" class="card-btn" style="background-color:#F1F5F9; color:#1E293B; border:1px solid #CBD5E1;">선택하기</a>
        </div>
    </div>
    """
    st.markdown(html_code, unsafe_allow_html=True)

# ==========================================
# 3. 페이지 1: 랜딩 페이지 (카피라이팅 적용)
# ==========================================
def page_home():
    st.markdown("<h1 class='main-title'>🏆 위너스케치 (WinnerSketch)</h1>", unsafe_allow_html=True)
    st.markdown("""
    <p class='main-subtitle'>
    현상설계는 소중한 투자입니다. 그 가치를 아는 파트너를 만나세요.<br>
    합리적인 비용, 설득력 있는 퀄리티. 위너스케치
    </p>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class='highlight-box'>
        <p>7년차 전문 CG 팀의 노하우와 데이터 기반의 투명한 견적 시스템.<br>
        불확실한 결과 앞에서도 후회 없는 선택이 되도록, 최적의 솔루션을 제안합니다.</p>
    </div>
    """, unsafe_allow_html=True)

    if st.button("💰 내 프로젝트 맞춤 견적 확인하기 👉"):
        # 바로 2번 메뉴(견적 계산기)로 안내하는 느낌
        st.session_state["menu"] = "견적 계산기"

    st.markdown("---")
    st.subheader("당선과 탈락 사이, 가장 합리적인 전략은 무엇일까요?")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Risk 1. 너무 싼 곳은 불안합니다.")
        st.write("현상설계는 건축가의 의도를 정확히 시각화하는 것이 핵심입니다.")
        st.write("단순 모델링 알바는 '건축적 맥락'을 이해하지 못해 소장님의 시간을 뺏습니다.")

    with col2:
        st.markdown("#### Risk 2. 전문 업체는 부담스럽습니다.")
        st.write("당선을 장담할 수 없는 상황에서 수천만 원의 CG 비용은 큰 모험입니다.")
        st.write("작은 프로젝트 하나 맡기기엔 절차가 복잡하고 비용이 과합니다.")

    st.markdown("---")
    st.markdown("### ✅ Solution: 위너스케치 (WinnerSketch)")
    st.write("**전문가의 '퀄리티' + 합리적인 '시스템'**")
    st.write("위너스케치는 거품을 뺀 스마트 견적 시스템과 7년 업력의 전문성으로, 현상설계라는 투자의 '가성비'와 '가심비'를 모두 만족시킵니다.")

    st.markdown("---")
    st.markdown("### 우리의 핵심 경쟁력")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**01. Professional (검증된 7년의 팀워크)**")
        st.write("1인 프리랜서가 아닙니다. 7년차 전문 CG 기업의 프로세스 그대로, 도면을 완벽히 해석하고 건축물의 매력을 극대화합니다.")
    with c2:
        st.markdown("**02. Rational (데이터 기반 스마트 견적)**")
        st.write("나라장터 공고 데이터와 프로젝트 규모를 기반으로 산출된 투명한 표준 가격을 제시합니다.")
    with c3:
        st.markdown("**03. Strategic (심사위원을 설득하는 뷰)**")
        st.write("건축을 전공한 그래픽 디자이너가, 건축적 의도가 가장 잘 드러나는 구도와 분위기를 연출합니다. **'이기는 그림'**을 만듭니다.")

    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #888; font-size: 0.9rem; padding: 20px;'>
    <b>"좋은 설계가 좋은 그림으로 완성될 때, 당선은 현실이 됩니다."</b><br>
    위너스케치가 소장님의 성공적인 투자를 돕는 든든한 파트너가 되겠습니다.<br>
    📧 문의 및 의뢰: altjr1643@gmail.com
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# 4. 페이지 2: 견적 계산기 (기존 UI 전체)
# ==========================================
def page_estimator():
    st.markdown("<h1 class='main-title'>🏆 위너스케치 견적 시스템</h1>", unsafe_allow_html=True)
    st.markdown("<p class='main-subtitle'>건축 현상설계 당선을 위한 최적의 파트너 | 데이터 기반 스마트 견적</p>", unsafe_allow_html=True)

    st.markdown("""
    <div class='highlight-box'>
        <h3>"현상설계는 소중한 투자입니다."</h3>
        <p>7년차 전문 CG 팀의 노하우와 데이터 기반의 투명한 견적 시스템.<br>
        불확실한 결과 앞에서도 후회 없는 선택이 되도록, 최적의 솔루션을 제안합니다.</p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1: st.info("**01. Professional (7년의 팀워크)**\n\n1인 프리랜서가 아닙니다. 전문 CG 기업의 프로세스 그대로 도면을 완벽히 해석합니다.")
    with c2: st.info("**02. Rational (스마트 견적)**\n\n나라장터 데이터와 프로젝트 규모를 기반으로 산출된 투명한 표준 가격을 제시합니다.")
    with c3: st.info("**03. Strategic (이기는 뷰)**\n\n건축을 전공한 그래픽 디자이너가 건축적 의도를 살린 구도와 분위기를 연출합니다.")

    st.divider()

    tab1, tab2 = st.tabs(["🔍 용역 검색", "📋 추천 공모 리스트"])

    # --- TAB 1: 용역 검색 (네가 올린 코드 그대로) ---
    with tab1:
        col1, col2 = st.columns([4, 1])
        with col1:
            search_query = st.text_input("공모전 명칭 입력", placeholder="예) 해미면, 태화강, 도서관", key="main_search")
        with col2:
            st.write("")
            st.write("")
            search_btn = st.button("검색", use_container_width=True)

        if search_query or search_btn:
            with st.spinner("데이터 조회 중..."):
                results, debug_logs = get_competition_data(search_query, rows=100, strict_mode=False)

            with st.expander("개발자용 진단 데이터", expanded=False):
                for log in debug_logs:
                    st.text(log)

            if len(results) > 0:
                st.success(f"총 {len(results)}건의 공고를 찾았습니다.")
                for item in results:
                    design_fee = item['설계비']
                    item_key = f"tab1_{item['공고명']}_{item['공고기관']}"
                    if item_key not in st.session_state:
                        st.session_state[item_key] = False

                    def toggle_state(k):
                        st.session_state[k] = not st.session_state[k]

                    with st.container():
                        st.markdown(
                            f"""<div class='list-item-box'>
                            <div class='list-title'>📄 {item['공고명']}</div>
                            <div class='list-meta'>{item['공고기관']} | 마감: {item['마감일']}</div>
                            <div class='list-price'>💰 공고 설계비: {format(design_fee, ',')}원</div>
                            </div>""",
                            unsafe_allow_html=True
                        )
                        if design_fee > 0:
                            st.button("가격제안보기 👇", key=f"btn_{item_key}",
                                      on_click=toggle_state, args=(item_key,),
                                      use_container_width=True)
                            if st.session_state[item_key]:
                                st.divider()
                                base_quote, rate, note = calculate_base_fee(design_fee)
                                render_price_cards(item['공고명'], design_fee, base_quote, rate, note)
                                st.markdown("<br>", unsafe_allow_html=True)
                        else:
                            st.button("설계비 미공개 (문의하기)", key=f"btn_{item['공고명']}")
            else:
                st.warning("검색 결과가 없습니다.")
                st.info("'설계' 키워드가 포함된 용역만 검색됩니다.")

    # --- TAB 2: 추천 공모 리스트 (기존 코드 그대로) ---
    with tab2:
        st.subheader("🔥 실시간 추천 '설계공모' 리스트")
        st.caption("나라장터에서 **건축설계, 실시설계, 리모델링, 설계공모** 관련 알짜배기 공고만 모아드립니다.")

        def toggle_price_view(key):
            st.session_state[key] = not st.session_state[key]

        if 'page' not in st.session_state:
            st.session_state['page'] = 1

        if 'reco_data' not in st.session_state:
            with st.spinner("추천 공고를 수집 중입니다..."):
                keywords = ["건축설계", "설계공모", "실시설계", "리모델링"]
                merged_results = []
                for kw in keywords:
                    res, _ = get_competition_data(kw, rows=300, strict_mode=True)
                    merged_results.extend(res)
                unique_results = []
                seen_ids = set()
                for item in merged_results:
                    uid = f"{item['공고명']}_{item['공고기관']}"
                    if uid not in seen_ids:
                        seen_ids.add(uid)
                        unique_results.append(item)
                unique_results.sort(
                    key=lambda x: x['마감일'] if x['마감일'] != '-' else '0000',
                    reverse=True
                )
                st.session_state['reco_data'] = unique_results

        data = st.session_state['reco_data']

        if not data:
            st.warning("현재 진행 중인 추천 공고를 찾지 못했습니다.")
        else:
            items_per_page = 10
            total_items = len(data)
            total_pages = math.ceil(total_items / items_per_page)
            start_idx = (st.session_state['page'] - 1) * items_per_page
            end_idx = start_idx + items_per_page
            current_page_items = data[start_idx:end_idx]

            st.info(f"총 {total_items}건 중 {start_idx + 1} ~ {min(end_idx, total_items)}건 표시 (페이지 {st.session_state['page']}/{total_pages})")

            for item in current_page_items:
                design_fee = item['설계비']
                item_key = f"view_{item['공고명']}_{item['공고기관']}"
                if item_key not in st.session_state:
                    st.session_state[item_key] = False

                with st.container():
                    st.markdown(
                        f"""<div class='list-item-box'>
                        <div class='list-title'>📄 {item['공고명']}</div>
                        <div class='list-meta'>{item['공고기관']} | 마감: {item['마감일']}</div>
                        <div class='list-price'>💰 공고 설계비: {format(design_fee, ',')}원</div>
                        </div>""",
                        unsafe_allow_html=True
                    )
                    if design_fee > 0:
                        st.button("가격제안보기 👇", key=f"btn_{item_key}",
                                  on_click=toggle_price_view, args=(item_key,),
                                  use_container_width=True)
                        if st.session_state[item_key]:
                            st.divider()
                            base_quote, rate, note = calculate_base_fee(design_fee)
                            render_price_cards(item['공고명'], design_fee, base_quote, rate, note)
                            st.markdown("<br>", unsafe_allow_html=True)
                    else:
                        st.button("설계비 미공개 (문의하기)", key=f"reco_btn_{item['공고명']}")

            st.divider()
            c1, c2, c3 = st.columns([1, 2, 1])
            with c1:
                if st.session_state['page'] > 1:
                    if st.button("◀ 이전 페이지"):
                        st.session_state['page'] -= 1
                        st.rerun()
            with c3:
                if st.session_state['page'] < total_pages:
                    if st.button("다음 페이지 ▶"):
                        st.session_state['page'] += 1
                        st.rerun()

# ==========================================
# 5. 페이지 3: 포트폴리오 (지금은 비워두고 메뉴만)
# ==========================================
def page_portfolio():
    st.markdown("<h1 class='main-title'>📂 포트폴리오</h1>", unsafe_allow_html=True)
    st.markdown("<p class='main-subtitle'>준비 중입니다. 곧 위너스케치의 작업 사례를 확인하실 수 있습니다.</p>", unsafe_allow_html=True)
    st.info("인스타그램 / 유튜브 / PDF 포트폴리오 링크 등을 추후 연결할 수 있습니다.")

# ==========================================
# 6. 메인 라우팅
# ==========================================
def main():
    st.set_page_config(
        page_title="위너스케치 - 건축 현상설계 비주얼",
        page_icon="🏆",
        layout="wide"
    )

    apply_custom_design()

    # 사이드바 메뉴
    st.sidebar.title("위너스케치 (WinnerSketch)")
    if "menu" not in st.session_state:
        st.session_state["menu"] = "홈"

    menu = st.sidebar.radio(
        "메뉴",
        ["홈", "견적 계산기", "포트폴리오"],
        index=["홈", "견적 계산기", "포트폴리오"].index(st.session_state["menu"])
    )

    st.session_state["menu"] = menu

    if menu == "홈":
        page_home()
    elif menu == "견적 계산기":
        page_estimator()
    elif menu == "포트폴리오":
        page_portfolio()

if __name__ == "__main__":
    main()
