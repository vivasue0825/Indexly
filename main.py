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
    t_map = {"USD/KRW": "USDKRW=X", "JPY/KRW": "JPYKRW=X", "NASDAQ100": "^NDX", "GOLD": "GC=F", "BTC/USD": "BTC-USD"}
    target = t_map.get(ticker, ticker)
    stock = yf.Ticker(target)
    hist = stock.history(period="1d", interval="15m")
    if hist.empty: return None
    
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
                data = fetch_latest_yf(t)
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
async def get_summary():
    """DB 기반의 빠른 요약 정보 제공"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM market_cache")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows: # 초기 데이터가 없을 경우 가이드 데이터 반환
        return [{"name": "달러/원 환율", "ticker": "USD/KRW", "last_price": 1340.5, "diff": 0, "percent": 0, "state": "even"}]
    
    return [dict(row) for row in rows]

@app.get("/api/chart/{ticker}")
async def get_market_data(ticker: str, period: str = "1d"):
    """상세 차트용 실시간 데이터 Fetch 및 DB 업데이트"""
    try:
        t_map = {"USD/KRW": "USDKRW=X", "JPY/KRW": "JPYKRW=X", "NASDAQ100": "^NDX", "GOLD": "GC=F", "BTC/USD": "BTC-USD"}
        target = t_map.get(ticker, ticker)
        stock = yf.Ticker(target)
        interval = "15m" if period == "1d" else "1d"
        hist = stock.history(period=period, interval=interval)
        
        if hist.empty: raise HTTPException(status_code=404)

        current_price = round(hist['Close'].iloc[-1], 2)
        diff = round(current_price - hist['Close'].iloc[0], 2)
        percent = round((diff / hist['Close'].iloc[0]) * 100, 2)
        
        # 캔들 데이터 생성
        candles = [{"x": idx.timestamp()*1000, "o": r['Open'], "h": r['High'], "l": r['Low'], "c": r['Close']} for idx, r in hist.iterrows()]
        
        # 1주일 평균가 계산
        week_hist = stock.history(period="1wk", interval="1d")
        avg_p = round(week_hist['Close'].mean(), 2) if not week_hist.empty else current_price

        # 캐시 업데이트 (Upsert)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO market_cache (ticker, last_price, diff, percent, is_open, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (ticker, current_price, diff, percent, check_market_open(ticker), datetime.now()))
        conn.commit()
        conn.close()

        return {
            "ticker": ticker, "currentPrice": current_price, "avgPrice": avg_p,
            "diff": diff, "percent": percent, "is_open": check_market_open(ticker),
            "state": "up" if diff >= 0 else "down",
            "labels": [d.strftime('%H:%M') for d in hist.index],
            "prices": hist['Close'].round(2).tolist(),
            "candles": candles
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/alerts")
async def create_alert(payload: AlertRequest):
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