import time
import ccxt
import pandas as pd
import requests
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread, Event
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "Crypto Monitor is running! (1h cycle, check at :00, :05, :10...)"

def run_flask():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

logging.basicConfig(filename='monitor.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

TELEGRAM_TOKEN = "8536228993:AAEXwG-kl9kFpSEBZqazv7oE0gUDhYeLulA"
TELEGRAM_CHAT_ID = "2043458735"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1464886198886469740/o5eSzKpez2IraxE7kWOsEm-xINvVM9kLzItbuLtAe0XkdWk4WM9KD4sgo_j6WAiJ8kfp"

alerted = set()
last_alert_hour = -1  # 上次发送警报的小时（东八区）

BEIJING_TZ = timezone(timedelta(hours=8))

stop_event = Event()  # 用于中断正在运行的检查

def send_alert(symbol, price, chg, vol, period='1h'):
    timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
    period_display = f"({period}周期)"

    telegram_msg = f"""
交易量延迟增长率 大于 10 (1000%) 警报 {period_display}
币种:  *{symbol}*
24小时涨跌幅:  {chg}
24小时交易量(USDT):  {vol}
最新价:  {price}
时间: {timestamp}

————————————————————————————————
"""#.strip()

    discord_msg = f"""
**交易量延迟增长率 >10 (1000%) 警报 {period_display}**
**币种：** **{symbol}**  
24小时涨跌幅： **{chg}**  
24小时交易量(USDT)： **{vol}**
最新价： {price}  
时间： {timestamp}  

————————————————————————————————
"""

    try:
        response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                params={"chat_id": TELEGRAM_CHAT_ID, "text": telegram_msg},
                                timeout=15)
        logging.info(f"Telegram 状态码: {response.status_code}")
        if response.status_code == 200:
            logging.info(f"Telegram 发送成功: {symbol} at {timestamp}")
    except Exception as e:
        logging.error(f"Telegram 请求异常: {e}")

    try:
        response = requests.post(DISCORD_WEBHOOK, json={"content": discord_msg}, timeout=15)
        logging.info(f"Discord 状态码: {response.status_code}")
        if response.status_code == 204:
            logging.info(f"Discord 发送成功: {symbol} at {timestamp}")
    except Exception as e:
        logging.error(f"Discord 请求异常: {e}")

    logging.info(f"[警报已尝试发送] {symbol} - 交易量延迟增长大于10 距 = 0 ({period})")

def check_signals():
    global alerted, last_alert_hour

    stop_event.clear()  # 重置中断标志

    current_time = datetime.now(BEIJING_TZ)
    current_hour = current_time.hour

    # 如果进入新小时周期，重置警报
    if current_hour != last_alert_hour:
        alerted.clear()
        last_alert_hour = current_hour
        logging.info(f"新小时周期开始: {current_hour:02d}:00，重置警报状态")

    start_time = time.time()
    logging.info(f"开始新一轮检查 (1h 周期) - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"开始新一轮检查 (1h 周期) - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        ex = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
        markets = ex.load_markets()
        perps = [s for s in markets if markets[s].get('swap') and markets[s].get('active') and markets[s]['quote'] == 'USDT']
        tickers = ex.fetch_tickers(perps)
        symbols = [s for s, v in sorted(((s, tickers.get(s, {}).get('quoteVolume', 0)) for s in perps), key=lambda x:x[1], reverse=True)]

        total = len(symbols)
        logging.info(f"加载 {total} 个正常永续合约")

        processed = 0
        for sym in symbols:
            if stop_event.is_set():
                logging.info(f"检查被中断（进入下一个时间点） - 已处理 {processed}/{total}")
                return

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

            if processed % 10 == 0 or processed == total:
                elapsed = time.time() - start_time
                percent = (processed / total) * 100
                logging.info(f"处理进度: {processed}/{total} ({percent:.1f}%) - 已耗时 {elapsed:.1f} 秒")
                print(f"处理进度: {processed}/{total} ({percent:.1f}%) - 已耗时 {elapsed:.1f} 秒")

    except Exception as e:
        logging.error(f"加载市场/合约失败: {e}")

def scheduler():
    while True:
        now = datetime.now(BEIJING_TZ)
        minute = now.minute

        # 只在 00,05,10,...,55 分运行
        if minute % 5 == 0:
            # 启动新检查前，先设置中断标志，让上一个检查（如果还在跑）退出
            stop_event.set()
            time.sleep(1)  # 给上一个线程一点时间退出

            # 清空中断标志，开始新检查
            stop_event.clear()
            check_thread = Thread(target=check_signals)
            check_thread.daemon = True
            check_thread.start()

        # 每分钟检查一次是否到达整点
        time.sleep(60 - now.second)

if __name__ == "__main__":
    logging.info("监控启动 - Railway免费层 - 1小时周期，每5分钟准点检查一次")

    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # 启动定时调度器
    scheduler_thread = Thread(target=scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    # 主线程保持运行
    while True:
        time.sleep(60)


