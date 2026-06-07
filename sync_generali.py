import os
import sys
import re
import getpass

# Ensure parent directory is in the path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Erreur : La bibliothèque 'playwright' n'est pas installée dans cet environnement.")
    print("Veuillez installer playwright :")
    print("  conda install -n dev_env -c conda-forge playwright")
    print("  ou : conda run -n dev_env pip install playwright")
    sys.exit(1)

from backend.database import SessionLocal, Account, Holding

def select_account(db):
    accounts = db.query(Account).all()
    if not accounts:
        print("Aucun compte support trouvé en base. Créez d'abord un compte support via l'interface.")
        sys.exit(1)
        
    print("\nComptes supports disponibles :")
    for i, acc in enumerate(accounts):
        print(f"  {i + 1}. {acc.name} ({acc.type})")
        
    while True:
        try:
            choice = int(input("\nSélectionnez le numéro du compte Generali à synchroniser : "))
            if 1 <= choice <= len(accounts):
                return accounts[choice - 1]
            print("Choix invalide.")
        except ValueError:
            print("Veuillez entrer un nombre.")

def clean_french_number(text):
    if not text:
        return None
    # Remove spaces, non-breaking spaces, currency symbols
    cleaned = text.replace('\xa0', '').replace(' ', '').replace('€', '').replace('%', '').strip()
    # Replace comma with dot for float conversion
    cleaned = cleaned.replace(',', '.')
    # Extract the decimal number structure
    match = re.search(r'-?\d+(?:\.\d+)?', cleaned)
    if match:
        return float(match.group(0))
    return None

def run_extraction():
    db = SessionLocal()
    account = select_account(db)
    
    print("\n--- Démarrage du navigateur ---")
    print("Lancement de Chromium en mode visible (Headed) pour vous permettre de vous connecter en toute sécurité...")
    
    p = sync_playwright().start()
    
    # Try launching chromium, instruct the user to install browsers if needed
    try:
        browser = p.chromium.launch(headless=False)
    except Exception as e:
        print("\nErreur de lancement de Playwright. Les navigateurs ne sont peut-être pas installés.")
        print("Tentative d'installation des navigateurs Chromium...")
        try:
            import subprocess
            subprocess.run(["conda", "run", "-n", "dev_env", "playwright", "install", "chromium"], check=True)
            browser = p.chromium.launch(headless=False)
        except Exception as install_err:
            print(f"Échec de l'installation automatique : {install_err}")
            print("Veuillez lancer dans votre terminal : playwright install")
            p.stop()
            db.close()
            sys.exit(1)
            
    page = browser.new_page()
    page.goto("https://monespace.generali.fr/")
    
    print("\n=============================================================")
    print(" INSTRUCTIONS :")
    print(" 1. Connectez-vous avec vos identifiants sur la fenêtre Generali.")
    print(" 2. Gérez la double authentification (2FA) si demandée.")
    print(" 3. Naviguez vers la page contenant le tableau de vos placements.")
    print(" 4. Une fois les lignes de placements (codes ISIN) affichées à l'écran,")
    print("    revenez sur ce terminal et appuyez sur ENTRÉE.")
    print("=============================================================")
    
    input("\nAppuyez sur ENTRÉE une fois que vous êtes sur la page des placements...")
    
    print("\nExtraction des placements en cours...")
    
    # JS code to extract elements containing ISINs and their parent row contents
    extract_js = """
    () => {
        const results = [];
        const isinRegex = /[A-Z]{2}[A-Z0-9]{9}\\d/g;
        const elements = Array.from(document.querySelectorAll('body *'));
        
        // Find leaf elements containing ISINs
        const isinNodes = elements.filter(el => {
            if (el.children.length > 0) return false;
            const text = el.textContent.trim();
            const matches = text.match(isinRegex);
            return matches && matches.length === 1;
        });

        for (const node of isinNodes) {
            const isin = node.textContent.trim().match(isinRegex)[0];
            
            // Climb up to find row container
            let row = node.parentElement;
            let foundRow = null;
            for (let i = 0; i < 8; i++) {
                if (!row) break;
                const tagName = row.tagName.toLowerCase();
                if (tagName === 'tr' || row.classList.contains('row') || row.getAttribute('role') === 'row' || row.classList.contains('line') || row.tagName.toLowerCase() === 'li') {
                    foundRow = row;
                    break;
                }
                row = row.parentElement;
            }
            if (!foundRow) {
                foundRow = node.parentElement;
            }
            
            // Collect text segments from children
            const segments = [];
            function collect(el) {
                if (el.children.length === 0) {
                    const txt = el.textContent.trim();
                    if (txt) segments.push(txt);
                } else {
                    for (const child of el.children) {
                        collect(child);
                    }
                }
            }
            collect(foundRow);
            
            results.push({
                isin: isin,
                segments: segments
            });
        }
        return results;
    }
    """
    
    try:
        extracted = page.evaluate(extract_js)
    except Exception as e:
        print(f"Erreur lors de l'exécution du script d'extraction : {e}")
        browser.close()
        p.stop()
        db.close()
        sys.exit(1)
        
    if not extracted:
        print("\nAucun code ISIN n'a été détecté sur la page active.")
        print("Assurez-vous que la liste des supports est bien affichée sur la page courante.")
        browser.close()
        p.stop()
        db.close()
        sys.exit(1)
        
    print(f"\n{len(extracted)} ligne(s) de placement détectée(s) avec des codes ISIN.")
    print("-" * 80)
    
    detected_holdings = []
    
    for idx, item in enumerate(extracted):
        isin = item['isin']
        segments = item['segments']
        
        # Parse placement name: longest string or first non-numerical string
        clean_segs = [s.strip() for s in segments if s.strip() and isin not in s]
        name = "Placement Inconnu"
        for s in clean_segs:
            has_letters = any(c.isalpha() for c in s)
            if has_letters and len(s) > 4 and not s.endswith('%') and not s.startswith('%'):
                name = s
                break
                
        # Parse numerical values
        numbers = []
        for s in clean_segs:
            val = clean_french_number(s)
            if val is not None:
                numbers.append(val)
                
        # Heuristics:
        # Quantity is usually a smaller decimal float (e.g. 15.234)
        # Current price or value are larger floats (e.g. 150.23 or 2500.00)
        # Generali tables often display: [Name, ISIN, Quantity, Buy Price (or Cost), Current Price (or Value)]
        quantity = 0.0
        current_price = 0.0
        
        # Try to identify quantity: usually the first decimal float or a number with 4+ decimal places
        # For security, let's list the values found and let the user see them
        if numbers:
            # Sort numbers by size to separate quantities from values
            # Typically, quantity < 10000 (often fractional like 14.5381)
            # Valorisation is often larger
            # We will use the first float in the list as quantity, and the last as price as a default guess
            quantity = numbers[0] if len(numbers) > 0 else 0.0
            if len(numbers) > 1:
                current_price = numbers[-1] # guess current price
                
        print(f"Ligne #{idx + 1} :")
        print(f"  Code ISIN   : {isin}")
        print(f"  Nom estimé  : {name}")
        print(f"  Valeurs num : {numbers}")
        print(f"  -> Quantité détectée : {quantity}")
        print(f"  -> Cours détecté     : {current_price}")
        print("-" * 80)
        
        detected_holdings.append({
            'name': name,
            'isin': isin,
            'quantity': quantity,
            'price': current_price
        })

    confirm = input("\nVoulez-vous intégrer ces placements dans votre base de données ? (o/n) : ").strip().lower()
    if confirm == 'o':
        updated_count = 0
        created_count = 0
        
        for h in detected_holdings:
            isin_code = h['isin']
            # Search if holding already exists for this account
            existing = db.query(Holding).filter(
                Holding.account_id == account.id,
                Holding.isin_or_symbol == isin_code
            ).first()
            
            if existing:
                # Update quantity and current price
                existing.quantity = h['quantity']
                if h['price'] > 0:
                    existing.manual_price = h['price']
                updated_count += 1
            else:
                # Create a new holding
                # Default buy price to 1.0 or current price if not known
                buy_price = h['price'] if h['price'] > 0 else 1.0
                new_h = Holding(
                    account_id=account.id,
                    name=h['name'],
                    isin_or_symbol=isin_code,
                    quantity=h['quantity'],
                    buy_price=buy_price,
                    is_manual=False,
                    manual_price=h['price'],
                    category="Autre"
                )
                db.add(new_h)
                created_count += 1
                
        db.commit()
        print(f"\nSynchronisation terminée avec succès !")
        print(f"  - Placements mis à jour : {updated_count}")
        print(f"  - Nouveaux placements créés : {created_count}")
    else:
        print("\nSynchronisation annulée.")

    browser.close()
    p.stop()
    db.close()

if __name__ == "__main__":
    try:
        run_extraction()
    except KeyboardInterrupt:
        print("\nInterrompu par l'utilisateur.")
        sys.exit(0)
