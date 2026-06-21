@echo off
cd /d "%~dp0"
echo Starting BetterJob Pro...
streamlit run app_pro.py --server.port 8502
