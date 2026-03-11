import time
import os
import argparse
import pandas as pd
import numpy as np
from moomoo import *
from pandas.tseries.offsets import BDay

# ================= CONFIG =================
SYMBOL = "HK.00700"
# SYMBOL = "US.AAPL"
SHORT_WINDOW = 3
LONG_WINDOW = 15
PROFIT_PCT = 1
trade_env = TrdEnv.SIMULATE

# ============================================================
# STRATEGY CLASS
# ============================================================

class MovingAverageStrategy:
    def __init__(self, trade_ctx):
        self.trade_ctx = trade_ctx
        self.output = []
        self.prices = []
        self.last_candle_time = None
        self.realized_pl_pct = 0
        self.vmap = 0
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
        # Compute short SMA if enough prices, else 0
        if len(self.prices) >= SHORT_WINDOW:
            self.short_sma = sum(self.prices[-SHORT_WINDOW:]) / SHORT_WINDOW
        else:
            self.short_sma = 0

        # Compute long SMA if enough prices, else 0
        if len(self.prices) >= LONG_WINDOW:
            self.long_sma = sum(self.prices[-LONG_WINDOW:]) / LONG_WINDOW
        else:
            self.long_sma = 0

    def buy_or_sell(self, unrealized_pl_pct=0):
        if len(self.prices) < LONG_WINDOW:
            return "INITIALIZING", "INITIALIZING"
        
        action = "HOLD"

        sell_ratio = min(0.5, unrealized_pl_pct / 2)
        sell_qty = int(self.max_position_sell * sell_ratio)
        
        buy_signal = (
            self.short_sma > self.long_sma
            and self.vmap > self.prev_vmap
            and self.max_cash_buy > 0
        )
        sell_signal = (
            self.short_sma < self.long_sma
            and unrealized_pl_pct >= PROFIT_PCT
            and sell_qty > 0
        )
        
        if buy_signal:
            action = "BUY"
        elif sell_signal:
            action = "SELL"
            
        return action, sell_qty

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
            "cost_price": self.cost_price,
            "max_cash_buy": self.max_cash_buy,
            "max_position_sell": self.max_position_sell,
            "action": action,
            "order_id": order_data['order_id'].iloc[0] if order_data is not None else None,
            "execution_time": "NA",
            "execution_price": "NA",
            "Position": "OPEN" if self.position_open else "CLOSED",
            "realized_pl_pct": self.realized_pl_pct,
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

def get_position_status(trade_ctx, current_price):
    """Check if there's an open position for the symbol and return entry price and P/L%"""
    ret, positions = trade_ctx.position_list_query(trd_env=trade_env)
    if ret != RET_OK:
        print("Error fetching positions:", positions)
        return None, None

    for _, row in positions.iterrows():
        if SYMBOL == row['code'] and row['cost_price'] > 0:
            position_open = True
            cost_price = row['cost_price']
            unrealized_pl_pct = (current_price - cost_price) / cost_price * 100
            break
        else:
            position_open = False
            unrealized_pl_pct = 0
            cost_price = 0

    return position_open, unrealized_pl_pct, cost_price

def get_available_qty(trade_ctx, current_price, lot_size):
    ret, max_qty_to_trade = trade_ctx.acctradinginfo_query(order_type=OrderType.NORMAL, code=SYMBOL, price=current_price, trd_env=trade_env)
    if ret != RET_OK:
        print("Error fetching trading info:", max_qty_to_trade)
        return 0
    
    max_cash_buy = max_qty_to_trade['max_cash_buy'].iloc[0] // lot_size
    max_position_sell = max_qty_to_trade['max_position_sell'].iloc[0] // lot_size

    return max_cash_buy, max_position_sell

def initialize_rows(strategy, quote_ctx, prev_date, end_date, lot_size):
    
    ret, historical_df, _ = quote_ctx.request_history_kline(
        SYMBOL,
        prev_date,
        end_date,
        SubType.K_1M, 
        AuType.QFQ
    )
    if ret != RET_OK:
        print("Error fetching historical data:", historical_df)
        return 0

    # Intialize first LONG_WINDOW-1 candles to fill the strategy state
    df_past = historical_df.iloc[-LONG_WINDOW+1:]
    for i in range(len(df_past)):
        row = df_past.iloc[i]
        strategy.update_state_from_row(row)
        current_price = strategy.prices[-1]
        strategy.position_open, unurealized_pl_pct, strategy.cost_price = get_position_status(strategy.trade_ctx, current_price)
        if i == 0:
            # Get available qty for the first row to initialize the strategy state correctly
            strategy.max_cash_buy, strategy.max_position_sell = get_available_qty(strategy.trade_ctx, current_price, lot_size)
        action, _ = strategy.buy_or_sell()
        strategy.save_output(row, action, order_data=None)
    return unurealized_pl_pct

# ============================================================
# QUOTE CALLBACK
# ============================================================
class KlineHandler(CurKlineHandlerBase):

    def __init__(self, strategy, trade_ctx, lot_size):
        super().__init__()
        self.strategy = strategy
        self.trade_ctx = trade_ctx
        self.lot_size = lot_size

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
        
        if len(self.strategy.prices):
            current_price = self.strategy.prices[-1]
            self.strategy.position_open, unrealized_pl_pct, self.strategy.cost_price = get_position_status(self.trade_ctx, current_price)
        
        self.strategy.max_cash_buy, self.strategy.max_position_sell = get_available_qty(self.trade_ctx, current_price, self.lot_size)
        # Decide action
        action, sell_qty = self.strategy.buy_or_sell(unrealized_pl_pct)

        QTY = self.lot_size * 1
        # Execute action in live mode
        if action == "BUY":
            order_data = place_order(self.trade_ctx, self.strategy.prices[-1], SYMBOL, QTY, TrdSide.BUY, OrderType.MARKET, trade_env)
        elif action == "SELL":
            order_data = place_order(self.trade_ctx, self.strategy.prices[-1], SYMBOL, sell_qty, TrdSide.SELL, OrderType.MARKET, trade_env)
        else:
            order_data = None
        self.strategy.save_output(row, action, order_data)
            
        return RET_OK, data

# ============================================================
# ORDER CALLBACK (LIVE MODE ONLY)
# ============================================================
class OrderHandler(TradeOrderHandlerBase):
    
    def __init__(self, strategy, trade_ctx, lot_size):
        super().__init__()
        self.strategy = strategy
        self.trade_ctx = trade_ctx
        self.lot_size = lot_size

    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        if ret != RET_OK:
            print("❌ Order callback error:", data)
            return RET_ERROR, data
        
        if data['order_status'].iloc[0] == "FILLED_ALL":
            for o in self.strategy.output:
                if o['order_id'] == data['order_id'].iloc[0]:
                    action = data['trd_side'].iloc[0]
                    current_price = data['dealt_avg_price'].iloc[0]
                    self.strategy.position_open, self.strategy.realized_pl_pct, self.strategy.cost_price = get_position_status(self.trade_ctx, current_price)
                    
                    o['execution_time'] = data['updated_time'].iloc[0]
                    o['execution_price'] = current_price
                    o['position_open'] = self.strategy.position_open
                    o['cost_price'] = self.strategy.cost_price
                    o['Position'] = "OPEN" if self.strategy.position_open else "CLOSED"
                    
                    print(f"{SYMBOL} | Price:{o['execution_price']:.2f} "
                    f"| Action:{action} "
                    f"| Time:{o['execution_time']}")
                    if action == 'SELL':
                        print(f"|Cost Price:{o['cost_price']}, Sell Price:{o['execution_price']},  Profit:{o['unrealized_   pl_pct']:.2f}")
                    break

        return RET_OK, data
         
# ============================================================
# START
# ============================================================

def start(today_date):
    if SYMBOL.startswith("HK."):
        trade_market = TrdMarket.HK
        market = 'market_hk'
    elif SYMBOL.startswith("US."):
        trade_market = TrdMarket.US
        market = 'market_us'

    quote_ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    trade_ctx = OpenSecTradeContext(
            filter_trdmarket=trade_market,
            host="127.0.0.1",
            port=11111,
            security_firm=SecurityFirm.FUTUSG
    )
    strategy = MovingAverageStrategy(trade_ctx)

    ret, stock_data = quote_ctx.get_stock_basicinfo(
        market=trade_market,
        stock_type=SecurityType.STOCK,
        code_list=SYMBOL
    )
    lot_size = stock_data['lot_size'].iloc[0]

    # Intialize first LONG_WINDOW-1 rows to fill the strategy state
    if live_mode:
        prev_date = (today_date - BDay(1)).strftime('%Y-%m-%d')
        end_date = today_date.strftime('%Y-%m-%d')
    else:
        if today_date.time() < pd.Timestamp("09:30").time():
            # before market open → use last completed trading day
            prev_date = (today_date - BDay(2)).strftime('%Y-%m-%d')
        else:
            prev_date = (today_date - BDay(1)).strftime('%Y-%m-%d')
        end_date = prev_date
    print(prev_date, end_date)
    unrealized_pl_pct = initialize_rows(strategy, quote_ctx, prev_date, end_date, lot_size)

    if live_mode:    
        trade_ctx.set_handler(OrderHandler(strategy, trade_ctx, lot_size))
        quote_ctx.set_handler(KlineHandler(strategy, trade_ctx, lot_size))
        ret, data = quote_ctx.subscribe([SYMBOL], [SubType.K_1M], subscribe_push=True)
        if ret != RET_OK:
            print(f"Subscription failed: {data}")

    mode = "LIVE TRADING" if live_mode else "SIMULATION MODE"
    print(f"🚀 Started ({mode})")
    print("Press Ctrl+C to exit.")
    if live_mode:
        while True:
            ret, df_state = quote_ctx.get_global_state()
            if ret != RET_OK:
                print(f"[QUOTE] get_global_state failed, ret={df_state}")
            if df_state[market] == 'CLOSED':
                print("LOOP EXITED: Market closed")
                break
            time.sleep(1)
    else:
        ret, df_current, _ = quote_ctx.request_history_kline(
            SYMBOL,
            (pd.to_datetime(prev_date) + BDay(1)).strftime('%Y-%m-%d'),
            (pd.to_datetime(prev_date) + BDay(1)).strftime('%Y-%m-%d'),
            SubType.K_1M, 
            AuType.QFQ
        )

        total_price = strategy.cost_price * strategy.max_position_sell
        for _, row in df_current.iterrows():
            strategy.update_state_from_row(row)
            strategy.realized_pl_pct = unrealized_pl_pct
            action, sell_qty = strategy.buy_or_sell(strategy.realized_pl_pct)
            if len(strategy.prices):
                current_price = strategy.prices[-1]
                strategy.position_open = True
                if action == 'BUY':
                    strategy.max_cash_buy -= 1
                    strategy.max_position_sell += 1
                    total_price += current_price
                    strategy.cost_price = total_price / strategy.max_position_sell
                    strategy.realized_pl_pct = 0
                elif action == 'SELL':
                    strategy.max_cash_buy += sell_qty
                    strategy.max_position_sell -= sell_qty
                    total_price -= current_price * sell_qty
                    if strategy.max_position_sell > 0:
                        strategy.cost_price = total_price / strategy.max_position_sell
                        strategy.realized_pl_pct = (current_price - strategy.cost_price) / strategy.cost_price * 100
                    else:
                        strategy.cost_price = 0
                        strategy.realized_pl_pct = 0
                    
                elif action == 'HOLD':
                    strategy.realized_pl_pct = 0

                if strategy.max_position_sell > 0:
                    strategy.position_open = True
                else:
                    strategy.position_open = False

            strategy.save_output(row, action, order_data=None)

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
            output_path = os.path.join(os.getcwd(), 'logs', f"{pd.Timestamp.today().strftime('%Y-%m-%d %H:%M:%S')} - logs.csv")
            output_df.to_csv(output_path)
            quote_ctx.close()
            trade_ctx.close()
