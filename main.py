import time
import os
import argparse
import pandas as pd
import numpy as np
from moomoo import *

# ================= CONFIG =================
SYMBOL = "HK.00700"
SHORT_WINDOW = 3
LONG_WINDOW = 15
QTY = 100
PROFIT_PCT = 0.01
trade_env = TrdEnv.SIMULATE

# ============================================================
# STRATEGY CLASS
# ============================================================

class MovingAverageStrategy:
    def __init__(self):
        self.output = []
        self.prices = []
        self.last_candle_time = None
        self.position_open = False
        self.entry_price = 0.0
        self.prev_vmap = 0
        self.vmap = 0
        self.pl_pct = 0
        self.cum_sum_pct = 0
        self.cum_turnover = 0
        self.cum_volume = 0

    def update_state_from_row(self, row):

        # From previous/saved data
        prev_price = self.prices[-1] if self.prices else 0

         # Current time
        current_price = row['close']
        self.prices.append(current_price)
        turnover = row['turnover']
        volume = row['volume']

        # Update vmap -> prev_vmap
        self.prev_vmap = self.vmap
        
        # Update cumulative VMAP
        self.cum_turnover += turnover
        self.cum_volume += volume
        self.vmap = self.cum_turnover / self.cum_volume if self.cum_volume else 0
       
        # Compute pct_diff
        if len(self.prices) <= 1 :
            self.pct_diff = 0
        else:
            self.pct_diff = (current_price - prev_price) / prev_price * 100
        self.cum_sum_pct += self.pct_diff
        
       # Maintain rolling window
        self.prices = self.prices[-LONG_WINDOW:]
        self.short_sma = sum(self.prices[-SHORT_WINDOW:]) / SHORT_WINDOW
        self.long_sma = sum(self.prices[-LONG_WINDOW:]) / LONG_WINDOW

    def buy_or_sell(self):
        if len(self.prices) < LONG_WINDOW:
            return "NO DATA"

        action = "HOLD"
        
        current_price = self.prices[-1]
        if self.position_open:
            self.pl_pct = (current_price - self.entry_price) / self.entry_price * 100
        else:
            self.pl_pct = 0
        
        buy_signal = (
            not self.position_open
            and self.short_sma > self.long_sma
            and self.vmap > self.prev_vmap
        )
        sell_signal = (
            self.position_open
            and (self.short_sma < self.long_sma or self.pl_pct >= PROFIT_PCT)
        )
        
        if buy_signal:
            action = "BUY"
        elif sell_signal:
            action = "SELL"
            
        return action

    def save_output(self, row, action, order_data=None):
        candle_dict = {
            "code": row['code'],
            "time": row['time_key'],
            "open": row['open'],
            "close": row['close'],
            "pct_diff": self.pct_diff,
            "short_sma": self.short_sma,
            "long_sma": self.long_sma,
            "Short_above_Long": self.short_sma > self.long_sma,
            "vmap": self.vmap,
            "prev_vmap": self.prev_vmap,
            "VMAP_up": self.vmap > self.prev_vmap,
            "action": action,
            "order_id": order_data['order_id'] if order_data else None,
            "execution_time": "NA",
            "execution_price": "NA",
            "entry_price": self.entry_price,
            "Position": "OPEN" if self.position_open else "CLOSED",
            "pl_pct": self.pl_pct,
            "cum_sum_pct": self.cum_sum_pct,
        }

        self.output.append(candle_dict)
# ============================================================
# MATCHING YOUR place_order FUNCTION
# ============================================================
def place_order(trade_ctx, price, symbol, qty, side, order_type, trd_env):
    """Place a LIMIT/MARKET order in SIMULATE mode"""
    ret, data = trade_ctx.place_order(
        price=price,
        qty=qty,
        code=symbol,
        trd_side=side,
        order_type=order_type,
        trd_env=trd_env
    )
    if ret == RET_OK:
        print(f"✅ Order executed: {side} {qty} {symbol}")
    else:
        print(f"❌ Order failed: {side} {symbol} | {data}")
    return data

def compute_total_return(sell_df):
    total_pct = 1
    for trade_pct in sell_df['pl_pct']:
        total_pct *= (1 + trade_pct / 100)
    total_pct -= 1
    return total_pct
   
# ============================================================
# QUOTE CALLBACK
# ============================================================
class KlineHandler(CurKlineHandlerBase):

    def __init__(self, strategy, trade_ctx):
        super().__init__()
        self.strategy = strategy
        self.trade_ctx = trade_ctx

    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        if ret != RET_OK:
            print("Kline error:", data)
            return RET_ERROR, data
        
        row = data.iloc[-1]
        if row['time_key'] == self.strategy.last_candle_time:
            return RET_OK, data
    
        self.strategy.last_candle_time = row['time_key']
        print(f"Current time: {row['time_key']}, Current price:  {row['close']}")

        # Update state
        self.strategy.update_state_from_row(row)
        
        # Decide action
        action = self.strategy.buy_or_sell()
        
        # Execute action in live mode
        if action == "BUY":
            order_data = place_order(self.trade_ctx, self.strategy.prices[-1], SYMBOL, QTY, TrdSide.BUY, OrderType.MARKET, trade_env)
        elif action == "SELL":
            order_data = place_order(self.trade_ctx, self.strategy.prices[-1], SYMBOL, QTY, TrdSide.SELL, OrderType.MARKET, trade_env)
        else:
            order_data = None
        self.strategy.save_output(row, action, order_data)
            
        return RET_OK, data

# ============================================================
# ORDER CALLBACK (LIVE MODE ONLY)
# ============================================================
class OrderHandler(TradeOrderHandlerBase):
    
    def __init__(self, strategy):
        super().__init__()
        self.strategy = strategy
    
    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        if ret != RET_OK:
            print("❌ Order callback error:", data)
            return RET_ERROR, data

        if data['order_status'].iloc[0] == OrderStatus.FILLED_ALL:
            for o in self.strategy.output:
                if o['order_id'] == data['order_id'].iloc[0]:
                    o['execution_time'] = data['update_time'].iloc[0]
                    o['execution_price'] = data['price'].iloc[0]

                    if data['trd_side'].iloc[0] == TrdSide.BUY:
                        action = "BUY"
                        self.strategy.position_open = True
                        self.strategy.entry_price = o['execution_price']

                    elif data['trd_side'].iloc[0] == TrdSide.SELL:
                        action = "SELL"
                        self.strategy.position_open = False
                        self.strategy.entry_price = 0
                        
                        o['pl_pct'] = (o['execution_price'] - o['entry_price']) / o['entry_price'] * 100
                    else:
                        action = "HOLD"

                    o['position_open'] = self.strategy.position_open
                    o['Position'] = "OPEN" if self.strategy.position_open else "CLOSED"
                    break
            print(f"{SYMBOL} | Price:{data['price'].iloc[0]:.2f} "
                    f"| Action:{action} "
                    f"| Time:{data['update_time'].iloc[0]}")

        return RET_OK, data
         
# ============================================================
# START
# ============================================================
def start(today_date):
   
    strategy = MovingAverageStrategy()
    quote_ctx = OpenQuoteContext(host="127.0.0.1", port=11111)

    if live_mode:
        trade_ctx = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.HK,
            host="127.0.0.1",
            port=11111,
            security_firm=SecurityFirm.FUTUSG
        )
        trade_ctx.set_handler(OrderHandler(strategy))
        quote_ctx.set_handler(KlineHandler(strategy, trade_ctx))
        quote_ctx.subscribe([SYMBOL], [SubType.K_1M], subscribe_push=True)
        
    else:
        trade_ctx = None

    mode = "LIVE TRADING" if live_mode else "SIMULATION MODE"
    print(f"🚀 Started ({mode})")
    print("Press Ctrl+C to exit.")
    if live_mode:
        while True:
            ret, df_state = quote_ctx.get_global_state()
            if ret != RET_OK:
                print(f"[QUOTE] get_global_state failed, ret={df_state}")
            if df_state['market_hk'] == 'CLOSED':
                print("LOOP EXITED: Market closed")
                break
            time.sleep(1)
    else:
        # historical values
        if today_date.day_name() == "Saturday" or today_date.day_name() == "Sunday":
            start_date = (today_date - pd.Timedelta(3, unit='D')).strftime("%Y-%m-%d")
        else:
            start_date = (today_date - pd.Timedelta(1, unit='D')).strftime("%Y-%m-%d")
        end_date = today_date.strftime("%Y-%m-%d")

        ret, historical_df, _ = quote_ctx.request_history_kline(
            SYMBOL,
            start_date,
            end_date,
            SubType.K_1M, 
            AuType.QFQ
        )
        for _, row in historical_df.iterrows():

            # Update state
            strategy.update_state_from_row(row)
        
            # Decide action
            action = strategy.buy_or_sell()

            if action == "BUY":
                strategy.position_open = True
                strategy.entry_price = strategy.prices[-1]
            elif action == "SELL":
                strategy.position_open = False
            
            strategy.save_output(row, action, order_data=None)

            if action == "SELL":
                strategy.entry_price = 0

    return strategy, quote_ctx, trade_ctx

if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description='Run the trading bot in live or test mode.')
    argparser.add_argument('--live', default=False, action='store_true', help='Run the bot in live mode (default is test mode)')
    args = argparser.parse_args()
    live_mode = args.live
    
    try:
        today_date = pd.Timestamp.today()
        strategy, quote_ctx, trade_ctx = start(today_date)
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        if len(strategy.output):
            output_df = pd.DataFrame(strategy.output)
            sell_df = output_df.loc[output_df['action'] == 'SELL']
            total_pct = compute_total_return(sell_df)
            print(f"Total Return: {total_pct*100:.3f}%")
            
            output_path = os.path.join(os.getcwd(), 'logs', f"{today_date.strftime('%Y-%m-%d %H:%M:%S')} - logs.csv")
            output_df.to_csv(output_path)
            quote_ctx.close()
            if live_mode:
                trade_ctx.close()
