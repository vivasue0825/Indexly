from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from datetime import datetime
import uvicorn
import pytz

app = FastAPI()

# Antigravity 환경을 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def check_market_open(ticker: str):
    """
    종목별 시장 운영 여부를 판단합니다. (KST 및 글로벌 기준)
    """
    kst = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(kst)
    
    # 1. 암호화폐 (BTC, ETH 등) -> 24시간/365일 가동
    if "BTC" in ticker or "ETH" in ticker or "/USD" in ticker:
        return True
    
    # 2. 한국 시장 (환율 및 국장: 주중 09:00 ~ 15:30)
    if "KRW" in ticker or "KOSPI" in ticker:
        if now_kst.weekday() >= 5: return False # 주말 종료
        # 오전 9시부터 오후 3시 30분까지
        start_time = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
        end_time = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
        return start_time <= now_kst <= end_time
    
    # 3. 미국 시장 등 기타 (간소화: 우선 평일이면 열린 것으로 처리)
    return now_kst.weekday() < 5

@app.get("/api/summary")
async def get_summary():
    """
    홈 화면을 위한 실시간 시세 요약 (Mock/Real 데이터 결합)
    """
    try:
        # 실제 환경에서는 DB나 실시간 API에서 루프를 돌며 가져옵니다.
        # 여기서는 요건 확인을 위한 샘플 데이터를 반환합니다.
        return [
            {"name": "달러/원 환율", "ticker": "USD/KRW", "price": 1342.50, "diff": 5.2, "percent": 0.38, "state": "up"},
            {"name": "나스닥 100", "ticker": "NASDAQ100", "price": 18234.15, "diff": -12.4, "percent": -0.07, "state": "down"},
            {"name": "비트코인", "ticker": "BTC/USD", "price": 63450.00, "diff": 120.0, "percent": 0.19, "state": "up"}
        ]
    except Exception:
        return []

@app.get("/api/chart/{ticker}")
async def get_market_data(ticker: str, period: str = "1d"):
    try:
        t_map = {
            "USD/KRW": "USDKRW=X", 
            "JPY/KRW": "JPYKRW=X", 
            "GOLD": "GC=F", 
            "NASDAQ100": "^NDX",
            "BTC/USD": "BTC-USD"
        }
        target = t_map.get(ticker, ticker)
        stock = yf.Ticker(target)
        
        interval = "15m" if period == "1d" else "1d"
        hist = stock.history(period=period, interval=interval)

        if hist.empty: raise HTTPException(status_code=404)

        prices = hist['Close'].round(2).tolist()
        labels = [d.strftime('%H:%M' if period == "1d" else '%m/%d') for d in hist.index]
        
        # 캔들 데이터 생성 (t, o, h, l, c)
        candles = []
        for index, row in hist.iterrows():
            candles.append({
                "x": index.to_pydatetime().timestamp() * 1000,
                "o": row['Open'], "h": row['High'], "l": row['Low'], "c": row['Close']
            })

        # 1주일 평균가 (Price Watch용)
        week_hist = stock.history(period="1wk", interval="1d")
        avg_price = round(week_hist['Close'].mean(), 2) if not week_hist.empty else prices[-1]

        return {
            "ticker": ticker,
            "currentPrice": prices[-1],
            "avgPrice": avg_price,
            "is_open": check_market_open(ticker),
            "diff": round(prices[-1] - prices[0], 2),
            "percent": round(((prices[-1] - prices[0]) / prices[0]) * 100, 2),
            "state": "up" if prices[-1] >= prices[0] else "down",
            "labels": labels,
            "prices": prices,
            "candles": candles
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)