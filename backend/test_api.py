import sys
import os

# Add parent directory to path to import backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.prices import resolve_isin_to_ticker, get_current_price, fetch_price_for_holding

def run_tests():
    print("=== Testing Ticker Resolution by ISIN ===")
    
    # 1. Test CW8 (Amundi MSCI World ETF) - LU1681043599
    cw8_isin = "LU1681043599"
    cw8_ticker = resolve_isin_to_ticker(cw8_isin)
    print(f"ISIN: {cw8_isin} -> Resolved Ticker: {cw8_ticker}")
    assert cw8_ticker == "CW8.PA", f"Expected CW8.PA, got {cw8_ticker}"
    
    # 2. Test LVMH - FR0000121014
    lvmh_isin = "FR0000121014"
    lvmh_ticker = resolve_isin_to_ticker(lvmh_isin)
    print(f"ISIN: {lvmh_isin} -> Resolved Ticker: {lvmh_ticker}")
    assert "MC.PA" in lvmh_ticker or lvmh_ticker != lvmh_isin, f"Failed resolving LVMH, got {lvmh_ticker}"

    print("\n=== Testing Live Price Fetching ===")
    # 1. Fetch CW8 price
    cw8_price = get_current_price(cw8_ticker)
    print(f"Ticker: {cw8_ticker} -> Current Price: {cw8_price} EUR")
    assert cw8_price is not None and cw8_price > 0, "Failed to get valid CW8 price"

    # 2. Fetch manual asset holding
    manual_price = fetch_price_for_holding("", is_manual=True, manual_price=123.45)
    print(f"Manual Asset -> Price: {manual_price} EUR")
    assert manual_price == 123.45, "Failed manual price fallback"
    
    print("\n=== All Tests Passed Successfully! ===")

if __name__ == "__main__":
    run_tests()
