import pandas as pd
from moomoo import *

start_date = '2019-09-11'
end_date = '2019-09-18'
SYMBOL = "HK.00700"
# SYMBOL = "US.AAPL"
quote_ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
ret, data, page_req_key = quote_ctx.request_history_kline(
    code=SYMBOL, 
    start=start_date, 
    end=end_date, 
    ktype=KLType.K_DAY) # 5 per page, request the first page

if ret != RET_OK:
    print("Error requesting History Klines: ", data)

try:
    df = pd.DataFrame(data)
    df.to_csv(f'data_from_{start_date}_to_{end_date}')
    print("Successfully exported historical candlestick data")
finally:
    quote_ctx.close()