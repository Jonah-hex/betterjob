# BetterJob - publish to new private GitHub repo
$ErrorActionPreference = "Stop"
$RepoName = "betterjob-survey-outreach"
$RepoUrl = "https://github.com/Jonah-hex/$RepoName.git"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Gh = if (Test-Path "$env:TEMP\gh-cli\bin\gh.exe") { "$env:TEMP\gh-cli\bin\gh.exe" } elseif (Get-Command gh -ErrorAction SilentlyContinue) { "gh" } else { $null }

Set-Location $Root

Write-Host "=== BetterJob GitHub Publish ===" -ForegroundColor Cyan
Write-Host "Target: $RepoUrl"

if (git status --porcelain) {
    Write-Host "Uncommitted changes - commit first." -ForegroundColor Yellow
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

if ($Gh) {
    $ghOk = $false
    try {
        & $Gh auth status *> $null
        $ghOk = ($LASTEXITCODE -eq 0)
    } catch { $ghOk = $false }
    if ($ghOk) {
        Write-Host "Creating repo via gh..." -ForegroundColor Green
        & $Gh repo create $RepoName --private --description "BetterJob survey outreach bot" --source $Root --remote origin --push
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Done: $RepoUrl" -ForegroundColor Green
            exit 0
        }
    }
}

if (Test-RepoReady) {
    Write-Host "Repo exists - pushing..." -ForegroundColor Green
    Push-ToOrigin
    Write-Host "Done: $RepoUrl" -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "Open GitHub and create a PRIVATE repo:" -ForegroundColor Yellow
Write-Host "  Name: $RepoName"
Write-Host "  Do NOT add README or .gitignore"
Write-Host ""
Start-Process "https://github.com/new?name=$RepoName&visibility=private&description=BetterJob+survey+outreach+bot"

Write-Host "Waiting up to 5 minutes..." -ForegroundColor Yellow
for ($i = 1; $i -le 100; $i++) {
    if (Test-RepoReady) {
        Push-ToOrigin
        Write-Host "Pushed: $RepoUrl" -ForegroundColor Green
        exit 0
    }
    Start-Sleep -Seconds 3
}

throw "Timeout. Sign in to GitHub, create the repo, then run: .\publish_to_github.ps1"
