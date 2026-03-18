import os
import pandas as pd
import argparse
from pandas.tseries.offsets import BDay
from moomoo import *
SYMBOL = "HK.00700"

def main(today_date, live_mode):
    if SYMBOL.startswith("HK."):
        trade_market = TrdMarket.HK
        market = 'market_hk'
    elif SYMBOL.startswith("US."):
        trade_market = TrdMarket.US
        market = 'market_us'

    quote_ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    ret, stock_data = quote_ctx.get_stock_basicinfo(
        market=trade_market,
        stock_type=SecurityType.STOCK,
        code_list=SYMBOL
    )
    quote_ctx.close()
    lot_size = stock_data['lot_size'].iloc[0]

    if live_mode:
        keyword = 'live_trading_logs'
        output_filename = 'live'
        price = 'execution_price'
    else:
        keyword = 'simulated_trading_logs'
        output_filename = 'simulated'
        price = 'close'
    for log_file in os.listdir('logs'):
        if today_date.strftime('%Y-%m-%d') in log_file and keyword in log_file:
            print(f"Processing log file: {log_file}")
            output_df = pd.read_csv(f'logs/{log_file}')
            output_df['next_max_position_sell'] = output_df['max_position_sell'].shift(-1)
            output_df['trade_qty'] = abs(output_df['next_max_position_sell'] - output_df['max_position_sell'])

            buy_df = output_df.loc[output_df['action'] == 'BUY']
            buy_df['capital'] = buy_df[price] * buy_df['trade_qty'] * lot_size
            initial_capital = buy_df['capital'].sum()

            sell_df = output_df.loc[output_df['action'] == 'SELL']
            sell_df['realized_pl'] = (sell_df[price] - sell_df['cost_price']) * sell_df['trade_qty'] * lot_size
            total_pct = sell_df['realized_pl'].sum()/initial_capital * 100
            print(f"Total Return: {sell_df['realized_pl'].sum():.0f}, {total_pct:.3f}%")
            break

    # Save into output, everyday log here
    output_path = os.path.join(os.getcwd(), 'logs', f"{today_date.strftime('%Y-%m-%d')} 23:59:00 - pl_{output_filename}.csv")
    sell_df.to_csv(output_path)

if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description='Run the trading bot in live or test mode.')
    argparser.add_argument('--live', default=False, action='store_true', help='Run the bot in live mode (default is test mode)')
    argparser.add_argument('--date', default=pd.Timestamp.today(), help='Current date, or previous date for backtesting')
    args = argparser.parse_args()
    live_mode = args.live
    today_date = pd.to_datetime(args.date)
    main(today_date, live_mode)