import aiohttp
import logging

BINANCE_API_URL = "https://api.binance.com/api/v3/ticker/price"

async def get_current_price(pair: str):
    """
    Fetches the current price of a trading pair from the Binance API.
    Returns None if the pair is not found or an error occurs.
    """
    # Binance pairs are usually uppercase without slashes, e.g., BTCUSDT
    pair = pair.replace("/", "").replace("-", "").replace("_", "").upper()
    
    # Auto-append USDT if user just typed the coin (e.g., "HBAR" -> "HBARUSDT")
    if not pair.endswith("USDT") and not pair.endswith("USD") and not pair.endswith("BTC"):
        pair += "USDT"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(BINANCE_API_URL, params={"symbol": pair}) as response:
                if response.status == 200:
                    data = await response.json()
                    return float(data['price'])
                else:
                    logging.error(f"Binance API error for {pair}: {response.status}")
                    return None
        except Exception as e:
            logging.error(f"Exception fetching price for {pair}: {e}")
            return None
