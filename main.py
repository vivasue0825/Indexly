from fastapi import FastAPI, HTTPException, BackgroundTasks, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yfinance as yf
from datetime import datetime
import uvicorn
import pytz
import sqlite3
import asyncio
from typing import List, Optional

app = FastAPI()

# Antigravity 환경의 프론트엔드 통신을 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "indexly.db"

# --- 데이터 모델 ---
class UserConfigRequest(BaseModel):
    nickname: str

class AlertRequest(BaseModel):
    ticker: str
    base_type: str  # 'now' or 'avg'
    up_pct: Optional[float] = None
    down_pct: Optional[float] = None
    period: str # 'day' or 'week'

# --- DB 초기화 로직 ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 1. 시세 캐시 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS market_cache (
            ticker TEXT PRIMARY KEY,
            name TEXT,
            last_price REAL,
            diff REAL,
            percent REAL,
            is_open INTEGER,
            updated_at DATETIME
        )
    ''')
    # 2. 가격 알림 설정 (Price Watch)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            base_type TEXT,
            target_price REAL,
            condition TEXT, -- 'UP' or 'DOWN'
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 3. 사용자 설정
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    # 4. 차트 이력 캐싱
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chart_cache (
            ticker TEXT,
            period TEXT,
            data TEXT,
            updated_at DATETIME,
            PRIMARY KEY (ticker, period)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- 유틸리티 함수 ---
def check_market_open(ticker: str):
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    if "BTC" in ticker or "/USD" in ticker: return 1
    if now.weekday() >= 5: return 0
    return 1 if 9 <= now.hour < 16 else 0

def fetch_latest_yf(ticker: str):
    t_map = {
        "USD/KRW": "USDKRW=X", "JPY/KRW": "JPYKRW=X", 
        "NASDAQ100": "^NDX", "S&P500": "^GSPC", "DOW": "^DJI",
        "KOSPI": "^KS11", "KOSDAQ": "^KQ11",
        "GOLD": "GC=F", "SILVER": "SI=F", "COPPER": "HG=F", 
        "WTI": "CL=F", "NATGAS": "NG=F", "BTC/USD": "BTC-USD"
    }
    target = t_map.get(ticker, ticker)
    stock = yf.Ticker(target)
    hist = stock.history(period="1d", interval="15m")
    
    if hist.empty or len(hist) < 2:
        # Fallback to 5d daily if 1d is empty (e.g. weekends for commodities)
        hist = stock.history(period="5d", interval="1d")
        if hist.empty or len(hist) < 2: return None
        curr = round(hist['Close'].iloc[-1], 2)
        prev = round(hist['Close'].iloc[-2], 2)
    else:
        curr = round(hist['Close'].iloc[-1], 2)
        prev = hist['Close'].iloc[0]
        
    diff = round(curr - prev, 2)
    pct = round((diff / prev) * 100, 2)
    return {"ticker": ticker, "price": curr, "diff": diff, "percent": pct, "is_open": check_market_open(ticker)}

# --- 백그라운드 엔진 (Watcher) ---
async def price_watcher_loop():
    """
    30초마다 DB에 등록된 모든 종목의 시세를 동기화하고 알림 조건을 체크합니다.
    """
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT ticker FROM market_cache")
            tickers = [row[0] for row in cursor.fetchall()]
            
            for t in tickers:
                data = await asyncio.to_thread(fetch_latest_yf, t)
                if data:
                    cursor.execute('''
                        UPDATE market_cache SET last_price=?, diff=?, percent=?, is_open=?, updated_at=?
                        WHERE ticker=?
                    ''', (data['price'], data['diff'], data['percent'], data['is_open'], datetime.now(), t))
                    
                    # [여기서 알림 체크 로직 추가 가능]
                    # target_price 도달 시 Push 발송 로직 등
            
            conn.commit()
            conn.close()
            await asyncio.sleep(30)
        except Exception as e:
            print(f"Watcher Error: {e}")
            await asyncio.sleep(10)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(price_watcher_loop())

# --- API 엔드포인트 ---

@app.get("/api/summary")
def get_summary():
    """DB 기반의 빠른 요약 정보 제공"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM market_cache")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows: # 초기 데이터가 없을 경우 가이드 데이터 대신 빈 배열 반환
        return []
    
    return [dict(row) for row in rows]

@app.get("/api/userconfig")
def get_userconfig():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM user_config WHERE key='nickname'")
    row = cursor.fetchone()
    conn.close()
    return {"nickname": row[0] if row else "Indexly"}

@app.post("/api/userconfig")
def update_userconfig(payload: UserConfigRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO user_config (key, value) VALUES ('nickname', ?)", (payload.nickname,))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/api/search")
def search_tickers(q: str = ""):
    q = q.lower().strip()
    t_map = [
        # 지수/환율/원자재
        {"name": "달러/원 환율", "ticker": "USD/KRW"},
        {"name": "엔/원 환율", "ticker": "JPY/KRW"},
        {"name": "코스피", "ticker": "KOSPI"},
        {"name": "코스닥", "ticker": "KOSDAQ"},
        {"name": "나스닥 100", "ticker": "NASDAQ100"},
        {"name": "S&P 500", "ticker": "S&P500"},
        {"name": "다우 존스", "ticker": "DOW"},
        {"name": "국제 금", "ticker": "GOLD"},
        {"name": "국제 은", "ticker": "SILVER"},
        {"name": "국제 구리", "ticker": "COPPER"},
        {"name": "원유 (WTI)", "ticker": "WTI"},
        {"name": "천연가스", "ticker": "NATGAS"},
        # 미국 테크/반도체
        {"name": "애플", "ticker": "AAPL"},
        {"name": "마이크로소프트", "ticker": "MSFT"},
        {"name": "엔비디아", "ticker": "NVDA"},
        {"name": "구글", "ticker": "GOOGL"},
        {"name": "아마존", "ticker": "AMZN"},
        {"name": "메타", "ticker": "META"},
        {"name": "테슬라", "ticker": "TSLA"},
        {"name": "브로드컴", "ticker": "AVGO"},
        {"name": "AMD", "ticker": "AMD"},
        {"name": "퀄컴", "ticker": "QCOM"},
        {"name": "인텔", "ticker": "INTC"},
        {"name": "ASML", "ticker": "ASML"},
        {"name": "TSMC", "ticker": "TSM"},
        {"name": "어플라이드 머티어리얼즈", "ticker": "AMAT"},
        {"name": "램리서치", "ticker": "LRCX"},
        {"name": "마이크론", "ticker": "MU"},
        {"name": "ARM", "ticker": "ARM"},
        {"name": "록히드마틴", "ticker": "LMT"},
        {"name": "넷플릭스", "ticker": "NFLX"},
        # 국내 반도체/2차전지/IT
        {"name": "삼성전자", "ticker": "005930.KS"},
        {"name": "SK하이닉스", "ticker": "000660.KS"},
        {"name": "LG에너지솔루션", "ticker": "373220.KS"},
        {"name": "POSCO홀딩스", "ticker": "005490.KS"},
        {"name": "에코프로BM", "ticker": "247540.KQ"},
        {"name": "에코프로", "ticker": "086520.KQ"},
        {"name": "포스코퓨처엠", "ticker": "003670.KS"},
        {"name": "삼성SDI", "ticker": "006400.KS"},
        {"name": "현대차", "ticker": "053800.KS"},
        {"name": "기아", "ticker": "000270.KS"},
        {"name": "네이버", "ticker": "035420.KS"},
        {"name": "카카오", "ticker": "035720.KS"},
        {"name": "한미반도체", "ticker": "042700.KS"},
        # 주요 ETF
        {"name": "SOXX (미국 반도체)", "ticker": "SOXX"},
        {"name": "QQQ (나스닥100)", "ticker": "QQQ"},
        {"name": "SPY (S&P500)", "ticker": "SPY"},
        {"name": "TIGER 2차전지테마", "ticker": "305540.KS"},
        {"name": "KODEX 반도체", "ticker": "091160.KS"},
    ]
    
    if not q:
        defaults = ["KOSPI", "KOSDAQ", "NASDAQ100", "S&P500", "USD/KRW", "GOLD", "WTI", "MSFT", "NVDA", "GOOGL"]
        return [item for item in t_map if item['ticker'] in defaults]
        
    res = [item for item in t_map if q in item['name'].lower() or q in item['ticker'].lower()]
    
    if not res:
        # Avoid blocking search for short incomplete queries
        if len(q) < 2:
            return []
            
        try:
            target = q.upper()
            stock = yf.Ticker(target)
            hist = stock.history(period="1d", interval="1d")
            if not hist.empty:
                # Try to get shortName but fallback to ticker to save time if missing
                info_name = target
                try:
                    full_info = stock.info
                    if full_info and 'shortName' in full_info:
                        info_name = full_info['shortName']
                except:
                    pass
                res = [{"name": info_name, "ticker": target}]
        except:
            pass
            
    return res


@app.get("/api/chart/{ticker:path}")
def get_market_data(ticker: str, period: str = "1d"):
    """상세 차트용 실시간 데이터 Fetch 및 DB 업데이트"""
    try:
        t_map = {
            "USD/KRW": "USDKRW=X", "JPY/KRW": "JPYKRW=X", 
            "NASDAQ100": "^NDX", "S&P500": "^GSPC", "DOW": "^DJI",
            "KOSPI": "^KS11", "KOSDAQ": "^KQ11",
            "GOLD": "GC=F", "SILVER": "SI=F", "COPPER": "HG=F", 
            "WTI": "CL=F", "NATGAS": "NG=F"
        }
        target = t_map.get(ticker, ticker)
        
        is_open = check_market_open(ticker)
        import json, math
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # DB 캐시 확인 (장이 닫혔거나, 당일(1d) 조회가 아닐 경우 캐시 우선 반환)
        if not (period == "1d" and is_open):
            cursor.execute("SELECT data FROM chart_cache WHERE ticker=? AND period=?", (ticker, period))
            row = cursor.fetchone()
            if row:
                conn.close()
                return json.loads(row[0])

        stock = yf.Ticker(target)
        yf_period, yf_interval = "1d", "15m"
        if period == "1w":
            yf_period, yf_interval = "5d", "1d"
        elif period == "1m":
            yf_period, yf_interval = "1mo", "1d"
        elif period == "1y":
            yf_period, yf_interval = "1y", "1wk"
            
        hist = stock.history(period=yf_period, interval=yf_interval)
        
        if hist.empty:
            if yf_period == "1d":
                hist = stock.history(period="5d", interval="1d")
                if hist.empty: raise HTTPException(status_code=404)
            else:
                raise HTTPException(status_code=404)

        current_price = round(hist['Close'].iloc[-1], 2)
        if len(hist) > 1:
            diff = round(current_price - hist['Close'].iloc[period == "1d" and yf_interval == "15m" and 0 or -2], 2)
        else:
            diff = 0
            
        percent = round((diff / (current_price - diff)) * 100, 2) if (current_price - diff) != 0 else 0
        
        # 캔들 데이터 생성 및 라벨
        candles = [{"x": idx.timestamp()*1000, "o": r['Open'], "h": r['High'], "l": r['Low'], "c": r['Close']} for idx, r in hist.iterrows()]
        
        current_year = datetime.now().year
        def fmt_label(d):
            if period == "1d": return d.strftime('%H:%M')
            if d.year == current_year: return d.strftime('%m/%d')
            return d.strftime('%y/%m/%d')
            
        time_labels = [fmt_label(d) for d in hist.index]
        
        # 1주일 평균가 계산 (5일치 데이터 활용 결측치 NaN 방어)
        week_hist = stock.history(period="5d", interval="1d")
        avg_val = week_hist['Close'].mean() if not week_hist.empty else current_price
        avg_p = current_price if math.isnan(avg_val) else round(float(avg_val), 2)

        # 요약 캐시 업데이트
        cursor.execute('''
            INSERT OR REPLACE INTO market_cache (ticker, name, last_price, diff, percent, is_open, updated_at)
            VALUES (?, COALESCE((SELECT name FROM market_cache WHERE ticker=?), ?), ?, ?, ?, ?, ?)
        ''', (ticker, ticker, ticker, current_price, diff, percent, is_open, datetime.now()))
        
        # 차트 캐시 신규 맵핑
        res_data = {
            "ticker": ticker, "currentPrice": current_price, "avgPrice": avg_p,
            "diff": diff, "percent": percent, "is_open": is_open,
            "state": "up" if diff >= 0 else "down",
            "labels": time_labels,
            "prices": hist['Close'].round(2).tolist(),
            "candles": candles
        }
        
        cursor.execute('''
            INSERT OR REPLACE INTO chart_cache (ticker, period, data, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (ticker, period, json.dumps(res_data), datetime.now()))
        
        conn.commit()
        conn.close()

        return res_data
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/alerts")
def create_alert(payload: AlertRequest):
    """프론트엔드로부터 알림 설정값을 받아 DB에 저장"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 기준가 가져오기
        cursor.execute("SELECT last_price FROM market_cache WHERE ticker=?", (payload.ticker,))
        row = cursor.fetchone()
        base_price = row[0] if row else 0
        
        # 상승 알림 저장
        if payload.up_pct:
            target = base_price * (1 + payload.up_pct/100)
            cursor.execute("INSERT INTO price_alerts (ticker, base_type, target_price, condition) VALUES (?, ?, ?, 'UP')", 
                           (payload.ticker, payload.base_type, target))
            
        # 하락 알림 저장
        if payload.down_pct:
            target = base_price * (1 - payload.down_pct/100)
            cursor.execute("INSERT INTO price_alerts (ticker, base_type, target_price, condition) VALUES (?, ?, ?, 'DOWN')", 
                           (payload.ticker, payload.base_type, target))
            
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)