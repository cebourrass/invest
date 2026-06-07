@echo off
echo ===================================================
echo   Demarrage de AuraVest (Suivi de Portefeuille)
echo ===================================================
echo.
echo Ouverture de l'application sur : http://127.0.0.1:8000
echo.
conda run --no-capture-output -n dev_env uvicorn backend.main:app --reload
pause
