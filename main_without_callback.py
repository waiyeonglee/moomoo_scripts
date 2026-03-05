import time
import os
import argparse
import pandas as pd
import numpy as np
from moomoo import *
import matplotlib.pyplot as plt
from sklearn.metrics import mean_absolute_error, root_mean_squared_error, mean_absolute_percentage_error

trade_env = TrdEnv.SIMULATE
SHORT_WINDOW = 3
LONG_WINDOW = 15
SYMBOL = "HK.00700"
PROFIT_PCT = 0
buy_cond = 'FIXED_PROFIT_PCT'
QTY = 100

quote_ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host="127.0.0.1", port=11111, security_firm=SecurityFirm.FUTUSG)

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
    
def subscribe_quotes(symbol):
    quote_ctx.subscribe([symbol], [SubType.QUOTE, SubType.K_1M])
    ret, data = quote_ctx.query_subscription()
    if ret != RET_OK:
        raise RuntimeError(f"[QUOTE] query_subscription failed, ret={data}")

def buy_or_sell(short_sma, long_sma, vmap, prev_vmap, PROFIT_PCT, current_price, position_open, entry_price):    
    pl_pct = 0.0
    action = 'HOLD'

    # Compute P/L if position is open
    if position_open:
        pl_pct = ((current_price - entry_price) / entry_price * 100)

    # ---------------------
    # BUY/SELL LOGIC
    # ---------------------
    buy_signal = not position_open and short_sma > long_sma and vmap > prev_vmap
    sell_signal = position_open and (short_sma < long_sma or pl_pct >= PROFIT_PCT)

    if buy_signal:
        action = 'BUY'

        if live_mode:
            success = place_order(current_price, SYMBOL, QTY, TrdSide.BUY, OrderType.MARKET, trade_env)
        else:
            success = True

        if success:
            position_open = True
            entry_price = current_price

    elif sell_signal:
        action = 'SELL'

        if live_mode:
            success = place_order(current_price, SYMBOL, QTY, TrdSide.SELL, OrderType.MARKET, trade_env)
        else:
            success = True
            
        if success:
            position_open = False
            entry_price = 0.0

    print(f"{SYMBOL} | Short SMA: {short_sma:.2f} | Long SMA: {long_sma:.2f} | "
            f"Price: {current_price:.2f} | Position: {'OPEN' if position_open else 'CLOSED'} | Action: {action}")

    return position_open, entry_price, action, pl_pct

def compute_total_return(sell_df):
    total_pct = 1
    for trade_pct in sell_df['pl_pct']:
        total_pct *= (1 + trade_pct / 100)
    total_pct -= 1
    return total_pct

def update_state_from_row(data, output_params, prices):
    
    # Initialization
    if len(data) > 1:
        row = data.iloc[-1]  # last historical row
        # Initialize cumulative fields
        prev_vmap, entry_price, pl_pct, cum_sum_pct = 0, 0, 0, 0
        action = 'NO DATA'
        position_open = False   

        prev_price = data.iloc[-2]['close']
        cum_turnover = data['turnover'].sum()
        cum_volume = data['volume'].sum()

        short_sma = data.iloc[-SHORT_WINDOW:]['close'].mean()
        long_sma = data.iloc[-LONG_WINDOW:]['close'].mean()
        prices = data['close'].tolist()

    # Current time
    elif len(data) == 1:
        row = data.iloc[0]
        # Increment cumulative fields
        prev_vmap = output_params['vmap']
        entry_price = output_params['entry_price']
        position_open = output_params['position_open']

        prev_price = output_params['close']
        cum_turnover = output_params['cum_turnover'] + row['turnover']
        cum_volume = output_params['cum_volume'] + row['volume']
    code = row['code']
    # Computation of states from previous values, output_params
    vmap = cum_turnover / cum_volume if cum_volume != 0 else 0
    
    # Current price from current timestamp
    cur_time = row['time_key']
    open_price = row['open']
    current_price = row['close'] # / open

    # Compute PROFIT_PCT as mean of pct_diff
    if prev_price == 0:
        pct_diff = 0
    else:
        pct_diff = (current_price - prev_price) / prev_price * 100

    # pct_mean = cum_sum_pct / (i+1)
    # if buy_cond != 'FIXED_PROFIT_PCT':
    #     if pct_mean > 0:
    #         PROFIT_PCT = pct_mean
    #     else:
    #         PROFIT_PCT = 0

    # During initialization, skip Buy/Sell
    if len(data) == 1:
        short_sma = output_params['short_sma']
        long_sma = output_params['long_sma']
        cum_sum_pct = output_params['cum_sum_pct'] + pct_diff

        position_open, entry_price, action, pl_pct = buy_or_sell(
            short_sma,
            long_sma,
            vmap,
            prev_vmap,
            PROFIT_PCT,
            current_price,
            position_open,
            entry_price
        )

        # truncate prices to ensure it only takes the last LONG WINDOW items
        prices.append(current_price)
        prices = prices[-LONG_WINDOW:]
        short_sma = sum(prices[-SHORT_WINDOW:]) / SHORT_WINDOW
        long_sma  = sum(prices[-LONG_WINDOW:]) / LONG_WINDOW
        
    output_params = {
        "code": code,
        "time": cur_time,
        "action": action,
        "open": open_price,
        "close": current_price,
        "pct_diff": pct_diff,
        "short_sma": short_sma,
        "long_sma": long_sma,
        "Short_above_Long": short_sma > long_sma,
        "vmap": vmap,
        "prev_vmap": prev_vmap,
        "VMAP_up": vmap > prev_vmap,
        "PROFIT_PCT": PROFIT_PCT,
        "position_open": position_open,
        "entry_price": entry_price,
        "Position": "OPEN" if position_open else "CLOSED",
        "pl_pct": pl_pct,
        "cum_sum_pct": cum_sum_pct,
        "cum_turnover": cum_turnover,
        "cum_volume": cum_volume
    }

    return output_params, prices

def main(today_date):

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
    if ret != RET_OK:
        raise RuntimeError(f"[QUOTE] get_stock_quote failed, ret={historical_df}")
    df_past = historical_df.iloc[:LONG_WINDOW]
    
    if not live_mode:
        df_current = historical_df.iloc[LONG_WINDOW:]

    output_params, prices = update_state_from_row(df_past, output_params={}, prices=None)
    output = []
    i = 0

    # main loop
    while True:
        start = time.time()

        # Exit condition for test mode
        if not live_mode and i>=len(df_current):
            print("TEST: LOOP EXIT")
            quote_ctx.close()
            trade_ctx.close()
            break

        if live_mode:
            
            ret, df_state = quote_ctx.get_global_state()
            if ret != RET_OK:
                raise RuntimeError(f"[QUOTE] get_global_state failed, ret={df_state}")
            
            subscribe_quotes(SYMBOL)
            ret, df_current = quote_ctx.get_cur_kline(SYMBOL, 10, SubType.K_1M, AuType.QFQ)
            if ret != RET_OK:
                raise RuntimeError(f"[QUOTE] get_cur_kline failed, ret={df_current}")
            df_current = df_current.sort_values(by='time_key', ascending=False)  # Ensure data is sorted by time
            print(df_current['time_key'].iloc[0])

            # Exit condition for live mode
            if df_state['market_hk'] == 'CLOSED':
                print("LOOP EXITED: Market closed")
                quote_ctx.close()
                trade_ctx.close()
                break
            
            i = 1  # reset i to 1 to only take the second latest row for live mode

        row = df_current.iloc[[i]]
        output_params, prices = update_state_from_row(row, output_params, prices)
        output.append(output_params)

        end = time.time()
        print("Time taken (secs):", end-start)

        if live_mode:
            # Sleep until the start of the next minute
            now = datetime.now()
            sleep_seconds = 61 - now.second
            time.sleep(sleep_seconds)
            
            # Exit condition for live mode
            if df_state['market_hk'] == 'CLOSED':
                print("LOOP EXITED: Market closed")
                quote_ctx.close()
                trade_ctx.close()
                break
        else:
            i += 1 

    return output

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