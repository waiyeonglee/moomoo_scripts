import time
import os
import argparse
import pandas as pd
import numpy as np
from moomoo import *

trade_env = TrdEnv.SIMULATE
SHORT_WINDOW = 3
LONG_WINDOW = 15
SYMBOL = "HK.00700"
PROFIT_PCT = 0
buy_cond = 'FIXED_PROFIT_PCT'
QTY = 100

# --- Strategy class ---
class Strategy:
    def __init__(self):
        self.in_position = False
        self.entry_price = None
        self.output_params = {}
        self.prices = {}

    def update_state_from_row(self, row):
        # row is the latest Kline row (pandas Series or DataFrame slice)
        # Update internal state and compute signals
        print("Processing new candle:", row['time_key'].iloc[0])

        # Example: store the row
        self.last_row = row

        # Update output params / prices
        # (replace with your actual logic)
        self.output_params, self.prices = update_state_from_row(
            row, self.output_params, self.prices
        )
        print("Updated params:", self.output_params)
        return self.output_params, self.prices

    def on_order_filled(self, data):
        # Update in_position and entry price
        side = data['trd_side'][0]
        price = data['dealt_avg_price'][0]
        if side == 1:  # BUY
            self.in_position = True
            self.entry_price = price
        else:           # SELL
            self.in_position = False
            self.entry_price = None
        print("Order filled:", side, price, "Current position:", self.in_position)

class KlineHandler(CurKlineHandlerBase):
    def __init__(self, strategy):
        super().__init__()
        self.strategy = strategy

    def on_recv_rsp(self, rsp_pb):
        ret_code, data = super().on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            print("Kline callback error:", data)
            return RET_OK, data

        # Get the latest closed candle
        latest_row = data.iloc[-2]  # second latest if last is still forming
        self.strategy.update_state_from_row(latest_row)

        return RET_OK, data

class OrderHandler(TradeOrderHandlerBase):
    def __init__(self, strategy):
        super().__init__()
        self.strategy = strategy

    def on_recv_rsp(self, rsp_pb):
        ret_code, data = super().on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            print("Order callback error:", data)
            return RET_OK, data

        if data['order_status'][0] == OrderStatus.FILLED:
            self.strategy.on_order_filled(data)

        return RET_OK, data

if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description='Run the trading bot in live or test mode.')
    argparser.add_argument('--live', default=False, help='Run the bot in live mode (default is test mode)')
    args = argparser.parse_args()
    live_mode = args.live
    try:
        today_date = pd.Timestamp.today()
        # today_date = pd.Timestamp("2026-02-22")
        output_df = pd.DataFrame(main(today_date))
        if len(output_df):
            sell_df = output_df.loc[output_df['action'] == 'SELL']
            total_pct = compute_total_return(sell_df)
            print(f"Total Return: {total_pct*100:.3f}%")

    except KeyboardInterrupt:
        print("Manual stop detected.")

    except Exception as e:
        print("Unexpected error occurred.")
        print(traceback.format_exc())

    finally:
        if len(output_df):
            output_path = os.path.join(os.getcwd(), 'logs', f"{today_date.strftime('%Y-%m-%d %H:%M:%S')} - logs.csv")
            output_df.to_csv(output_path)

if __name__ == "__main__":
    strategy = Strategy()

    # --- Quote context for K-line ---
    quote_ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    quote_ctx.set_handler(KlineHandler(strategy))
    quote_ctx.subscribe([SYMBOL], [SubType.K_1M])  # 1-minute candles

    # --- Trade context for order updates ---
    trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host="127.0.0.1", port=11111, security_firm=SecurityFirm.FUTUSG)
    trade_ctx.set_handler(OrderHandler(strategy))

    print("Live system started. Waiting for new candles and order updates...")

    try:
        while True:
            time.sleep(1)  # Nothing else needed, all handled in callbacks
    except KeyboardInterrupt:
        print("Shutting down...")
        quote_ctx.close()
        trade_ctx.close()