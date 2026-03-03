import time
from moomoo import *

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
    strategy = Strategy()

    # --- Quote context for K-line ---
    quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    quote_ctx.set_handler(KlineHandler(strategy))
    quote_ctx.subscribe(['US.AAPL'], [SubType.K_1M])  # 1-minute candles

    # --- Trade context for order updates ---
    trade_ctx = OpenSecTradeContext(host='127.0.0.1', port=11111)
    trade_ctx.set_handler(OrderHandler(strategy))

    print("Live system started. Waiting for new candles and order updates...")

    try:
        while True:
            time.sleep(1)  # Nothing else needed, all handled in callbacks
    except KeyboardInterrupt:
        print("Shutting down...")
        quote_ctx.close()
        trade_ctx.close()