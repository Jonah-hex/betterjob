# BetterJob — رفع المشروع إلى مستودع GitHub جديد
$ErrorActionPreference = "Stop"
$RepoName = "betterjob-survey-outreach"
$RepoUrl = "https://github.com/Jonah-hex/$RepoName.git"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

Set-Location $Root

Write-Host "=== BetterJob GitHub Publish ===" -ForegroundColor Cyan
Write-Host "المستودع المستهدف: $RepoUrl"

if (-not (git rev-parse --is-inside-work-tree 2>$null)) {
    throw "هذا المجلد ليس مستودع git"
}

$status = git status --porcelain
if ($status) {
    Write-Host "توجد تغييرات غير محفوظة — احفظها أولاً (git add / commit)" -ForegroundColor Yellow
    git status -sb
    exit 1
}

Write-Host ""
Write-Host "1) سيفتح المتصفح لإنشاء مستودع خاص جديد على GitHub." -ForegroundColor Yellow
Write-Host "   الاسم: $RepoName | الخصوصية: Private"
Write-Host "   لا تضف README أو .gitignore (المشروع جاهز محلياً)."
Write-Host ""
Start-Process "https://github.com/new?name=$RepoName&visibility=private&description=BetterJob+survey+outreach+bot"

Write-Host "2) انتظار إنشاء المستودع..." -ForegroundColor Yellow
$ready = $false
for ($i = 1; $i -le 120; $i++) {
    git ls-remote $RepoUrl 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 3
    if ($i % 10 -eq 0) { Write-Host "   ... ما زلنا ننتظر ($i)" }
}

if (-not $ready) {
    throw "انتهى الوقت — أنشئ المستودع يدوياً ثم أعد تشغيل السكربت"
}

Write-Host "3) ربط المستودع والدفع..." -ForegroundColor Green
if (git remote get-url origin 2>$null) {
    git remote set-url origin $RepoUrl
} else {
    git remote add origin $RepoUrl
}

git push -u origin master
Write-Host ""
Write-Host "تم الرفع بنجاح: $RepoUrl" -ForegroundColor Green
