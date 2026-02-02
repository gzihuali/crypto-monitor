import os
import time
from datetime import datetime
import ccxt
import pandas as pd
import mplfinance as mpf
from tqdm import tqdm

# 代理
proxies = {
    'http': 'http://127.0.0.1:7980',
    'https': 'http://127.0.0.1:7980',
}

exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
    'proxies': proxies,
    'enableRateLimit': True,
    'timeout': 60000,  # 增加超时到60秒
})

def get_all_usdt_perps():
    try:
        markets = exchange.load_markets()
        usdt_perps = [s for s in markets if markets[s].get('swap', False) and markets[s].get('active', False) and markets[s].get('quote') == 'USDT']
        if not usdt_perps:
            print("没有找到永续合约")
            return []

        tickers = exchange.fetch_tickers(usdt_perps)
        sorted_symbols = sorted(
            usdt_perps,
            key=lambda s: tickers.get(s, {}).get('quoteVolume', 0) or 0,
            reverse=True
        )
        print(f"获取到 {len(sorted_symbols)} 个 USDT 永续合约，按24h交易量排序")
        return sorted_symbols  # 返回所有，按交易量降序
    except Exception as e:
        print(f"获取交易对失败: {e}")
        return []

def fetch_ohlcv_with_retry(symbol, timeframe, since, limit, retries=5):
    for attempt in range(retries):
        try:
            return exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        except Exception as e:
            print(f"第 {attempt+1}/{retries} 次重试 {symbol}: {e}")
            time.sleep(5)  # 增加等待时间
    print(f"{symbol} 获取失败，跳过")
    return None

def plot_and_save(df, symbol_name, days, file_path):
    try:
        my_style = mpf.make_marketcolors(
            up='white', down='black',
            edge={'up':'black', 'down':'black'},
            wick='black',
            volume='gray',
        )
        my_style = mpf.make_mpf_style(
            marketcolors=my_style,
            gridstyle='',
            facecolor='#fcf7e1',
            figcolor='#fcf7e1',
            y_on_right=False,
        )

        mpf.plot(
            df,
            type='candle',
            style=my_style,
            volume=True,
            ylabel='Price',
            ylabel_lower='Volume',
            title=f"{symbol_name} 1h Chart (Last {days} Days)",
            datetime_format='%m-%d %H:%M',
            xrotation=45,
            tight_layout=True,
            figsize=(16, 9),
            panel_ratios=(3,1),
            savefig=dict(fname=file_path, dpi=300, bbox_inches='tight'),
            xlim=(df.index[0], df.index[-1] + pd.Timedelta(days=1)),
        )
        print(f"成功保存: {file_path}")
    except Exception as e:
        print(f"绘图失败 {symbol_name}: {e}")

def main():
    now = datetime.now()
    current_time_str = now.strftime("%Y%m%d_%H")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    folder_path = os.path.join(script_dir, current_time_str)
    os.makedirs(folder_path, exist_ok=True)
    print(f"创建文件夹: {folder_path}")

    all_symbols = get_all_usdt_perps()  # 改为获取所有
    if not all_symbols:
        print("无法获取交易对，程序退出。")
        return

    days = 5
    num_candles = (days + 1) * 24
    since = exchange.milliseconds() - num_candles * 3600 * 1000

    print(f"开始生成 {len(all_symbols)} 个永续合约的 K线图（按24h交易量排序）...")
    for symbol in tqdm(all_symbols, desc="生成 K线图"):
        ohlcv = fetch_ohlcv_with_retry(symbol, '1h', since, num_candles)
        if not ohlcv or len(ohlcv) < 50:
            continue

        df = pd.DataFrame(ohlcv, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Date'] = pd.to_datetime(df['Date'], unit='ms')
        df = df.set_index('Date')

        symbol_name = symbol.split('/')[0]
        file_name = f"{symbol_name}_1h_10d_{current_time_str}.png"
        file_path = os.path.join(folder_path, file_name)

        plot_and_save(df, symbol_name, days, file_path)

    print("所有图片生成完成！")

if __name__ == "__main__":
    main()