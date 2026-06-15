# BetterJob — رفع المشروع إلى مستودع GitHub جديد
$ErrorActionPreference = "Stop"
$RepoName = "betterjob-survey-outreach"
$RepoUrl = "https://github.com/Jonah-hex/$RepoName.git"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Gh = if (Test-Path "$env:TEMP\gh-cli\bin\gh.exe") { "$env:TEMP\gh-cli\bin\gh.exe" } elseif (Get-Command gh -ErrorAction SilentlyContinue) { "gh" } else { $null }

Set-Location $Root

Write-Host "=== BetterJob GitHub Publish ===" -ForegroundColor Cyan
Write-Host "المستودع: $RepoUrl"

if (git status --porcelain) {
    Write-Host "احفظ التغييرات أولاً: git add -A && git commit -m '...'" -ForegroundColor Yellow
    git status -sb
    exit 1
}

function Test-RepoReady {
    git ls-remote $RepoUrl 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Push-ToOrigin {
    if (git remote get-url origin 2>$null) { git remote set-url origin $RepoUrl }
    else { git remote add origin $RepoUrl }
    git push -u origin master
}

# محاولة 1: gh مسجّل دخول
if ($Gh) {
    & $Gh auth status 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "إنشاء المستودع عبر gh..." -ForegroundColor Green
        & $Gh repo create $RepoName --private --description "BetterJob survey outreach bot" --source $Root --remote origin --push
        if ($LASTEXITCODE -eq 0) { Write-Host "تم: $RepoUrl" -ForegroundColor Green; exit 0 }
    }
}

# محاولة 2: المستودع موجود مسبقاً
if (Test-RepoReady) {
    Write-Host "المستودع موجود — رفع الكود..." -ForegroundColor Green
    Push-ToOrigin
    Write-Host "تم: $RepoUrl" -ForegroundColor Green
    exit 0
}

# محاولة 3: فتح المتصفح وانتظار الإنشاء اليدوي
Write-Host ""
Write-Host "افتح GitHub وأنشئ مستودعاً خاصاً:" -ForegroundColor Yellow
Write-Host "  الاسم: $RepoName"
Write-Host "  بدون README / .gitignore"
Write-Host ""
Start-Process "https://github.com/new?name=$RepoName&visibility=private&description=BetterJob+survey+outreach+bot"

Write-Host "انتظار إنشاء المستودع (حتى 5 دقائق)..." -ForegroundColor Yellow
for ($i = 1; $i -le 100; $i++) {
    if (Test-RepoReady) {
        Push-ToOrigin
        Write-Host "تم الرفع: $RepoUrl" -ForegroundColor Green
        exit 0
    }
    Start-Sleep -Seconds 3
}

throw "انتهى الوقت. سجّل دخول GitHub ثم أعد تشغيل: .\publish_to_github.ps1"
