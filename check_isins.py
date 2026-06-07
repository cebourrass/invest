import os
import sys

# Ensure the root directory is in the path so we can import backend
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from backend.database import SessionLocal, Holding
from backend.prices import resolve_isin_to_ticker, get_current_price

def check_db_isins():
    print("==================================================")
    print("   Verification des codes ISIN / Tickers en DB    ")
    print("==================================================")
    
    db = SessionLocal()
    try:
        # Get all holdings that have an ISIN or symbol
        holdings = db.query(Holding).all()
        if not holdings:
            print("Aucun placement trouve dans la base de donnees.")
            return

        print(f"\n{len(holdings)} placement(s) trouve(s) dans la base de donnees.\n")
        
        # Headers
        header_format = "{:<30} | {:<15} | {:<12} | {:<12} | {:<8} | {:<20}"
        print(header_format.format("Nom du Placement", "Code Saisi", "Ticker Yahoo", "Prix Actuel", "Mode DB", "Statut Yahoo"))
        print("-" * 105)

        for h in holdings:
            code = (h.isin_or_symbol or "").strip()
            mode = "Manuel" if h.is_manual else "Auto"
            
            if not code:
                print(header_format.format(h.name[:30], "(Vide)", "N/A", "N/A", mode, "Manuel (Saisie man.)"))
                continue
                
            # Try to resolve to Yahoo ticker
            ticker = resolve_isin_to_ticker(code)
            
            # Fetch price
            price = get_current_price(ticker)
            
            if price is not None:
                status = "VALIDE"
                price_str = f"{price:.2f} EUR"
            else:
                status = "INVALIDE (Yahoo hors service ou code incorrect)"
                price_str = "Echec"
                
            print(header_format.format(h.name[:30], code, ticker, price_str, mode, status))

        print("\n==================================================")
    finally:
        db.close()

if __name__ == "__main__":
    check_db_isins()
