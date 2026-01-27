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

alerted = set()

def send_alert(symbol, price, chg, vol):
    message = f"[警报] 交易量延迟增长 >10 (1000%) - 最近6根K线\n币种: {symbol}\n最新价: {price}\n24h涨跌: {chg}\n24h量(USDT): {vol}"
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     params={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
        logging.info(f"Telegram sent: {symbol}")
        print(f"Telegram sent: {symbol}")
    except Exception as e:
        logging.error(f"Telegram failed: {e}")
        print(f"Telegram failed: {e}")

    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message})
        logging.info(f"Discord sent: {symbol}")
        print(f"Discord sent: {symbol}")
    except Exception as e:
        logging.error(f"Discord failed: {e}")
        print(f"Discord failed: {e}")

def check_signals():
    global alerted
    alerted.clear()  # 每15分钟周期清空，确保周期内只发一次

    logging.info("开始新一轮检查 (1h 周期)")
    print("开始新一轮检查 (1h 周期)")

    try:
        ex = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
        markets = ex.load_markets()
        logging.info("load_markets 成功")
        print("load_markets 成功")

        perps = [s for s in markets if markets[s].get('swap') and markets[s]['quote'] == 'USDT']
        tickers = ex.fetch_tickers(perps)
        symbols = [s for s, v in sorted(((s, tickers.get(s, {}).get('quoteVolume', 0)) for s in perps), key=lambda x:x[1], reverse=True)]  # 全部币种，按交易量降序

        logging.info(f"加载 {len(symbols)} 个合约")
        print(f"加载 {len(symbols)} 个合约")

        for sym in symbols:
            try:
                # 只获取最近10根1h K线（足够计算最近6根）
                ohlcv = ex.fetch_ohlcv(sym, '1h', limit=10)
                df = pd.DataFrame(ohlcv, columns=['ts','o','h','l','c','v'])

                if len(df) >= 6:
                    # 最近3根总交易量 (index -1, -2, -3)
                    recent_3 = df['v'].iloc[-3:].sum()
                    # 前3根总交易量 (index -4, -5, -6)
                    prev_3 = df['v'].iloc[-6:-3].sum()

                    if prev_3 > 0 and (recent_3 / prev_3 - 1) > 10:
                        if sym not in alerted:
                            t = tickers.get(sym, {})
                            price = t.get('last', 'N/A')
                            chg = f"{t.get('percentage', 'N/A'):+.2f}%"
                            vol = f"{t.get('quoteVolume', 0):,.0f}"
                            send_alert(sym.replace('/USDT:USDT', ''), price, chg, vol)
                            alerted.add(sym)
                            logging.info(f"找到信号并发送: {sym} (增长率 > 1000%)")
                            print(f"找到信号并发送: {sym} (增长率 > 1000%)")

            except ccxt.RateLimitExceeded as e:
                logging.warning(f"Rate limit exceeded for {sym}, waiting 10s")
                time.sleep(10)
                continue
            except Exception as e:
                logging.error(f"{sym} 出错: {e}")
                print(f"{sym} 出错: {e}")

            time.sleep(0.5)  # 每合约延时0.5秒，避免429

    except Exception as e:
        logging.error(f"加载市场/合约失败: {e}")
        print(f"加载市场/合约失败: {e}")

if __name__ == "__main__":
    logging.info("监控启动 - Railway免费层 - 1小时周期，每15分钟检查一次")
    print("监控启动 - Railway免费层 - 1小时周期，每15分钟检查一次")
    while True:
        try:
            check_signals()
        except Exception as e:
            logging.error(f"主循环异常: {e}")
            print(f"主循环异常: {e}")
        time.sleep(900)  # 每15分钟检查一次
