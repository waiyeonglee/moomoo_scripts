import os
import pandas as pd
from pandas.tseries.offsets import BDay

today_date = pd.Timestamp.today()# - BDay(1)
for log_file in os.listdir('logs'):
    if today_date.strftime('%Y-%m-%d') in log_file:
        print(f"Processing log file: {log_file}")
        output_df = pd.read_csv(f'logs/{log_file}')
        output_df['prev_max_position_sell'] = output_df['max_position_sell'].shift(1)
        output_df['sell_qty'] = output_df['prev_max_position_sell'] - output_df['max_position_sell']

        initial_capital = output_df.iloc[0]['cost_price'] * output_df.iloc[0]['max_position_sell']

        sell_df = output_df.loc[output_df['action'] == 'SELL']
        sell_df['realized_pl'] = (sell_df['close'] - sell_df['cost_price']) * sell_df['sell_qty']
        total_pct = sell_df['realized_pl'].sum()/initial_capital * 100
        print(f"Total Return: {total_pct:.3f}%")
        break

# Save into output, everyday log here
output_path = os.path.join(os.getcwd(), 'logs', f"{pd.Timestamp.today().strftime('%Y-%m-%d %H:%M:%S')} - pl.csv")
sell_df.to_csv(output_path)