import time
import ccxt
import pandas as pd
import requests
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "Crypto Monitor is running! (1h cycle, check every 5 min)"

def run_flask():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

logging.basicConfig(filename='monitor.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

TELEGRAM_TOKEN = "8536228993:AAEXwG-kl9kFpSEBZqazv7oE0gUDhYeLulA"
TELEGRAM_CHAT_ID = "2043458735"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1464886198886469740/o5eSzKpez2IraxE7kWOsEm-xINvVM9kLzItbuLtAe0XkdWk4WM9KD4sgo_j6WAiJ8kfp"

alerted = set()

# 东八区时区（北京时间）
BEIJING_TZ = timezone(timedelta(hours=8))

def send_alert(symbol, price, chg, vol, period='1h'):
    timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
    period_display = f"({period}周期)"

    telegram_msg = f"""
<b>🚨 交易量延迟增长 >10 (1000%) 警报 {period_display}</b>

<b>时间：</b> {timestamp}  
<b>币种：</b> <span style="color:#FF4444; font-weight:bold;">{symbol}</span>  
<b>最新价：</b> {price}  
<b>24h涨跌：</b> {chg}  
<b>24h量(USDT)：</b> {vol}

---
""".strip()

    discord_msg = f"""
**🚨 交易量延迟增长 >10 (1000%) 警报 {period_display}**

**时间：** {timestamp}  
**币种：** **{symbol}**  
**最新价：** {price}  
**24h涨跌：** {chg}  
**24h量(USDT)：** {vol}

---
"""

    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     params={"chat_id": TELEGRAM_CHAT_ID, "text": telegram_msg, "parse_mode": "HTML"})
        logging.info(f"Telegram sent: {symbol} ({period}) at {timestamp}")
    except Exception as e:
        logging.error(f"Telegram failed: {e}")

    try:
        requests.post(DISCORD_WEBHOOK, json={"content": discord_msg})
        logging.info(f"Discord sent: {symbol} ({period}) at {timestamp}")
    except Exception as e:
        logging.error(f"Discord failed: {e}")

def check_signals():
    global alerted
    alerted.clear()

    start_time = time.time()
    logging.info("开始新一轮检查 (1h 周期)")
    print("开始新一轮检查 (1h 周期)")

    try:
        ex = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
        markets = ex.load_markets()
        logging.info("load_markets 成功")

        perps = [s for s in markets if markets[s].get('swap') and markets[s].get('active') and markets[s]['quote'] == 'USDT']
        tickers = ex.fetch_tickers(perps)
        symbols = [s for s, v in sorted(((s, tickers.get(s, {}).get('quoteVolume', 0)) for s in perps), key=lambda x:x[1], reverse=True)]

        total = len(symbols)
        logging.info(f"加载 {total} 个正常永续合约")
        print(f"加载 {total} 个正常永续合约")

        processed = 0
        for sym in symbols:
            processed += 1
            try:
                ohlcv = ex.fetch_ohlcv(sym, '1h', limit=10)
                df = pd.DataFrame(ohlcv, columns=['ts','o','h','l','c','v'])

                if len(df) >= 6:
                    recent_3 = df['v'].iloc[-3:].sum()
                    prev_3 = df['v'].iloc[-6:-3].sum()

                    if prev_3 > 0 and (recent_3 / prev_3 - 1) > 10:
                        if sym not in alerted:
                            t = tickers.get(sym, {})
                            price = t.get('last', 'N/A')
                            chg = f"{t.get('percentage', 'N/A'):+.2f}%"
                            vol = f"{t.get('quoteVolume', 0):,.0f}"
                            send_alert(sym.replace('/USDT:USDT', ''), price, chg, vol, period='1h')
                            alerted.add(sym)
                            logging.info(f"找到信号并发送: {sym}")

            except ccxt.RateLimitExceeded as e:
                logging.warning(f"Rate limit exceeded for {sym}, waiting 10s")
                time.sleep(10)
                continue
            except Exception as e:
                logging.error(f"{sym} 出错: {e}")

            # 进度显示（每10个记录一次，最后一批强制显示100% + 总耗时）
            if processed % 10 == 0 or processed == total:
                elapsed = time.time() - start_time
                percent = (processed / total) * 100
                logging.info(f"处理进度: {processed}/{total} ({percent:.1f}%) - 已耗时 {elapsed:.1f} 秒")
                print(f"处理进度: {processed}/{total} ({percent:.1f}%) - 已耗时 {elapsed:.1f} 秒")

    except Exception as e:
        logging.error(f"加载市场/合约失败: {e}")

if __name__ == "__main__":
    logging.info("监控启动 - Railway免费层 - 1小时周期，每5分钟检查一次")

    # 启动 Flask 保活服务器（后台线程）
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    while True:
        try:
            check_signals()
        except Exception as e:
            logging.error(f"主循环异常: {e}")
        time.sleep(300)  # 每5分钟检查一次
