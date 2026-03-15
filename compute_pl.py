import os
import pandas as pd
import argparse
from pandas.tseries.offsets import BDay

def main(today_date):
    for log_file in os.listdir('logs'):
        if today_date.strftime('%Y-%m-%d') in log_file and 'simulated_trading' in log_file:
            print(f"Processing log file: {log_file}")
            output_df = pd.read_csv(f'logs/{log_file}')
            output_df['prev_max_position_sell'] = output_df['max_position_sell'].shift(1)
            output_df['trade_qty'] = abs(output_df['prev_max_position_sell'] - output_df['max_position_sell'])

            buy_df = output_df.loc[output_df['action'] == 'BUY']
            buy_df['capital'] = buy_df['close'] * buy_df['trade_qty']
            initial_capital = buy_df['capital'].sum()

            sell_df = output_df.loc[output_df['action'] == 'SELL']
            sell_df['realized_pl'] = (sell_df['close'] - sell_df['cost_price']) * sell_df['trade_qty']
            total_pct = sell_df['realized_pl'].sum()/initial_capital * 100
            print(f"Total Return: {total_pct:.3f}%")
            break

    # Save into output, everyday log here
    output_path = os.path.join(os.getcwd(), 'logs', f"{today_date.strftime('%Y-%m-%d')} 23:59:00 - pl.csv")
    sell_df.to_csv(output_path)

if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description='Run the trading bot in live or test mode.')
    argparser.add_argument('--date', default=pd.Timestamp.today(), help='Current date, or previous date for backtesting')
    args = argparser.parse_args()
    today_date = pd.to_datetime(args.date)
    main(today_date)