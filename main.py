import time
import os
import argparse
import talib
import pandas as pd
import numpy as np
from moomoo import *
from pandas.tseries.offsets import BDay

# ================= CONFIG =================
# SYMBOL = "HK.00068"
SYMBOL = "HK.00700"
# SYMBOL = "US.AAPL"
RSI_threshold_follow = 55
RSI_threshold_revert = 35
RSI_PERIOD = 14
SHORT_WINDOW = 12
LONG_WINDOW = 26
MACD_SIGNAL = 9

window_length = max(RSI_PERIOD+1, LONG_WINDOW + MACD_SIGNAL+1)
PROFIT_PCT = 1.5
LOSS_PCT = -1.0
trade_env = TrdEnv.SIMULATE

# ============================================================
# STRATEGY CLASS
# ============================================================

class MovingAverageStrategy:
    def __init__(self):
        self.output = []
        self.prices = []
        self.prev_vwap = 0
        self.vwap = 0
        self.cum_sum_pct = 0
        self.cum_turnover = 0
        self.cum_volume = 0

    def update_state_from_row(self, row, init=False):

        # From previous/saved data
        prev_price = self.prices[-1] if self.prices else 0

         # Current time
        current_price = row['close']
        self.prices.append(current_price)
        turnover = row['turnover']
        volume = row['volume']

        # Skip vwap computation during init
        if init == False:
            # Update vwap -> prev_vwap
            self.prev_vwap = self.vwap
            
            # Update cumulative vwap
            self.cum_turnover += turnover
            self.cum_volume += volume
            self.vwap = self.cum_turnover / self.cum_volume if self.cum_volume else 0
       
        # Compute pct_diff
        if len(self.prices) <= 1 :
            self.pct_diff = 0
        else:
            self.pct_diff = (current_price - prev_price) / prev_price * 100
        self.cum_sum_pct += self.pct_diff
        
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

        # Compute RSI if enough prices, else 0
        if len(self.prices) >= RSI_PERIOD+1:
            self.rsi = talib.RSI(np.array(self.prices[-(RSI_PERIOD+1):]), timeperiod=RSI_PERIOD)[-1]
        else:
            self.rsi = 0

        # Compute MACD if enough prices, else 0
        if len(self.prices) >= LONG_WINDOW + MACD_SIGNAL+1:
            macd, macd_signal, macd_histogram = talib.MACD(
                np.array(self.prices[-(LONG_WINDOW + MACD_SIGNAL+1):]),
                fastperiod=SHORT_WINDOW,
                slowperiod=LONG_WINDOW,
                signalperiod=MACD_SIGNAL
            )
            self.macd = macd[-1]
            self.macd_signal = macd_signal[-1]
            self.macd_histogram = macd_histogram[-1]
        else:
            self.macd, self.macd_signal, self.macd_histogram = 0, 0, 0
    
    def compute_pl(self, current_price):
        # unrealized -> to compute pl before BUY/SELL (use current cost_price)
        # realized -> to compute pl after BUY/SELL (use previous cost_price)

        # position OPEN (BUY/SELL)
        if self.cost_price > 0:
            self.position_open = True
            pl_pct = (current_price - self.cost_price) / self.cost_price * 100
        # position CLOSED (SELL)
        else:
            self.position_open = False
            pl_pct = 0
    
        return pl_pct

    def buy_or_sell(self, pl_pct=0):
        if len(self.prices) < window_length:
            return "INITIALIZING", "INITIALIZING", "INITIALIZING"
        
        action = "HOLD"
        
        # buy ratio 0 < x < 1
        trend_strength = self.macd - self.macd_signal
        buy_ratio = max(0, min(0.9, trend_strength/0.005))
        if self.max_cash_buy > 0:
            buy_qty = int(self.max_cash_buy * buy_ratio)
        else:
            buy_qty = 0

        # sell ratio 0 < x < 1
        sell_ratio = min(1, abs(pl_pct/LOSS_PCT))
        if self.max_position_sell > 0:
            sell_qty = max(1, int(self.max_position_sell * sell_ratio))
        else:
            sell_qty = 0
        
        # A: trend following
        if self.market_trend > 0:
            buy_signal = (
                buy_qty > 0
                and trend_strength > 0
                and self.rsi > RSI_threshold_follow
            )
        # B: mean reversion
        else:
             buy_signal = (
                buy_qty > 0
                and trend_strength < 0
                and self.rsi < RSI_threshold_revert
            )

        # if pl_pct >= PROFIT_PCT, only sell when hit loss pct or above, regardless of MACD signal (take profit)
        if pl_pct >= PROFIT_PCT:
            sell_signal = (
                sell_qty > 0
                and self.macd < self.macd_signal
                and self.rsi < RSI_threshold_revert
            )
        else:
        # if not hit profit pct, sell when MACD signal is unfavorable or hit loss pct (cut loss)
            sell_signal = (
                sell_qty > 0
                and (self.macd < self.macd_signal
                or pl_pct <= LOSS_PCT)
            )
        if buy_signal:
            action = "BUY"
        if sell_signal:
            action = "SELL"
            
        return action, buy_qty, sell_qty

    def save_output(self, row, action, order_data=None):
        candle_dict = {
            "code": row['code'],
            "time": row['time_key'],
            "open": row['open'],
            "close": row['close'],
            "pct_diff": self.pct_diff,
            "short_sma": self.short_sma,
            "long_sma": self.long_sma,
            # "vwap": self.vwap,
            # "prev_vwap": self.prev_vwap,
            # "vwap_up": self.vwap > self.prev_vwap,
            "RSI": self.rsi,
            "MACD": self.macd,
            "MACD Signal": self.macd_signal,
            "MACD_up": (self.macd - self.macd_signal) > 0,
            "hit_profit": self.unrealized_pl_pct >= PROFIT_PCT,
            "hit_loss": self.unrealized_pl_pct <= LOSS_PCT,
            "MACD Histogram": self.macd_histogram,
            "cost_price": self.cost_price,
            "max_cash_buy": self.max_cash_buy,
            "max_position_sell": self.max_position_sell,
            "action": action,
            "order_id": order_data['order_id'].iloc[0] if order_data is not None else None,
            "execution_time": "NA",
            "execution_price": "NA",
            "Position": "OPEN" if self.position_open else "CLOSED",
            "unrealized_pl_pct": self.unrealized_pl_pct,
            "realized_pl_pct": self.realized_pl_pct,
            "cum_sum_pct": self.cum_sum_pct,
            "market_trend": self.market_trend
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

def get_position_status(trade_ctx):
    """Check if there's an open position for the symbol and return positions"""
    ret, positions = trade_ctx.position_list_query(trd_env=trade_env)
    if ret != RET_OK:
        print("Error fetching positions:", positions)
        return None
    
    # for CLOSED positions
    cost_price = 0
    for _, row in positions.iterrows():
        # for OPEN positions, find latest cost price
        if SYMBOL == row['code']:
            cost_price = row['cost_price']
            break
    return cost_price
    
def get_available_qty(trade_ctx, current_price, lot_size):
    ret, max_qty_to_trade = trade_ctx.acctradinginfo_query(order_type=OrderType.NORMAL, code=SYMBOL, price=current_price, trd_env=trade_env)
    if ret != RET_OK:
        print("Error fetching trading info:", max_qty_to_trade)
        return 0
    
    max_cash_buy = max_qty_to_trade['max_cash_buy'].iloc[0] // lot_size
    max_position_sell = max_qty_to_trade['max_position_sell'].iloc[0] // lot_size

    return max_cash_buy, max_position_sell

def initialize_rows(strategy, trade_ctx, quote_ctx, prev_date, end_date, lot_size):
    
    ret, historical_df, _ = quote_ctx.request_history_kline(
        SYMBOL,
        prev_date,
        end_date,
        SubType.K_1M, 
        AuType.NONE
    )
    if ret != RET_OK:
        print("Error fetching historical data:", historical_df)
        return 0

    # Intialize first window_length-1 candles to fill the strategy state
    df_past = historical_df.iloc[-window_length+1:]
    for i in range(len(df_past)):
        
        row = df_past.iloc[i]
        strategy.update_state_from_row(row, init=True)
        current_price = strategy.prices[-1]
        
        if live_mode:
            strategy.cost_price = get_position_status(trade_ctx)
            strategy.unrealized_pl_pct = strategy.compute_pl(current_price)
        else:
            strategy.position_open = False
            strategy.unrealized_pl_pct = 0
            strategy.cost_price = 0

        strategy.market_trend = 0
        strategy.realized_pl_pct = 0

        if i == 0:
            max_cash_buy, max_position_sell = get_available_qty(trade_ctx, current_price, lot_size)
            if live_mode:
                strategy.max_cash_buy = max_cash_buy
                strategy.max_position_sell = max_position_sell
            else:
                strategy.max_cash_buy = max_cash_buy + max_position_sell
                strategy.max_position_sell = 0
        action, _, _ = strategy.buy_or_sell()
        strategy.save_output(row, action, order_data=None)

    print("Initialized time: ", df_past['time_key'].iloc[-1])
    return None

def compute_daily_pl(today_date, output_df, file_name, price, lot_size):
    output_filename = file_name.split('_')[0]
    output_df['next_max_position_sell'] = output_df['max_position_sell'].shift(-1)
    output_df['trade_qty'] = abs(output_df['next_max_position_sell'] - output_df['max_position_sell'])

    buy_df = output_df.loc[output_df['action'] == 'BUY']
    buy_df['capital'] = buy_df[price] * buy_df['trade_qty'] * lot_size
    initial_capital = buy_df['capital'].sum()
    print(f"Initial Capital: {initial_capital:.0f}")
    sell_df = output_df.loc[output_df['action'] == 'SELL']
    sell_df['realized_pl'] = (sell_df[price] - sell_df['cost_price']) * sell_df['trade_qty'] * lot_size
    if initial_capital > 0:
        total_pct = sell_df['realized_pl'].sum()/initial_capital * 100
    else:
        total_pct = 0
        
    print(f"Total Return: {sell_df['realized_pl'].sum():.0f}, {total_pct:.3f}%")
    output_path = os.path.join(os.getcwd(), 'logs', f"{today_date.strftime('%Y-%m-%d %H:%M:%S')} - pl_{output_filename}.csv")
    sell_df.to_csv(output_path)
# ============================================================
# QUOTE CALLBACK
# ============================================================
class KlineHandler(CurKlineHandlerBase):
    
    def __init__(self, strategy, quote_ctx, trade_ctx, lot_size):
        super().__init__()
        self.strategy = strategy
        self.quote_ctx = quote_ctx
        self.trade_ctx = trade_ctx
        self.lot_size = lot_size
        self.prev_candle = None

    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        if ret != RET_OK:
            print("Kline error:", data)
            return RET_ERROR, data

        current_candle = data.iloc[-1]
        # When new candle starts, process prev_candle
        if self.prev_candle is None:
            self.prev_candle = current_candle
            action ='HOLD'
            self.strategy.save_output(self.prev_candle, action, order_data=None)
        if current_candle['time_key'] != self.prev_candle['time_key']:
            print(f"Current time: {self.prev_candle['time_key']}, Current price:  {self.prev_candle['close']}")

            # Update state
            self.strategy.update_state_from_row(self.prev_candle, init=False)

            current_price = self.strategy.prices[-1]

            # unrealized -> get cost_price before compute pl
            self.strategy.cost_price = get_position_status(self.trade_ctx)
            self.strategy.unrealized_pl_pct = self.strategy.compute_pl(current_price)
            
            self.strategy.max_cash_buy, self.strategy.max_position_sell = get_available_qty(self.trade_ctx, current_price, self.lot_size)
            
            # get trend signal
            ret, data = self.quote_ctx.get_market_snapshot(['HK.800000'])
            self.strategy.market_trend = data['last_price'].iloc[0] - data['prev_close_price'].iloc[0]
            # Decide action
            action, buy_qty, sell_qty = self.strategy.buy_or_sell(self.strategy.unrealized_pl_pct)

            BUY_QTY = self.lot_size * buy_qty
            SELL_QTY = self.lot_size * sell_qty
            # Execute action in live mode
            if action == "BUY":
                print("Max QTY to Buy:", self.strategy.max_cash_buy)
                order_data = place_order(self.trade_ctx, self.strategy.prices[-1], SYMBOL, BUY_QTY, TrdSide.BUY, OrderType.MARKET, trade_env)
            elif action == "SELL":
                print("Max QTY to Sell:", self.strategy.max_position_sell)
                order_data = place_order(self.trade_ctx, self.strategy.prices[-1], SYMBOL, SELL_QTY, TrdSide.SELL, OrderType.MARKET, trade_env)
            else:
                order_data = None
                self.strategy.realized_pl_pct = 0
            self.strategy.save_output(self.prev_candle, action, order_data)
        
        self.prev_candle = current_candle

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

                    # realized -> get cost_price after compute pl
                    match action:
                        # update cost price if BUY
                        case 'BUY':
                            self.strategy.realized_pl_pct = 0
                            self.strategy.cost_price = get_position_status(self.trade_ctx)
                            o['cost_price'] = self.strategy.cost_price

                        case 'SELL':
                            self.strategy.realized_pl_pct = self.strategy.compute_pl(current_price)

                    o['execution_time'] = data['updated_time'].iloc[0]
                    o['execution_price'] = current_price
                    o['realized_pl_pct'] = self.strategy.realized_pl_pct
                    o['Position'] = "OPEN" if self.strategy.position_open else "CLOSED"
                    
                    print(f"{SYMBOL} | Price:{o['execution_price']:.2f} "
                    f"| Action:{action} "
                    f"| Time:{o['execution_time']}")
                    if action == 'SELL':
                        print(f"|Cost Price:{o['cost_price']}, Sell Price:{o['execution_price']},  Profit:{o['realized_pl_pct']:.2f}")
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

    strategy = MovingAverageStrategy()

    quote_ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    trade_ctx = OpenSecTradeContext(
            filter_trdmarket=trade_market,
            host="127.0.0.1",
            port=11111,
            security_firm=SecurityFirm.FUTUSG
    )
    
    ret, stock_data = quote_ctx.get_stock_basicinfo(
        market=trade_market,
        stock_type=SecurityType.STOCK,
        code_list=SYMBOL
    )
    lot_size = stock_data['lot_size'].iloc[0]

    # Intialize first LONG_WINDOW-1 rows to fill the strategy state
    prev_date = (today_date - BDay(3)).strftime('%Y-%m-%d')
    if live_mode:
        end_date = today_date.strftime('%Y-%m-%d')
    else:
        if today_date.time() < pd.Timestamp("09:30").time():
            # before market open → use last completed trading day
            end_date = (today_date - BDay(2)).strftime('%Y-%m-%d')
        else:
            end_date = (today_date - BDay(1)).strftime('%Y-%m-%d')
    
    initialize_rows(strategy, trade_ctx, quote_ctx, prev_date, end_date, lot_size)

    if live_mode:    
        trade_ctx.set_handler(OrderHandler(strategy, trade_ctx, lot_size))
        quote_ctx.set_handler(KlineHandler(strategy, quote_ctx, trade_ctx, lot_size))
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
                return strategy, quote_ctx, trade_ctx, lot_size
            time.sleep(1)
    else:
        ret, df_current, _ = quote_ctx.request_history_kline(
            SYMBOL,
            (pd.to_datetime(end_date) + BDay(1)).strftime('%Y-%m-%d'),
            (pd.to_datetime(end_date) + BDay(1)).strftime('%Y-%m-%d'),
            SubType.K_1M, 
            AuType.NONE
        )

        ret2, df_HSI, _ = quote_ctx.request_history_kline(
                "HK.800000",
                (pd.to_datetime(end_date) + BDay(1)).strftime('%Y-%m-%d'),
                (pd.to_datetime(end_date) + BDay(1)).strftime('%Y-%m-%d'),
                SubType.K_1M, 
                AuType.NONE
            )
        
        total_price = strategy.cost_price * strategy.max_position_sell
        for _, row in df_current.iterrows():
            strategy.update_state_from_row(row, init=False)
            current_price = strategy.prices[-1]

            # Manual function for get_position_status
            # unrealized -> get cost_price before compute pl
            if strategy.max_position_sell > 0:
                total_price = strategy.cost_price * strategy.max_position_sell
            else:
                total_price = 0

            strategy.unrealized_pl_pct = strategy.compute_pl(current_price)

            # get_available_qty called once during init rows

            # buy_or_sell
            curr_time = row['time_key']
            strategy.market_trend = df_HSI.loc[df_HSI['time_key'] == curr_time, 'close'].iloc[0] - df_HSI.loc[df_HSI['time_key'] == curr_time, 'last_close'].iloc[0]
            action, buy_qty, sell_qty = strategy.buy_or_sell(strategy.unrealized_pl_pct)
            
            # place_order + OrderHandler
            if action == 'BUY':
                next_max_cash_buy = strategy.max_cash_buy - buy_qty
                next_max_position_sell = strategy.max_position_sell + buy_qty
                
                # compute_pl then get_position_status
                total_price += current_price * buy_qty
                strategy.realized_pl_pct = 0
                strategy.cost_price = total_price / next_max_position_sell
                print(f"BUY | {buy_qty*lot_size} {SYMBOL} | Cost: {strategy.cost_price:.2f}")
            elif action == 'SELL':
                next_max_cash_buy = strategy.max_cash_buy + sell_qty
                next_max_position_sell = strategy.max_position_sell - sell_qty

                # compute_pl
                strategy.realized_pl_pct = strategy.compute_pl(current_price)
                # cost price not updated, but not logged
                print(f"SELL | {sell_qty*lot_size} {SYMBOL} | Cost: {strategy.cost_price:.2f} | Profit: {strategy.realized_pl_pct:.2f}")
            elif action == 'HOLD':
                next_max_cash_buy = strategy.max_cash_buy
                next_max_position_sell = strategy.max_position_sell
                strategy.realized_pl_pct = 0
                # cost price remain the same

            # Manual function for get_position_status, done before current iteration
            if next_max_position_sell > 0:
                strategy.position_open = True
            else:
                strategy.position_open = False
            print(f"Current time: {row['time_key']}, Current price:  {row['close']}, Unrealized P/L: {strategy.unrealized_pl_pct}")
            strategy.save_output(row, action, order_data=None)

            # To be done before next iteration of buy_or_sell
            # Manual function for get_available_qty
            strategy.max_cash_buy = next_max_cash_buy
            strategy.max_position_sell = next_max_position_sell

    return strategy, quote_ctx, trade_ctx, lot_size

if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description='Run the trading bot in live or test mode.')
    argparser.add_argument('--live', default=False, action='store_true', help='Run the bot in live mode (default is test mode)')
    argparser.add_argument('--date', default=pd.Timestamp.today(), help='Current date, or previous date for backtesting')
    args = argparser.parse_args()
    live_mode = args.live
    if live_mode:
        today_date = args.date
    else:
        today_date = pd.to_datetime(str(args.date) + ' 23:59:00')
    
    try:
        strategy, quote_ctx, trade_ctx, lot_size = start(today_date)
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        if len(strategy.output):
            output_df = pd.DataFrame(strategy.output)
            if live_mode:
                file_name = 'live_trading_logs.csv'
                price = 'execution_price'
            else:
                file_name = 'simulated_trading_logs.csv'
                price = 'close'
            output_path = os.path.join(os.getcwd(), 'logs', f"{today_date.strftime('%Y-%m-%d %H:%M:%S')} - {file_name}")
            print(output_path)
            output_df.to_csv(output_path)

            compute_daily_pl(today_date, output_df, file_name, price, lot_size)
            quote_ctx.close()
            trade_ctx.close()
