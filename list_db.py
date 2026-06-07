import os
import sys

# Ensure parent directory is in the path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from backend.database import SessionLocal, Holding, Account

def list_db():
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        holdings = db.query(Holding).all()
        
        print("=== COMPTES SUPPORTS ===")
        if not accounts:
            print("Aucun compte support.")
        for a in accounts:
            print(f"ID: {a.id} | Nom: {a.name} | Type: {a.type}")
            
        print("\n=== PLACEMENTS (HOLDINGS) ===")
        if not holdings:
            print("Aucun placement.")
        for h in holdings:
            acc_name = next((a.name for a in accounts if a.id == h.account_id), "Inconnu")
            print(f"ID: {h.id} | Compte: {acc_name} | Nom: {h.name} | ISIN/Ticker: {h.isin_or_symbol or 'Manuel'} | Qty: {h.quantity} | Prix d'achat: {h.buy_price} EUR")
    finally:
        db.close()

if __name__ == "__main__":
    list_db()
