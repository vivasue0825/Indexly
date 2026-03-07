from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import uvicorn
from datetime import datetime

app = FastAPI()

# 프론트엔드 연결 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/chart/{ticker}")
async def get_market_data(ticker: str, period: str = "1d"):
    """
    Yahoo Finance API를 통해 실시간 OHLC 데이터를 가져옵니다.
    """
    try:
        # 티커 변환 (예: USD/KRW -> USDKRW=X)
        ticker_map = {
            "USD/KRW": "USDKRW=X",
            "JPY/KRW": "JPYKRW=X",
            "GOLD": "GC=F",
            "SILVER": "SI=F",
            "NASDAQ100": "^NDX"
        }
        target = ticker_map.get(ticker, ticker)
        stock = yf.Ticker(target)
        
        # 1일 데이터는 15분 단위, 그 외는 1일 단위
        interval = "15m" if period == "1d" else "1d"
        hist = stock.history(period=period, interval=interval)

        if hist.empty:
            raise HTTPException(status_code=404, detail="Data not found")

        # 캔들스틱용 데이터 (t: 시간, o: 시가, h: 고가, l: 저가, c: 종가)
        candle_data = []
        for index, row in hist.iterrows():
            candle_data.append({
                "x": index.isoformat(),
                "o": round(row['Open'], 2),
                "h": round(row['High'], 2),
                "l": round(row['Low'], 2),
                "c": round(row['Close'], 2)
            })

        # 단순 라인차트용 데이터 (기존 호환성)
        prices = hist['Close'].round(2).tolist()
        labels = [d.strftime('%H:%M' if period == "1d" else '%m/%d') for d in hist.index]

        # 1주일 평균가 (Price Watch용)
        week_hist = stock.history(period="1wk", interval="1d")
        avg_price = round(week_hist['Close'].mean(), 2) if not week_hist.empty else prices[-1]

        curr = prices[-1]
        prev = prices[0]
        diff = round(curr - prev, 2)
        pct = round((diff / prev) * 100, 2)

        return {
            "ticker": ticker,
            "currentPrice": curr,
            "avgPrice": avg_price,
            "diff": diff,
            "percent": pct,
            "state": "up" if diff >= 0 else "down",
            "labels": labels,
            "prices": prices,
            "candles": candle_data # 캔들 전용 데이터셋 추가
        }
    except Exception as e:
        print(f"Error: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)