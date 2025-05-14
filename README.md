magin.py ---- margin ratio (no fastapi )
margin ratio it only gives access of rest api 
position.py ---- positional risk (no fastapi)
positional risk it only gives access of rest api 
liquidation.py ---- liquidation 
liquidation using the websocket 
"margin-ratio_positional-risk_liquidation.py ---- combined functions with rotation of listen key 
functions_fastapi.py ---- functions using fast api 

local host url 

http://127.0.0.1:8000/margin_ratio

http://127.0.0.1:8000/position_risk?symbol=BTCUSDT 

(as we only have balance in this symbol)

http://127.0.0.1:8000/liquidation
