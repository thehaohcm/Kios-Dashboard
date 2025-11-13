from flask import Flask, render_template, jsonify
import requests, json, os, time, threading, xml.etree.ElementTree as ET, yfinance as yf

app = Flask(__name__)

from datetime import datetime

@app.template_filter('datetimeformat')
def datetimeformat(value):
    return datetime.fromtimestamp(value).strftime("%H:%M")

@app.template_filter('datetimeformat_day')
def datetimeformat_day(value):
    return datetime.fromtimestamp(value).strftime("%a")


CACHE_FILE = "cache.json"
CACHE_TTL = 3 * 60 * 60   # 3 tiếng
OPENWEATHER_KEY = "554d82bd5b108ef8c58c522f3372dddf"

# ---------------- Cache utilities ----------------
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

def get_cached_data(key, fetch_func):
    cache = load_cache()
    now = time.time()
    if key in cache and (now - cache[key]["time"] < CACHE_TTL):
        return cache[key]["data"]
    data = fetch_func()
    cache[key] = {"data": data, "time": now}
    save_cache(cache)
    return data

def clear_expired_cache():
    while True:
        try:
            cache = load_cache()
            now = time.time()
            expired_keys = [k for k, v in cache.items() if now - v.get("time", 0) > CACHE_TTL]
            if expired_keys:
                for k in expired_keys:
                    del cache[k]
                save_cache(cache)
                print(f"🧹 Cache cleared: {expired_keys}")
        except Exception as e:
            print("Cache cleanup error:", e)
        time.sleep(CACHE_TTL)

threading.Thread(target=clear_expired_cache, daemon=True).start()

# ---------------- WEATHER ----------------
from datetime import datetime
import requests

@app.route('/weather')
def weather():
    def fetch_weather():
        city = "Ho Chi Minh City"
        api_key = OPENWEATHER_KEY

        # 1️⃣ Current Weather
        url_current = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={city}&appid={api_key}&units=metric&lang=vi"
        )
        current = requests.get(url_current, timeout=10).json()

        # Lấy city name an toàn
        city_name = current.get("name", "Thành phố Hồ Chí Minh")

        lat = current["coord"]["lat"]
        lon = current["coord"]["lon"]

        # 2️⃣ Forecast 5 ngày (3 giờ/lần) – API forecast
        url_forecast = (
            f"https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={lat}&lon={lon}&appid={api_key}&units=metric&lang=vi"
        )
        forecast_raw = requests.get(url_forecast, timeout=10).json()

        # 🧠 Chuyển forecast 3h thành forecast theo ngày
        from collections import defaultdict
        daily = defaultdict(list)

        for item in forecast_raw["list"]:
            day = item["dt_txt"].split(" ")[0]
            daily[day].append(item)

        # Chỉ lấy 6 ngày tới
        forecast = []
        for day, items in list(daily.items())[:6]:
            temps = [i["main"]["temp"] for i in items]
            max_t = max(temps)
            min_t = min(temps)
            icon = items[len(items)//2]["weather"][0]["icon"]
            desc = items[len(items)//2]["weather"][0]["description"]
            forecast.append({
                "date": day,
                "icon": icon,
                "description": desc,
                "temp_max": max_t,
                "temp_min": min_t
            })

        # 3️⃣ Air quality
        url_air = (
            f"http://api.openweathermap.org/data/2.5/air_pollution"
            f"?lat={lat}&lon={lon}&appid={api_key}"
        )
        air = requests.get(url_air, timeout=10).json()

        return {
            "city": city_name,
            "current": current,
            "forecast": forecast,
            "air": air
        }

    data = get_cached_data("weather_full", fetch_weather)
    return render_template("weather.html", data=data)

# ---------------- NEWS (VnExpress) ----------------
def parse_rss_items(content, limit=10):
    root = ET.fromstring(content)
    items = []
    for item in root.findall("./channel/item")[:limit]:
        title = item.findtext("title")
        link = item.findtext("link")
        pubDate = item.findtext("pubDate")
        items.append({"title": title, "link": link, "pubDate": pubDate})
    return items

@app.route('/news_json')
def news_json():
    def fetch_news():
        rss_url = "https://vnexpress.net/rss/tin-moi-nhat.rss"
        r = requests.get(rss_url, timeout=10)
        return parse_rss_items(r.content, limit=20)
    data = get_cached_data("news", fetch_news)
    return jsonify(data)

@app.route('/news')
def news():
    # page sẽ fetch /news_json client-side (để có spinner)
    return render_template('news.html')

@app.route('/market')
def market():
    import yfinance as yf, requests

    def fetch_market():
        tickers = {
            # Forex
            "DXY": "DX-Y.NYB",
            "EURUSD": "EURUSD=X",
            "USDJPY": "JPY=X",
            "USDCHF": "CHF=X",
            "GBPUSD": "GBPUSD=X",
            "AUDUSD": "AUDUSD=X",
            "USDVND": "USDVND=X",

            # Stock index
            "VNINDEX": "^VNINDEX.VN",
            "DJIA": "^DJI",
            "NASDAQ": "^IXIC",
            "S&P500": "^GSPC",
            "KOSPI": "^KS11",
            "NIKKEI": "^N225",
            "SHANGHAI": "000001.SS",

            # Commodity
            "Gold": "GC=F",
            "Silver": "SI=F",
            "Brent": "BZ=F",
            "Crude": "CL=F",

            # Crypto
            "BTCUSDT": "BTC-USD",
            "ETHUSDT": "ETH-USD",
            "XRPUSDT": "XRP-USD",
            "BNBUSDT": "BNB-USD"
        }

        try:
            data = yf.download(list(tickers.values()), period="2d", interval="1h", progress=False, group_by='ticker')
        except Exception as e:
            print(f"⚠️ Lỗi tải dữ liệu yfinance: {e}")
            data = {}

        forex, stock, commodity, crypto = {}, {}, {}, {}

        for name, symbol in tickers.items():
            try:
                closes = data[symbol]["Close"].dropna()
                if len(closes) < 2:
                    continue
                current = closes.iloc[-1]
                prev = closes.iloc[-2]
                change = "▲" if current > prev else "▼"
                change_pct = round(((current - prev) / prev) * 100, 2)
                info = {"price": round(float(current), 2), "change": change, "percent": change_pct}
                if name in ["DXY","EURUSD","USDJPY","USDCHF","GBPUSD","AUDUSD","USDVND"]:
                    forex[name] = info
                elif name in ["VNINDEX","DJIA","NASDAQ","S&P500","KOSPI","NIKKEI","SHANGHAI"]:
                    stock[name] = info
                elif name in ["Gold","Silver","Brent","Crude"]:
                    commodity[name] = info
                else:
                    crypto[name] = info
            except Exception as e:
                print(f"⚠️ Lỗi lấy {name}: {e}")

        # VNINDEX fallback
        if "VNINDEX" not in stock:
            try:
                vn = yf.Ticker("^VNINDEX.VN").history(period="2d")
                if not vn.empty:
                    current = vn["Close"].iloc[-1]
                    prev = vn["Close"].iloc[-2]
                    change = "▲" if current > prev else "▼"
                    change_pct = round(((current - prev) / prev) * 100, 2)
                    stock["VNINDEX"] = {"price": round(float(current), 2), "change": change, "percent": change_pct}
            except Exception as e:
                print("⚠️ Không thể lấy VNINDEX:", e)

        # Cổ phiếu tiềm năng
        def fetch_stock():
            api_url = "https://trading-signals-pi.vercel.app/getPotentialSymbols"
            try:
                resp = requests.get(api_url, timeout=10).json()
                return resp
            except Exception as e:
                print("⚠️ Lỗi API cổ phiếu:", e)
                return {"data": [], "latest_updated": ""}

        stock_api = get_cached_data("stock_potential", fetch_stock)
        symbols = stock_api.get("data", [])
        print(symbols)
        updated = stock_api.get("latest_updated", "")

        return {
            "forex": forex,
            "stock": stock,
            "crypto": crypto,
            "commodity": commodity,
            "symbols": symbols,
            "updated": updated
        }

    data = get_cached_data("market_data", fetch_market)
    return render_template("market.html", data=data)

# ---------------- FINANCE (Dow Jones RSS) ----------------
@app.route('/finance_json')
def finance_json():
    def fetch_finance():
        rss_url = "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"
        r = requests.get(rss_url, timeout=10)
        return parse_rss_items(r.content, limit=20)
    data = get_cached_data("finance", fetch_finance)
    return jsonify(data)

@app.route('/finance')
def finance():
    # page sẽ fetch /finance_json client-side
    return render_template('finance.html')

# ---------------- ROOT ----------------
@app.route('/')
def index():
    return render_template('layout.html')

if __name__ == '__main__':
    print("🚀 Flask kiosk dashboard running — cache auto-refresh every 3h")
    app.run(host='0.0.0.0', port=5000)
