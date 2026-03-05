import time
import os
import argparse
import pandas as pd
import numpy as np
from moomoo import *

# ================= CONFIG =================
SYMBOL = "HK.02840"
SHORT_WINDOW = 3
LONG_WINDOW = 15
QTY = 100
PROFIT_PCT = 0
LIVE_MODE = False
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
        # From current time
        current_price = row['close']
        turnover = row['turnover']
        volume = row['volume']

        # Update vmap -> prev_vmap
        self.prev_vmap = self.vmap
        
        # Update cumulative VMAP
        self.cum_turnover += turnover
        self.cum_volume += volume
        self.vmap = self.cum_turnover / self.cum_volume if self.cum_volume else 0
       
        # Compute pct_diff
        prev_price = prices[-1]
        if len(prices) == 0:
            self.pct_diff = 0
        else:
            self.pct_diff = (current_price - prev_price) / prev_price * 100
        self.cum_sum_pct += pct_diff
        
       # Maintain rolling window
        self.prices.append(current_price)
        self.prices = self.prices[-LONG_WINDOW:]
       
        self.short_sma = sum(self.prices[-SHORT_WINDOW:]) / SHORT_WINDOW
        self.long_sma = sum(self.prices[-LONG_WINDOW:]) / LONG_WINDOW
      
    # --------------------------------------------------------
    # MATCHING YOUR buy_or_sell FUNCTION
    # --------------------------------------------------------
    def buy_or_sell(self):
        if len(self.prices) < LONG_WINDOW:
            return "HOLD"

        current_price = self.prices[-1]
        action = "HOLD"
        
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

# ============================================================
# MATCHING YOUR place_order FUNCTION
# ============================================================
def place_order(price, symbol, qty, side, order_type, trd_env):
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
        return True
    else:
        print(f"❌ Order failed: {side} {symbol} | {data}")
        return False

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
    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        if ret != RET_OK:
            print("Kline error:", data)
            return RET_ERROR, data
        
        row = data.iloc[-1]
        if row['time_key'] == strategy.last_candle_time:
            return RET_OK, data
    
        strategy.last_candle_time = row['time_key']

        # 1️⃣ Update state
        strategy.update_state_from_row(row)
        # 2️⃣ Generate decision (matching your function name)
        action = strategy.buy_or_sell()
        
        candle_dict = {
            "code": row['code'],
            "time": row['time_key'],
            "action": action,
            "open": row['open'],
            "close": row['close'],
            "pct_diff": self.pct_diff,
            "short_sma": self.short_sma,
            "long_sma": self.long_sma,
            "Short_above_Long": self.short_sma > self.long_sma,
            "vmap": self.vmap,
            "prev_vmap": self.prev_vmap,
            "VMAP_up": self.vmap > self.prev_vmap,
            "PROFIT_PCT": PROFIT_PCT,
            "entry_price": self.entry_price,
            "Position": "OPEN" if self.position_open else "CLOSED",
            "pl_pct": self.pl_pct,
            "cum_sum_pct": self.cum_sum_pct,
        }

        strategy.output.append(candle_dict)
        
        # 3️⃣ Execute
        if action == "BUY":
            place_order(current_price, SYMBOL, QTY, TrdSide.BUY, OrderType.LIMIT, trade_env)
        elif action == "SELL":
            place_order(current_price, SYMBOL, QTY, TrdSide.SELL, OrderType.MARKET, trade_env)
            
        return RET_OK, data

# ============================================================
# ORDER CALLBACK (LIVE MODE ONLY)
# ============================================================
if LIVE_MODE:
    class OrderHandler(TradeOrderHandlerBase):
        def on_recv_rsp(self, rsp_pb):
            ret, data = super().on_recv_rsp(rsp_pb)
            if ret != RET_OK:
                print("❌ Order callback error:", data)
                return RET_ERROR, data

            if data['order_status'].iloc[0] == FILLED_ALL:
                if data['trd_side'].iloc[0] == TrdSide.BUY:
                    action = "BUY"
                    self.position_open = True
                    self.entry_price = current_price
                elif data['trd_side'].iloc[0] == TrdSide.SELL:
                    action = "SELL"
                    self.position_open = False
                    self.entry_price = 0
                
                print(f"{SYMBOL} | Price:{current_price:.2f} "
                      f"| Action:{action}")

            return RET_OK, data
         
# ============================================================
# START
# ============================================================
def start():
   
   quote_ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
   quote_ctx.set_handler(KlineHandler())
   quote_ctx.subscribe([SYMBOL], [SubType.K_1M], subscribe_push=True)
   
   if LIVE_MODE:
      trade_ctx = OpenSecTradeContext(
          filter_trdmarket=TrdMarket.HK,
          host="127.0.0.1",
          port=11111,
          security_firm=SecurityFirm.FUTUSG
      )
      trade_ctx.set_handler(OrderHandler())
   
   mode = "LIVE TRADING" if LIVE_MODE else "SIMULATION MODE"
   print(f"🚀 Started ({mode})")
   print("Press Ctrl+C to exit.")
   while True:
       time.sleep(1)

if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description='Run the trading bot in live or test mode.')
    argparser.add_argument('--live', default=False, help='Run the bot in live mode (default is test mode)')
    args = argparser.parse_args()
    live_mode = args.live
    
    try:
        today_date = pd.Timestamp.today()
        strategy = MovingAverageStrategy()
        start()
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
            if LIVE_MODE:
                trade_ctx.close()