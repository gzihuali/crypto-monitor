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

    # Telegram 纯文本版本（无 parse_mode，避免转义问题）
    telegram_msg = f"""
交易量延迟增长 大于 10 (1000%) 警报 {period_display}

时间: {timestamp}
币种: **{symbol}**   # 加粗突出币种
最新价: {price}
24h涨跌: {chg}
24h量(USDT): {vol}

---
""".strip()

    # Discord Markdown 版本（保持原样，已正常工作）
    discord_msg = f"""
**交易量延迟增长 >10 (1000%) 警报 {period_display}**

**时间：** {timestamp}  
**币种：** **{symbol}**  
**最新价：** {price}  
**24h涨跌：** {chg}  
**24h量(USDT)：** {vol}

---
"""

    print(f"准备发送 Telegram: {symbol} at {timestamp}")
    logging.info(f"准备发送 Telegram: {symbol} at {timestamp}")

    try:
        response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                params={
                                    "chat_id": TELEGRAM_CHAT_ID,
                                    "text": telegram_msg
                                    # 故意不加 parse_mode，避免任何转义问题
                                },
                                timeout=15)
        print(f"Telegram 状态码: {response.status_code}")
        print(f"Telegram 返回: {response.text}")
        logging.info(f"Telegram 状态码: {response.status_code} | 返回: {response.text[:300]}...")
        if response.status_code == 200:
            print(f"Telegram 发送成功: {symbol}")
            logging.info(f"Telegram 发送成功: {symbol} at {timestamp}")
        else:
            print(f"Telegram 非200响应: {response.text}")
            logging.warning(f"Telegram 非200: {response.text}")
    except Exception as e:
        print(f"Telegram 请求异常: {e}")
        logging.error(f"Telegram 请求异常: {e}")

    print(f"准备发送 Discord: {symbol} at {timestamp}")
    logging.info(f"准备发送 Discord: {symbol} at {timestamp}")

    try:
        response = requests.post(DISCORD_WEBHOOK, json={"content": discord_msg}, timeout=15)
        print(f"Discord 状态码: {response.status_code}")
        logging.info(f"Discord 状态码: {response.status_code}")
        if response.status_code == 204:
            print(f"Discord 发送成功: {symbol}")
            logging.info(f"Discord 发送成功: {symbol} at {timestamp}")
    except Exception as e:
        print(f"Discord 请求异常: {e}")
        logging.error(f"Discord 请求异常: {e}")

    print(f"[警报已尝试发送] {symbol} - 交易量延迟增长>10 距 = 0 ({period})")
    logging.info(f"[警报已尝试发送] {symbol} ({period})")

def check_signals():
    global alerted
    alerted.clear()

    start_time = time.time()
    logging.info("开始新一轮检查 (1h 周期)")
    print("开始新一轮检查 (1h 周期)")

    try:
        logging.info("开始 load_markets...")
        print("开始 load_markets...")
        ex = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
        markets = ex.load_markets()
        logging.info("load_markets 成功")

        logging.info("开始 fetch_tickers...")
        print("开始 fetch_tickers...")
        perps = [s for s in markets if markets[s].get('swap') and markets[s].get('active') and markets[s]['quote'] == 'USDT']
        tickers = ex.fetch_tickers(perps)
        symbols = [s for s, v in sorted(((s, tickers.get(s, {}).get('quoteVolume', 0)) for s in perps), key=lambda x:x[1], reverse=True)]  # 全部正常永续合约

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
                            logging.info(f"找到信号并发送: {sym} (增长率 > 1000%)")

            except ccxt.RateLimitExceeded as e:
                logging.warning(f"Rate limit exceeded for {sym}, waiting 10s")
                time.sleep(10)
                continue
            except Exception as e:
                logging.error(f"{sym} 出错: {e}")

            time.sleep(0.2)  # 延时0.2秒，避免429

            if processed % 10 == 0 or processed == total:
                elapsed = time.time() - start_time
                percent = (processed / total) * 100
                logging.info(f"处理进度: {processed}/{total} ({percent:.1f}%) - 已耗时 {elapsed:.1f} 秒")
                print(f"处理进度: {processed}/{total} ({percent:.1f}%) - 已耗时 {elapsed:.1f} 秒")

    except Exception as e:
        logging.error(f"加载市场/合约失败: {e}")
        print(f"加载市场/合约失败: {e}")

if __name__ == "__main__":
    logging.info("监控启动 - Railway免费层 - 1小时周期，每5分钟检查一次")

    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    while True:
        try:
            check_signals()
        except Exception as e:
            logging.error(f"主循环异常: {e}")
        time.sleep(300)  # 每5分钟检查一次
