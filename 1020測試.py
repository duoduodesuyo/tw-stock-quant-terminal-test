# ==============================================================================
# 1. 模組引入區 (各功能庫載入)
# ==============================================================================
import os                                      # 用於讀取系統環境變數
import re                                      # 正規表達式，用於新聞標題相似度比對與清洗
import urllib.request                          # 用於發送 HTTP 請求抓取備用新聞來源
import xml.etree.ElementTree as ET             # 用於解析 RSS 新聞的 XML 格式
from datetime import datetime, timedelta       # 時間與日期處理模組

import streamlit as st                         # 本地視覺化互動介面框架
import pandas as pd                            # 數據結構與時間序列處理
import numpy as np                             # 數值計算與矩陣運算
import plotly.graph_objects as go              # 繪製專業金融 K 線與圖表
from plotly.subplots import make_subplots      # 繪製多面板子圖 (K線 + 成交量)
import yfinance as yf                          # 抓取 Yahoo Finance 股票歷史數據與即時新聞的 API 庫

# 嘗試載入 Google 官方 Gemini AI 套件 (若尚未安裝或無金鑰，會平穩降級)
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


# ==============================================================================
# 2. 全域設定、側邊欄金鑰配置與 CSS 樣式鎖定
# ==============================================================================
# 設定為全寬度頁面模式，側邊欄保持完全收合
st.set_page_config(layout="wide", page_title="量化看盤工作站", initial_sidebar_state="collapsed")


# 透過 CSS 強制約束版面高度，防止內容過多時撐開跑版

st.markdown("""
<style>
    /* 1. 徹底隱藏左上角側邊欄按鈕與側邊欄本體 */
    [data-testid="collapsedControl"] {
        display: none !important;
    }
    section[data-testid="stSidebar"] {
        display: none !important;
    }

    /* 2. 移除 Streamlit 預設過大的頂部空白 */
    .block-container { 
        padding-top: 1rem; 
        padding-bottom: 1.5rem; 
        padding-left: 2rem; 
        padding-right: 2rem; 
    }
    
    /* 3. 鎖定頂部三個資訊框的統一高度與置中對齊 */
    .top-card-container {
        height: 52px;
        display: flex;
        align-items: center;
        overflow: hidden;
    }
    
    /* 4. 限制新聞列表最大高度，超出時自動啟用滾動條 */
    .news-scroll-container {
        max-height: 290px;
        overflow-y: auto;
        padding-right: 6px;
    }
    
    /* 5. 單則新聞卡片樣式 */
    .news-card {
        padding: 6px 8px;
        margin-bottom: 6px;
        border-radius: 6px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        font-size: 13px;
    }
    
    /* 6. 投資屬性標籤 (如：營收、外資) */
    .news-tag {
        background-color: #e0f2fe;
        color: #0369a1;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: bold;
        margin-right: 6px;
    }

    /* 7. 強制彈窗按鈕內的文字與圖示不換行 */
    div[data-testid="stPopover"] button {
        white-space: nowrap !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 4px !important;
    }

    /* 8. 自訂量能比懸停氣泡提示框 (保留正常箭頭游標 + 支援滑鼠移入選取) */
    .tooltip-box {
        position: relative;
        display: inline-block;
        cursor: default; /* 保留原生一般滑鼠游標，不變問號 */
    }
    .tooltip-box .tooltip-text {
        visibility: hidden;
        width: 230px;
        background-color: #0b0f19;
        color: #e2e8f0;
        text-align: left;
        border-radius: 8px;
        padding: 9px 12px;
        position: absolute;
        z-index: 99999;
        bottom: 125%;
        right: -10px;
        opacity: 0;
        transition: opacity 0.15s ease-in-out;
        border: 1px solid rgba(59, 130, 246, 0.4);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.6);
        font-size: 11px;
        line-height: 1.5;
        white-space: normal;
        pointer-events: auto; /* 允許游標直接移到氣泡框內選取與閱讀 */
    }
    /* 隱形透明橋接層：補滿氣泡與標題間隙，防止滑鼠滑過時氣泡消失 */
    .tooltip-box .tooltip-text::before {
        content: "";
        position: absolute;
        top: 100%;
        left: 0;
        width: 100%;
        height: 16px;
    }
    /* 氣泡下方小三角箭頭 */
    .tooltip-box .tooltip-text::after {
        content: "";
        position: absolute;
        top: 100%;
        right: 18px;
        border-width: 6px;
        border-style: solid;
        border-color: #0b0f19 transparent transparent transparent;
    }
    /* 當懸停在標題或是氣泡本體時，皆保持顯示狀態 */
    .tooltip-box:hover .tooltip-text,
    .tooltip-box .tooltip-text:hover {
        visibility: visible;
        opacity: 1;
    }
</style>
""", unsafe_allow_html=True)



# ==============================================================================
# 3. 全台股票清單自動抓取與 ETF 費用表快取
# ==============================================================================
import requests
from io import StringIO

@st.cache_data(ttl=86400)  # 快取 24 小時
def get_all_taiwan_stocks() -> dict:
    """自動從證交所抓取最新全台股 (上市+上櫃) 代碼與名稱對照表"""
    stocks = {}
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    
    session = requests.Session()
    session.headers.update(headers)

    # 1. 抓取上市股票清單 (strMode=2)
    try:
        resp_twse = session.get("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", timeout=15)
        resp_twse.encoding = 'cp950'
        dfs_twse = pd.read_html(StringIO(resp_twse.text))
        if dfs_twse:
            df_twse = dfs_twse[0]
            for val in df_twse.iloc[1:, 0].dropna():
                parts = str(val).split()
                if len(parts) >= 2 and parts[0].isdigit():
                    stocks[parts[0]] = parts[1]
    except Exception as e:
        print(f"TWSE fetch error: {e}")

    # 2. 抓取上櫃股票清單 (strMode=4)
    try:
        resp_tpex = session.get("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", timeout=15)
        resp_tpex.encoding = 'cp950'
        dfs_tpex = pd.read_html(StringIO(resp_tpex.text))
        if dfs_tpex:
            df_tpex = dfs_tpex[0]
            for val in df_tpex.iloc[1:, 0].dropna():
                parts = str(val).split()
                if len(parts) >= 2 and parts[0].isdigit():
                    stocks[parts[0]] = parts[1]
    except Exception as e:
        print(f"TPEX fetch error: {e}")

    # 若全數失敗，使用保底熱門清單
    if not stocks:
        stocks = {"2330": "台積電", "2317": "鴻海", "2454": "聯發科", "0050": "元大台灣50"}

    return stocks


# 初始化載入全市場股票字典
ALL_STOCKS = get_all_taiwan_stocks()

# 確保當前股票代碼存在於狀態中
if "current_symbol" not in st.session_state:
    st.session_state["current_symbol"] = "2330"

curr_sym = st.session_state["current_symbol"]
curr_name = ALL_STOCKS.get(curr_sym, "個股")

# 讀取 ETF 管理費字典
@st.cache_data(ttl=86400)
def load_etf_fee_dict() -> dict:
    fee_dict = {}
    target_path = "/Users/howardlin/Desktop/量化製作中/台湾各etf管理费.xlsx"
    if not os.path.exists(target_path):
        target_path = "台湾各etf管理费.xlsx"
    if not os.path.exists(target_path):
        return fee_dict

    try:
        df_fee = pd.read_excel(target_path, sheet_name=0, engine='openpyxl')
        for _, row in df_fee.iterrows():
            raw_code = str(row.get('ETF代號', '')).strip()
            if not raw_code or raw_code == 'nan':
                continue
            if raw_code.isdigit() and len(raw_code) < 4:
                raw_code = raw_code.zfill(4)

            mgmt_fee = str(row.get('經理費', '--')).strip()
            cust_fee = str(row.get('保管費', '--')).strip()
            total_fee = row.get('經理費+保管費(合計)')
            if pd.notna(total_fee) and isinstance(total_fee, (int, float)):
                # 去掉原本重複的 %
                total_str = f"{total_fee * 100:.3f}".rstrip('0').rstrip('.') + "%"
            else:
                total_str = str(total_fee).strip() if pd.notna(total_fee) else "--"

            dividend = str(row.get('配息(除息月)', '--')).strip()

            fee_dict[raw_code] = {
                "name": str(row.get('ETF名稱', '')).strip(),
                "category": str(row.get('類別', '')).strip(),
                "management_fee": mgmt_fee,
                "custody_fee": cust_fee,
                "total_fee": total_str,
                "dividend_month": dividend
            }
    except Exception:
        pass
    return fee_dict

ETF_FEES = load_etf_fee_dict()


# ==============================================================================
# 4. 數據抓取與去重篩選函式
# ==============================================================================
@st.cache_data(ttl=120)
def fetch_kline_with_period(symbol: str, period_type: str = "日") -> pd.DataFrame:
    """獲取歷史數據並依據日/週/月/年進行 K 線重組合成"""
    ticker = f"{symbol}.TW" if not symbol.endswith(".TW") else symbol
    start_date = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
    try:
        df = yf.download(ticker, start=start_date, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.reset_index(inplace=True)
        if df.empty:
            return pd.DataFrame()

        df['Date'] = pd.to_datetime(df['Date'])
        
        if period_type == "週":
            df = df.set_index('Date').resample('W-FRI').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna().reset_index()
        elif period_type == "月":
            df = df.set_index('Date').resample('ME').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna().reset_index()
        elif period_type == "年":
            df = df.set_index('Date').resample('YE').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna().reset_index()

        return df
    except Exception:
        return pd.DataFrame()


def is_similar_title(t1: str, t2: str, threshold: float = 0.55) -> bool:
    """計算兩個標題的詞彙重複比例，用於自動剔除農場重複新聞"""
    words1 = set(re.findall(r'[\w]+', t1))
    words2 = set(re.findall(r'[\w]+', t2))
    if not words1 or not words2:
        return False
    intersection = words1.intersection(words2)
    return (len(intersection) / min(len(words1), len(words2))) >= threshold


@st.cache_data(ttl=300)
def fetch_filtered_news(symbol: str) -> list:
    """多渠道抓取新聞，並進行投資價值篩選與去重"""
    raw_candidates = []
    INVESTMENT_KEYWORDS = ["營收", "獲利", "法說", "外資", "目標價", "產能", "擴產", "訂單", "毛利", "股利", "配息", "資本支出", "供應鏈", "自結"]

    # 1. 優先從 Yahoo Finance API 抓取
    try:
        t = yf.Ticker(f"{symbol}.TW")
        if t.news:
            for n in t.news:
                raw_candidates.append({
                    "title": n.get("title", ""),
                    "link": n.get("link", "#"),
                    "time": datetime.fromtimestamp(n.get("providerPublishTime", 0)).strftime("%m/%d %H:%M") if n.get("providerPublishTime") else "即時"
                })
    except Exception:
        pass

    # 2. 備用來源：Yahoo 奇摩股市 RSS 頻道 (避免主 API 故障)
    try:
        url = f"https://tw.stock.yahoo.com/rss?s={symbol}.TW"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            tree = ET.fromstring(resp.read())
            for item in tree.findall('.//item'):
                raw_candidates.append({
                    "title": item.find('title').text,
                    "link": item.find('link').text,
                    "time": "最新"
                })
    except Exception:
        pass

    # 3. 執行去重與標籤賦予
    filtered_news = []
    for candidate in raw_candidates:
        title = candidate.get("title", "")
        if not title:
            continue
        if any(is_similar_title(title, exist["title"]) for exist in filtered_news):
            continue
        matched_tags = [kw for kw in INVESTMENT_KEYWORDS if kw in title]
        candidate["tag"] = matched_tags[0] if matched_tags else "市場動態"
        candidate["is_valuable"] = len(matched_tags) > 0
        filtered_news.append(candidate)

    filtered_news.sort(key=lambda x: x["is_valuable"], reverse=True)
    return filtered_news[:8]


# ==============================================================================
# 5. 【頂部三欄版面】+ 【ETF 專屬費率橫幅】(多一列動態顯示)
# ==============================================================================
top_col1, top_col2, top_col3 = st.columns([2.5, 5.5, 2.0])

# 左欄：標的名稱與代碼
with top_col1:
    with st.container(border=True):
        st.markdown(f"<div class='top-card-container'><h3 style='margin:0;'>{curr_name} ({curr_sym})</h3></div>", unsafe_allow_html=True)

# 中欄：量化規則動態生成專屬盤勢短評 (徹底告別固定死套話)
with top_col2:
    with st.container(border=True):
        # 1. 取得最新日 K 數據進行動態指標判定
        temp_df = fetch_kline_with_period(curr_sym, period_type="日")
        valid_c = temp_df['Close'].dropna() if not temp_df.empty else pd.Series()
        
        if len(valid_c) >= 20:
            c_now = float(valid_c.iloc[-1])
            ma5 = float(valid_c.tail(5).mean())
            ma20 = float(valid_c.tail(20).mean())
            
            # 判斷趨勢均線
            if c_now >= ma5 and ma5 >= ma20:
                trend_status = "短期均線多頭排列，多方掌控發球權"
            elif c_now < ma5 and ma5 < ma20:
                trend_status = "跌破月線空方排列，短線防禦為宜"
            elif c_now >= ma20:
                trend_status = "守穩月線關鍵生命線，處於蓄勢整理格局"
            else:
                trend_status = "面臨月線反壓，短線多空拉鋸震盪"

            # 判斷量能狀況
            vol_s = temp_df['Volume'].dropna()
            v_now = float(vol_s.iloc[-1]) if len(vol_s) > 0 else 0
            v_ma5 = float(vol_s.tail(5).mean()) if len(vol_s) >= 5 else 1
            v_ratio = v_now / (v_ma5 + 1e-9)
            
            if v_ratio >= 1.5:
                vol_status = "量能異常放大顯現籌碼換手"
            elif v_ratio <= 0.6:
                vol_status = "量縮量能退潮呈現無量觀望"
            else:
                vol_status = "量能維持常態水位"

            # 針對 ETF 與個股給予不同風控提示
            is_etf = str(curr_sym).strip() in ETF_FEES
            tip_status = "關注成分股權重與折溢價" if is_etf else "關注短線支撐與法人籌碼動向"

            ai_summary = f"【{curr_name}】{trend_status}，{vol_status}，{tip_status}。"
        else:
            ai_summary = f"【{curr_name}】目前歷史行情整理中，短線建議維持風控紀律。"

        st.markdown(
            f"<div class='top-card-container' style='display:flex; align-items:center;'>"
            f"<span style='font-size:13.5px;'><b>📊 盤勢量化體檢</b>：{ai_summary}</span>"
            f"</div>", 
            unsafe_allow_html=True
        )


# 右欄：股票/ETF 搜尋選擇器
with top_col3:
    with st.container(border=True):
        all_options = [f"{code} {name}" for code, name in ALL_STOCKS.items()]
        current_option = f"{curr_sym} {curr_name}"
        default_idx = all_options.index(current_option) if current_option in all_options else 0

        selected_option = st.selectbox(
            "搜尋全台股票",
            options=all_options,
            index=default_idx,
            label_visibility="collapsed",
            help="支援輸入全台上市、上櫃股票代碼或公司名稱即時聯想"
        )

        selected_code = selected_option.split()[0]
        if selected_code != curr_sym:
            st.session_state["current_symbol"] = selected_code
            st.rerun()

# ------------------------------------------------------------------------------
# 【ETF 專屬獨立列】：只要是 ETF，就在下方「額外多出一列」展示費率與配息！
# ------------------------------------------------------------------------------
clean_sym_check = str(curr_sym).strip()
if clean_sym_check in ETF_FEES:
    info = ETF_FEES[clean_sym_check]
    st.markdown(
        f"""
        <div style="background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 8px; padding: 10px 16px; margin-top: -6px; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; font-size: 13px;">
            <div style="display: flex; gap: 20px; align-items: center; flex-wrap: wrap;">
                <span>📂 類別：<b>{info['category']}</b></span>
                <span>💼 經理費：<b>{info['management_fee']}</b></span>
                <span>🏦 保管費：<b>{info['custody_fee']}</b></span>
                <span>💰 總費用率：<b style="color: #ef4444; font-size: 14px;">{info['total_fee']}</b></span>
                <span>📅 配息週期：<b>{info['dividend_month']}</b></span>
            </div>
            <div style="color: #94a3b8; font-size: 11px;">
                資料來源：本人搜集的 ETF 費率表，僅供參考，請以官方公告為準。
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# 獲取日 K 數據供主畫面繪圖與回測使用
df = fetch_kline_with_period(curr_sym, period_type="日")

# ==============================================================================
# 6. 【主體版面配置】(左側 6.3 : 右側 3.7 水平垂直對齊)
# ==============================================================================
left_panel, right_panel = st.columns([6.3, 3.7])


# ------------------------------------------------------------------------------
# 【左側面板】：K 線圖 + 複合指標回測系統
# ------------------------------------------------------------------------------
with left_panel:
    # 1. K 線圖與成交量控制面板
    with st.container(border=True):
        ctrl_col1, ctrl_col2 = st.columns([1.1, 1.9])
        with ctrl_col1:
            period_choice = st.radio(
                "K線週期", ["日K", "週K", "月K", "年K"],
                horizontal=True, index=0, label_visibility="visible",
                help="【K線週期】：選擇不同的時間週期，將會重新計算並繪製對應的 K 線圖。"
            )
        
        is_daily = (period_choice == "日K")

        with ctrl_col2:
            if is_daily:
                range_choice = st.radio(
                    "預覽範圍", ["7天", "15天", "30天", "1年", "全部"],
                    horizontal=True, index=1, label_visibility="visible",
                    help="【預覽範圍】：選取後圖表會直接將該區間內的 K 棒均勻鋪滿。"
                )
            else:
                range_choice = st.radio(
                    "預覽範圍", ["1年"],
                    horizontal=True, index=0, label_visibility="visible",
                    disabled=True,
                    help="長週期 K 線固定顯示近 1 年數據。"
                )

        clean_period = period_choice.replace("K", "")
        df_chart = fetch_kline_with_period(curr_sym, period_type=clean_period)

        if not df_chart.empty:
            if is_daily:
                if range_choice == "7天":
                    df_view = df_chart.tail(7).copy()
                elif range_choice == "15天":
                    df_view = df_chart.tail(15).copy()
                elif range_choice == "30天":
                    df_view = df_chart.tail(30).copy()
                elif range_choice == "1年":
                    df_view = df_chart.tail(250).copy()
                else:
                    df_view = df_chart.copy()
            else:
                df_view = df_chart.tail(52).copy() if clean_period == "週" else df_chart.tail(12).copy()

            df_view['DateStr'] = df_view['Date'].dt.strftime('%Y-%m-%d')

            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                vertical_spacing=0.03,
                row_heights=[0.72, 0.28]
            )

            fig.add_trace(go.Candlestick(
                x=df_view['DateStr'],
                open=df_view['Open'], high=df_view['High'],
                low=df_view['Low'], close=df_view['Close'],
                name=period_choice,
                increasing_line_color='#ef4444', increasing_fillcolor='#ef4444',
                decreasing_line_color='#22c55e', decreasing_fillcolor='#22c55e'
            ), row=1, col=1)

            vol_colors = ['#ef4444' if c >= o else '#22c55e' for c, o in zip(df_view['Close'], df_view['Open'])]
            fig.add_trace(go.Bar(
                x=df_view['DateStr'], y=df_view['Volume'],
                name='成交量', marker_color=vol_colors
            ), row=2, col=1)

            fig.update_layout(
                xaxis_rangeslider_visible=False,
                height=450,
                margin=dict(l=10, r=10, t=10, b=10),
                legend=dict(orientation="h", y=1.03, x=0),
                xaxis=dict(type='category')
            )
            fig.update_xaxes(type='category')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("查無股票數據，請確認搜尋欄股票代碼。")

    # 2. 三維複合指標量化回測引擎
    with st.container(border=True):
        col_title, col_info = st.columns([8, 2])
        with col_title:
            st.markdown(
                "**⚙️ 三維複合指標回測系統**", 
                help="【量化交易法則】：在『趨勢濾網』、『動能轉折』與『量能籌碼』三個互補維度中各挑選 1 個指標組合，兼顧勝率並過濾假突破！"
            )

        # ------------------- 第一步：三維度指標勾選 (預設全部關閉) -------------------
        dim1, dim2, dim3 = st.columns(3)

        with dim1:
            st.markdown("##### 🧭 趨勢濾網 (大方向)")
            use_ma = st.checkbox("啟用 均線多頭排列", value=False, help="短均 > 中均 > 長均，順勢交易濾網。")
            use_macd = st.checkbox("啟用 MACD 趨勢", value=False, help="DIF 與 DEA 黃金交叉判斷動能。")

        with dim2:
            st.markdown("##### ⚡ 動能轉折 (買賣點)")
            use_kd = st.checkbox("啟用 KD 超跌反彈", value=False, help="K 值低於超賣門檻代表短期超跌。")
            use_rsi = st.checkbox("啟用 RSI 強弱超賣", value=False, help="RSI 低於超賣門檻為逢低佈局良機。")
            use_bb = st.checkbox("啟用 布林下軌支撐", value=False, help="價格跌破下軌具備均值回歸拉力。")

        with dim3:
            st.markdown("##### 🌊 量能籌碼 (動能驗證)")
            use_vol_break = st.checkbox("啟用 成交量爆量突破", value=False, help="當日量大於均量倍數，確認真突破。")
            use_obv = st.checkbox("啟用 OBV 能量潮", value=False, help="OBV 大於其均線代表主力吸籌。")

        # ------------------- 第二步：動態展開參數 -------------------
        any_selected = any([use_ma, use_macd, use_kd, use_rsi, use_bb, use_vol_break, use_obv])
        
        if any_selected:
            param_cols = st.columns(3)
            with param_cols[0]:
                if use_ma:
                    p_ma_s = st.number_input("短天期均線 (天)", value=5, min_value=1)
                    p_ma_m = st.number_input("中天期均線 (天)", value=20, min_value=1)
                    p_ma_l = st.number_input("長天期均線 (天)", value=60, min_value=1)
                if use_macd:
                    macd_fast = st.number_input("MACD 快線天數", value=12, min_value=1)
                    macd_slow = st.number_input("MACD 慢線天數", value=26, min_value=1)

            with param_cols[1]:
                if use_kd:
                    kd_p = st.number_input("KD 週期天數", value=9, min_value=1)
                    kd_buy = st.number_input("K 超賣進場閾值", value=25, max_value=50)
                if use_rsi:
                    rsi_period = st.number_input("RSI 週期天數", value=14, min_value=1)
                    rsi_low = st.number_input("RSI 超賣進場閾值", value=35, max_value=50)
                if use_bb:
                    bb_period = st.number_input("布林中軌均線天數", value=20, min_value=1)
                    bb_std = st.number_input("標準差倍數", value=2.0, step=0.1)

            with param_cols[2]:
                if use_vol_break:
                    vol_ma_days = st.number_input("量能均線對比天數", value=5, min_value=1)
                    vol_mult = st.number_input("放量倍數門檻", value=1.5, step=0.1)
                if use_obv:
                    obv_ma_days = st.number_input("OBV 均線平滑天數", value=10, min_value=1)
        else:
            st.caption("👈 請於上方勾選欲測試的指標，對應參數設定將自動展開。")

        # ------------------- 第三步：回測日期與風控條件 -------------------
        st.markdown("---")
        r1_c1, r1_c2, r1_c3, r1_c4 = st.columns([1.2, 1.2, 1.2, 1.4])
        with r1_c1:
            stop_loss = st.number_input("停損門檻 (%)", value=5.0, min_value=0.0, step=0.5)
        with r1_c2:
            take_profit = st.number_input("停利門檻 (%)", value=15.0, min_value=0.0, step=0.5)
        with r1_c3:
            fee_rate = st.number_input("手續費+稅 (%)", value=0.15, step=0.05)
        with r1_c4:
            logic_mode = st.radio("條件邏輯", ["同時滿足 (AND)", "符合任一 (OR)"], horizontal=True)

        r2_c1, r2_c2, r2_c3, r2_c4 = st.columns([1.2, 1.2, 1.2, 1.4])
        with r2_c1:
            bt_start = st.date_input("回測起始日", value=datetime.now() - timedelta(days=180))
        with r2_c2:
            bt_end = st.date_input("回測結束日", value=datetime.now())
        with r2_c3:
            st.write("")
        with r2_c4:
            st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
            btn_run_bt = st.button("🚀 開始複合回測", use_container_width=True)

        # ------------------- 第四步：向量化訊號計算與狀態機 -------------------
        if btn_run_bt:
            if df.empty:
                st.error("❌ 查無歷史股價數據，無法執行回測。")
            elif not any_selected:
                st.warning("⚠️ 請至少勾選 1 個技術指標進行回測！")
            else:
                df_work = df.copy()
                df_work['Date_clean'] = pd.to_datetime(df_work['Date']).dt.tz_localize(None)
                start_dt = pd.to_datetime(bt_start).tz_localize(None)
                end_dt = pd.to_datetime(bt_end).tz_localize(None)

                df_bt = df_work[(df_work['Date_clean'] >= start_dt) & (df_work['Date_clean'] <= end_dt)].copy()

                if len(df_bt) < 15:
                    st.warning(f"⚠️ 所選區間交易日過少（僅 {len(df_bt)} 天），請拉長回測起始日！")
                else:
                    cond_list = []
                    if use_ma:
                        ma_s = df_bt['Close'].rolling(window=p_ma_s).mean()
                        ma_m = df_bt['Close'].rolling(window=p_ma_m).mean()
                        ma_l = df_bt['Close'].rolling(window=p_ma_l).mean()
                        cond_list.append((ma_s > ma_m) & (ma_m > ma_l))
                    if use_macd:
                        dif = df_bt['Close'].ewm(span=macd_fast, adjust=False).mean() - df_bt['Close'].ewm(span=macd_slow, adjust=False).mean()
                        dea = dif.ewm(span=9, adjust=False).mean()
                        cond_list.append(dif > dea)
                    if use_kd:
                        low_min = df_bt['Low'].rolling(window=kd_p).min()
                        high_max = df_bt['High'].rolling(window=kd_p).max()
                        rsv = 100 * ((df_bt['Close'] - low_min) / (high_max - low_min + 1e-9))
                        k = rsv.ewm(com=2, adjust=False).mean()
                        cond_list.append(k < kd_buy)
                    if use_rsi:
                        delta = df_bt['Close'].diff()
                        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
                        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
                        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
                        cond_list.append(rsi < rsi_low)
                    if use_bb:
                        ma = df_bt['Close'].rolling(window=bb_period).mean()
                        std = df_bt['Close'].rolling(window=bb_period).std()
                        cond_list.append(df_bt['Close'] < (ma - bb_std * std))
                    if use_vol_break:
                        v_ma = df_bt['Volume'].rolling(window=vol_ma_days).mean()
                        cond_list.append(df_bt['Volume'] > (v_ma * vol_mult))
                    if use_obv:
                        obv_sign = np.sign(df_bt['Close'].diff()).fillna(0)
                        obv = (obv_sign * df_bt['Volume']).cumsum()
                        obv_ma = obv.rolling(window=obv_ma_days).mean()
                        cond_list.append(obv > obv_ma)

                    if logic_mode == "同時滿足 (AND)":
                        comb_signal = cond_list[0].fillna(False)
                        for c in cond_list[1:]:
                            comb_signal = comb_signal & c.fillna(False)
                    else:
                        comb_signal = cond_list[0].fillna(False)
                        for c in cond_list[1:]:
                            comb_signal = comb_signal | c.fillna(False)

                    close_prices = df_bt['Close'].values
                    signals = comb_signal.values
                    n = len(df_bt)
                    positions = np.zeros(n, dtype=int)
                    
                    current_pos = 0
                    entry_price = 0.0

                    for i in range(n):
                        price = close_prices[i]
                        sig = signals[i]
                        if current_pos == 0:
                            if sig:
                                current_pos = 1
                                entry_price = price
                        else:
                            pnl_pct = ((price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
                            hit_sl = (stop_loss > 0) and (pnl_pct <= -stop_loss)
                            hit_tp = (take_profit > 0) and (pnl_pct >= take_profit)
                            signal_lost = not sig
                            if hit_sl or hit_tp or signal_lost:
                                current_pos = 0
                                entry_price = 0.0
                        positions[i] = current_pos

                    df_bt['Position'] = positions
                    df_bt['Market_Ret'] = df_bt['Close'].pct_change().fillna(0)
                    trades = df_bt['Position'].diff().fillna(0).abs()
                    df_bt['Strat_Ret'] = (df_bt['Position'].shift(1).fillna(0) * df_bt['Market_Ret']) - (trades * (fee_rate / 100))
                    
                    df_bt['Equity_Curve'] = (1 + df_bt['Strat_Ret']).cumprod()
                    df_bt['Benchmark_Curve'] = (1 + df_bt['Market_Ret']).cumprod()

                    strat_total = (df_bt['Equity_Curve'].iloc[-1] - 1) * 100
                    bench_total = (df_bt['Benchmark_Curve'].iloc[-1] - 1) * 100
                    cum_max = df_bt['Equity_Curve'].cummax()
                    mdd = ((df_bt['Equity_Curve'] - cum_max) / cum_max).min() * 100
                    trade_count = int(trades.sum())

                    st.markdown("---")
                    if trade_count == 0:
                        st.info("ℹ️ 在此回測日期區間內，此複合條件未被觸發（0 次進場）。")

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("策略累積報酬率", f"{strat_total:.2f}%", delta=f"{strat_total - bench_total:.2f}% vs 股票漲幅")
                    m2.metric("最大回撤 (MDD)", f"{mdd:.2f}%")
                    m3.metric("總進出次數", f"{trade_count} 次")
                    m4.metric("同期股票基準漲幅", f"{bench_total:.2f}%")

                    fig_eq = go.Figure()
                    fig_eq.add_trace(go.Scatter(x=df_bt['Date'], y=df_bt['Equity_Curve'], mode='lines', name='複合策略淨值', line=dict(color='#2563eb', width=2)))
                    fig_eq.add_trace(go.Scatter(x=df_bt['Date'], y=df_bt['Benchmark_Curve'], mode='lines', name='單純買進持有', line=dict(color='#94a3b8', dash='dot')))
                    fig_eq.update_layout(height=260, margin=dict(l=10, r=10, t=25, b=10), title_text="策略歷史資產淨值走勢 (Equity Curve)")
                    st.plotly_chart(fig_eq, use_container_width=True)


# ------------------------------------------------------------------------------
# 【右側面板】：即時量價行情概況 + AI 去重新聞流 + Gemini 真 AI 深度研報
# ------------------------------------------------------------------------------
with right_panel:
    # 1. 真實量價行情概況 (上下對稱留白 + 較前日量能增減 + 量能比 Help 說明)
    with st.container(border=True):
        st.markdown(f"**📊 即時盤態與量價體檢 · 【{curr_name}】**")
        
        valid_df = df.dropna(subset=['Close']).copy() if not df.empty else pd.DataFrame()
        
        if len(valid_df) >= 2:
            latest_row = valid_df.iloc[-1]
            prev_row = valid_df.iloc[-2]
            
            p_close = float(latest_row['Close'])
            p_prev = float(prev_row['Close'])
            p_open = float(latest_row['Open'])
            p_high = float(latest_row['High'])
            p_low = float(latest_row['Low'])
            
            # 今日成交量 vs 昨日成交量 (換算張數)
            v_today = int(latest_row['Volume'])
            v_prev = int(prev_row['Volume'])
            v_today_lots = v_today / 1000
            v_prev_lots = v_prev / 1000
            
            diff_v = v_today_lots - v_prev_lots
            diff_v_pct = (diff_v / (v_prev_lots + 1e-9)) * 100

            # 價的漲跌
            diff_p = p_close - p_prev
            diff_p_pct = (diff_p / p_prev) * 100
            
            # 5 日均量比
            v_ma5 = valid_df['Volume'].tail(5).mean()
            vol_ratio = v_today / (v_ma5 + 1e-9)

            diff_p_color = "#ef4444" if diff_p > 0 else ("#22c55e" if diff_p < 0 else "#94a3b8")
            diff_p_sign = "+" if diff_p > 0 else ""

            # 量的增減文字與樣式
            if diff_v > 0:
                vol_change_str = f"<span style='color:#ef4444; font-weight:600;'>▲ 增 {diff_v:,.0f} 張 (+{diff_v_pct:.1f}%)</span>"
            elif diff_v < 0:
                vol_change_str = f"<span style='color:#22c55e; font-weight:600;'>▼ 減 {abs(diff_v):,.0f} 張 ({diff_v_pct:.1f}%)</span>"
            else:
                vol_change_str = "<span style='color:#94a3b8;'>持平 (0.0%)</span>"

                        # 自訂量能比懸停氣泡提示框 CSS + 完整卡片 HTML
            tooltip_css = """
            <style>
                .custom-tooltip {
                    position: relative;
                    display: inline-block;
                    cursor: help;
                }
                .custom-tooltip .custom-tooltip-text {
                    visibility: hidden;
                    width: 230px;
                    background-color: #0b0f19;
                    color: #e2e8f0;
                    text-align: left;
                    border-radius: 8px;
                    padding: 9px 12px;
                    position: absolute;
                    z-index: 99999;
                    bottom: 140%;
                    right: -10px;
                    opacity: 0;
                    transition: opacity 0.15s ease-in-out;
                    border: 1px solid rgba(59, 130, 246, 0.4);
                    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.6);
                    font-size: 11px;
                    line-height: 1.5;
                    white-space: normal;
                    pointer-events: none;
                }
                .custom-tooltip .custom-tooltip-text::after {
                    content: "";
                    position: absolute;
                    top: 100%;
                    right: 18px;
                    border-width: 6px;
                    border-style: solid;
                    border-color: #0b0f19 transparent transparent transparent;
                }
                .custom-tooltip:hover .custom-tooltip-text {
                    visibility: visible;
                    opacity: 1;
                }
            </style>
            """

                        # 組合純 HTML 字串 (類別統一為 tooltip-box，游標維持箭頭且移入氣泡不消失)
            card_html = (
                f"<div style='padding: 6px 2px 14px 2px;'>"
                f"<div style='display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:12px;'>"
                f"<div>"
                f"<span style='font-size:28px; font-weight:bold; color:{diff_p_color}; font-family:monospace; line-height:1;'>{p_close:.2f}</span>"
                f"<span style='font-size:15px; font-weight:bold; color:{diff_p_color}; margin-left:8px;'>{diff_p_sign}{diff_p:.2f} ({diff_p_sign}{diff_p_pct:.2f}%)</span>"
                f"</div>"
                f"<div style='text-align:right; font-size:12px; line-height:1.4;'>"
                f"<div style='color:#94a3b8;'>成交量：<b style='color:#f8fafc;'>{v_today_lots:,.0f}</b> 張</div>"
                f"<div style='font-size:11px;'>較昨 {vol_change_str}</div>"
                f"</div>"
                f"</div>"
                f"<div style='display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;'>"
                f"<div style='background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 7px 4px; text-align: center;'>"
                f"<div style='font-size: 11px; color: #94a3b8; margin-bottom: 3px; height: 16px; line-height: 16px;'>開盤價</div>"
                f"<div style='font-size: 14px; font-weight: 600; font-family: monospace; line-height: 1.2;'>{p_open:.2f}</div>"
                f"</div>"
                f"<div style='background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 7px 4px; text-align: center;'>"
                f"<div style='font-size: 11px; color: #94a3b8; margin-bottom: 3px; height: 16px; line-height: 16px;'>最高價</div>"
                f"<div style='font-size: 14px; font-weight: 600; font-family: monospace; color: #ef4444; line-height: 1.2;'>{p_high:.2f}</div>"
                f"</div>"
                f"<div style='background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 7px 4px; text-align: center;'>"
                f"<div style='font-size: 11px; color: #94a3b8; margin-bottom: 3px; height: 16px; line-height: 16px;'>最低價</div>"
                f"<div style='font-size: 14px; font-weight: 600; font-family: monospace; color: #22c55e; line-height: 1.2;'>{p_low:.2f}</div>"
                f"</div>"
                f"<div style='background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 7px 4px; text-align: center; position: relative;' class='tooltip-box'>"
                f"<div style='font-size: 11px; color: #94a3b8; margin-bottom: 3px; display: flex; align-items: center; justify-content: center; gap: 3px; height: 16px; line-height: 16px;'>"
                f"<span>量能比</span><span style='font-size: 10px; color: #60a5fa; line-height: 1;'>ⓘ</span>"
                f"</div>"
                f"<div class='tooltip-text'>"
                f"<b style='color:#60a5fa;'>【量能比 (Volume Ratio)】</b><br>"
                f"公式：當日成交量 ÷ 近 5 日均量<br><br>"
                f"• <b style='color:#ef4444;'>＞ 1.5x</b>：爆量換手，動能強勁<br>"
                f"• <b style='color:#94a3b8;'>0.8x ~ 1.5x</b>：量能常態健康運行<br>"
                f"• <b style='color:#22c55e;'>＜ 0.6x</b>：量縮觀望，追價動能不足"
                f"</div>"
                f"<div style='font-size: 14px; font-weight: 600; font-family: monospace; line-height: 1.2;'>{vol_ratio:.1f}x</div>"
                f"</div>"
                f"</div>"
                f"</div>"
            )

            st.markdown(card_html, unsafe_allow_html=True)
        else:
            st.info("尚在整理歷史行情數據中...")


    # 2. AI 投資新聞流 + Gemini 深度研報
    with st.container(border=True):
        st.markdown(f"**📰 即時重要財經情報**")
        news_items = fetch_filtered_news(curr_sym)

        if news_items:
            cards_str = '<div class="news-scroll-container" style="max-height: 200px;">'
            for item in news_items:
                cards_str += (
                    f"<div class='news-card'>"
                    f"<div><span class='news-tag'>{item['tag']}</span><span style='color:#64748b;font-size:11px;'>{item['time']}</span></div>"
                    f"<div style='margin-top:4px;'><a href='{item['link']}' target='_blank' style='text-decoration:none;color:#1e293b;font-weight:500;'>{item['title']}</a></div>"
                    f"</div>"
                )
            cards_str += '</div>'
            st.markdown(cards_str, unsafe_allow_html=True)
        else:
            st.info("近期暫無重大新聞事件。")

        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

        # 真 AI 核心呼叫按鈕
        if "gemini_api_key" not in st.session_state:
            st.session_state["gemini_api_key"] = os.environ.get("GEMINI_API_KEY", "")

        current_key = st.session_state["gemini_api_key"]
        
        # 調整欄位寬度比例為 [4.8, 1.2]，提供足夠空間讓 ⚙️ Key 保持單行水平排列
        col_btn, col_key = st.columns([4.8, 1.2])
        with col_key:
            with st.popover("⚙️ Key", use_container_width=True):
                st.markdown("##### 🔑 配置 Gemini API Key")
                key_input = st.text_input("API Key", value=current_key, type="password", placeholder="AIzaSy...")
                if key_input != current_key:
                    st.session_state["gemini_api_key"] = key_input
                    st.rerun()

        with col_btn:
            btn_run_ai = st.button("🧠 啟動 Gemini 多空解讀", use_container_width=True)

        if btn_run_ai:
            active_key = st.session_state.get("gemini_api_key", "").strip()
            if not active_key:
                st.warning("👈 請點擊右側 **「⚙️ Key」** 填入您的 Gemini API Key！")
            elif not HAS_GENAI:
                st.error("❌ 尚未安裝 google-genai 套件，請執行：`pip install google-genai`")
            elif df.empty or len(df.dropna(subset=['Close'])) < 15:
                st.warning("⚠️ 歷史數據不足，無法進行深入多空分析。")
            else:
                with st.spinner("🤖 Gemini-3.8-flash 正在即時剖析量價結構與新聞面..."):
                    try:
                        valid_c = df['Close'].dropna()
                        last_close = float(valid_c.iloc[-1])
                        ma5 = float(valid_c.tail(5).mean())
                        ma20 = float(valid_c.tail(20).mean())
                        vol_today = float(df['Volume'].dropna().iloc[-1])
                        vol_ma5 = float(df['Volume'].dropna().tail(5).mean())
                        vol_ratio = vol_today / (vol_ma5 + 1e-9)

                        delta = valid_c.diff()
                        gain = delta.where(delta > 0, 0).tail(14).mean()
                        loss = (-delta.where(delta < 0, 0)).tail(14).mean()
                        rsi_val = 100 - (100 / (1 + (gain / (loss + 1e-9))))

                        news_text_list = [f"- {item['title']} ({item['tag']})" for item in news_items[:5]]
                        news_blob = "\n".join(news_text_list) if news_text_list else "近期暫無重大新聞事件。"

                        prompt = f"""
你是一位身經百戰的台股資深量化操盤手與分析師。請綜合以下【實時量價數據】與【即時新聞事件】，針對標的【{curr_name} ({curr_sym})】給出一份精確、去蕪存菁的投資多空診斷。

【當前市場微觀數據】：
- 最新收盤價：{last_close:.2f} 元
- 5日短期均線：{ma5:.2f} 元
- 20日月線生命線：{ma20:.2f} 元 (目前處於{'月線之上' if last_close >= ma20 else '月線之下'})
- 成交量能放大倍數：{vol_ratio:.2f} 倍
- 14日 RSI 相對強弱：{rsi_val:.1f}

【最新新聞情報】：
{news_blob}

請嚴格遵循以下格式輸出（使用繁體中文，語氣客觀嚴謹，總字數 220 字以內）：
### 🧭 多空方向定調
- **市場定調**：【偏多 / 偏空 / 中性整理】
- **多空信心指數**：【X%】（請依據均線、量能與新聞面合理估算，切忌固定給78%）

### 🔍 核心關鍵洞察
1. **量價與均線面**：[簡評 20MA 攻防、5MA 排列與量能是否有異常換手]
2. **基本與新聞面**：[綜合新聞內容點評實質影響，若為空泛新聞請明確指出無需過度反應]

### 🛡️ 實盤紀律與風控指引
- **多方防守 / 支撐點**：[具體點位或均線參考]
- **空方反壓 / 警戒點**：[具體點位或乖離警示]
- **操盤建議**：[用一句話說明追價風險或停損策略]
"""

                        client = genai.Client(api_key=active_key)
                        response = client.models.generate_content(
                            model='gemini-3.8-flash',
                            contents=prompt,
                        )

                        st.markdown(
                            f"""
                            <div style="background: rgba(59, 130, 246, 0.05); border: 1px solid #3b82f6; border-radius: 8px; padding: 12px; margin-top: 10px;">
                                <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 6px; margin-bottom: 8px;">
                                    <span style="font-weight: bold; font-size: 13px;">✨ Gemini AI 實時研報</span>
                                    <span style="font-size: 10px; background: rgba(59, 130, 246, 0.2); color: #60a5fa; padding: 1px 6px; border-radius: 4px; font-family: monospace;">gemini-3.8-flash</span>
                                </div>
                                <div style="font-size: 13px; line-height: 1.6;">
                                    {response.text}
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )

                    except Exception as e:
                        st.error(f"❌ Gemini 調用異常：{e}")
