import time
import ccxt
import pandas as pd
import requests
import logging

logging.basicConfig(filename='monitor.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

TELEGRAM_TOKEN = "8593268164:AAGUYOqIvTBUkOWrBhOyTjK5dluppIqFziQ"
TELEGRAM_CHAT_ID = "2043458735"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1464886198886469740/o5eSzKpez2IraxE7kWOsEm-xINvVM9kLzItbuLtAe0XkdWk4WM9KD4sgo_j6WAiJ8kfp"

alerted = set()  # (symbol) 集合

def send_alert(symbol, price, chg, vol):
    message = f"[警报] 交易量延迟增长 >10 距 = 0\n币种: {symbol}\n最新价: {price}\n24h涨跌: {chg}\n24h量(USDT): {vol}"
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     params={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
        logging.info(f"Telegram sent: {symbol}")
    except Exception as e:
        logging.error(f"Telegram failed: {e}")

    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message})
        logging.info(f"Discord sent: {symbol}")
    except Exception as e:
        logging.error(f"Discord failed: {e}")

def check_signals():
    global alerted
    alerted.clear()  # 每5分钟清空，确保周期内只发一次

    ex = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    markets = ex.load_markets()
    perps = [s for s in markets if markets[s].get('swap') and markets[s]['quote'] == 'USDT']
    tickers = ex.fetch_tickers(perps)
    symbols = [s for s, v in sorted(((s, tickers.get(s, {}).get('quoteVolume', 0)) for s in perps), key=lambda x:x[1], reverse=True)][:200]  # 前200

    for sym in symbols:
        try:
            ohlcv = ex.fetch_ohlcv(sym, '1h', limit=3000)
            df = pd.DataFrame(ohlcv, columns=['ts','o','h','l','c','v'])
            late10 = None
            if len(df) >= 6:
                for j in range(len(df)-1, 5-1, -1):
                    v = df['v'].iloc[j-5:j+1]
                    if v.iloc[:3].sum() > 0:
                        r = v.iloc[-3:].sum() / v.iloc[:3].sum() - 1
                        if late10 is None and r > 10:
                            late10 = len(df)-1-j
                        if late10 is not None: break

            if late10 == 0 and sym not in alerted:
                t = tickers.get(sym, {})
                price = t.get('last', 'N/A')
                chg = f"{t.get('percentage', 'N/A'):+.2f}%"
                vol = f"{t.get('quoteVolume', 0):,.0f}"
                send_alert(sym.replace('/USDT:USDT', ''), price, chg, vol)
                alerted.add(sym)

        except Exception as e:
            logging.error(f"{sym} 出错: {e}")

if __name__ == "__main__":
    logging.info("监控启动 - Railway免费层")
    while True:
        try:
            check_signals()
        except Exception as e:
            logging.error(f"主循环异常: {e}")
        time.sleep(300)  # 每5分钟检查一次
