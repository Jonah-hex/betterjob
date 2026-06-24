# BetterJob — جلب آخر تحديث من GitHub (جهاز البيت أو الدوام)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> git pull" -ForegroundColor Cyan
git pull origin master

if (Test-Path ".venv\Scripts\pip.exe") {
    Write-Host "==> pip install -r requirements.txt" -ForegroundColor Cyan
    & .\.venv\Scripts\pip install -r requirements.txt -q
} else {
    Write-Host "!! لا توجد .venv — أنشئها: python -m venv .venv" -ForegroundColor Yellow
}

if (-not (Test-Path ".env")) {
    Write-Host "!! .env غير موجود — انسخه من الجهاز الآخر أو: copy .env.example .env" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "تمت المزامنة. شغّل:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\streamlit run app.py"
Write-Host ""
Write-Host "لتحديث Oracle (من جهاز البيت + SSH):" -ForegroundColor Cyan
Write-Host "  ssh -i your-key.pem ubuntu@207.127.102.118"
Write-Host "  cd ~/betterjob && ./deploy/oracle/update.sh"
