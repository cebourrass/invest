import requests
import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Regex to check if a code looks like a standard ISIN (12 alphanumeric characters starting with 2 letters)
ISIN_REGEX = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")

def resolve_isin_to_ticker(isin: str) -> str:
    """
    Search Yahoo Finance for an ISIN and return the corresponding symbol/ticker.
    """
    isin = isin.strip().upper()
    if not ISIN_REGEX.match(isin):
        # If it doesn't look like an ISIN, assume it's already a ticker or ticker search query
        return isin

    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            quotes = data.get("quotes", [])
            if quotes:
                # Find the first quote that has a symbol
                symbol = quotes[0].get("symbol")
                if symbol:
                    logger.info(f"Resolved ISIN {isin} to Yahoo ticker: {symbol}")
                    return symbol
            logger.warning(f"No Yahoo Finance tickers found for ISIN {isin}")
        else:
            logger.error(f"Yahoo Search API returned status {response.status_code} for ISIN {isin}")
    except Exception as e:
        logger.error(f"Error resolving ISIN {isin}: {str(e)}")
    
    return isin

def get_current_price(ticker: str) -> float:
    """
    Fetch the regular market price for a given Yahoo Finance symbol.
    """
    ticker = ticker.strip().upper()
    if not ticker:
        return None

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            chart = data.get("chart", {})
            result = chart.get("result", [])
            if result and result[0]:
                meta = result[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                if price is not None:
                    # In some rare cases, currency might be in cents (e.g. GBp for UK stocks).
                    # But for French/European assets (CW8.PA, ALQ.PA, etc.), Yahoo uses standard EUR.
                    # We will assume Euros since user specified euro assets.
                    return float(price)
            logger.warning(f"Could not parse price from Yahoo Chart API for ticker {ticker}")
        else:
            logger.error(f"Yahoo Chart API returned status {response.status_code} for ticker {ticker}")
    except Exception as e:
        logger.error(f"Error fetching price for ticker {ticker}: {str(e)}")
    
    return None

def fetch_price_for_holding(isin_or_symbol: str, is_manual: bool, manual_price: float) -> float:
    """
    Main entrypoint to determine the price of an asset.
    Supports manual pricing and automatic resolution via ISIN/Ticker.
    """
    if is_manual:
        logger.info(f"Using manual price {manual_price} for asset.")
        return manual_price or 0.0

    if not isin_or_symbol:
        logger.warning("No ISIN or symbol provided for automatic tracking, falling back to manual price.")
        return manual_price or 0.0

    # Clean the code
    code = isin_or_symbol.strip()

    # Step 1: Resolve ISIN to Yahoo Ticker if it matches ISIN format
    ticker = resolve_isin_to_ticker(code)
    
    # Step 2: Fetch price for ticker
    price = get_current_price(ticker)
    
    if price is not None:
        return price

    # Step 3: Fallback to manual price if query failed
    logger.warning(f"Failed to fetch automatic price for {isin_or_symbol}. Falling back to manual price {manual_price}.")
    return manual_price or 0.0
