# Deploy Script for Nano Banana Bot Web App
# Run this from the project root directory

Write-Host ">>> Starting Nano Banana Deployment..." -ForegroundColor Yellow

# 1. Build the Web App inside the container
Write-Host ">>> Building Web App..." -ForegroundColor Cyan
docker exec nano_banana_bot-webapp-1 npm run build

if ($LASTEXITCODE -ne 0) {
    Write-Host "!!! Build failed. Check Docker logs." -ForegroundColor Red
    exit
}

# 2. Prepare the dist folder
Set-Location "web-app/dist"
Write-Host ">>> Packaging..." -ForegroundColor Cyan

# Remove old git info to start fresh
if (Test-Path .git) {
    Remove-Item .git -Recurse -Force -ErrorAction SilentlyContinue
}

git init
git add -A
git commit -m "Deploy update"

# 3. Push to GitHub Pages
Write-Host ">>> Pushing to GitHub Pages..." -ForegroundColor Cyan
git push -f https://github.com/DNStrokin/nano_banana_bot.git master:gh-pages

if ($LASTEXITCODE -eq 0) {
    Write-Host ">>> Successfully deployed!" -ForegroundColor Green
    Write-Host ">>> Check verification at: https://DNStrokin.github.io/nano_banana_bot/" -ForegroundColor Gray
}
else {
    Write-Host "!!! Push failed." -ForegroundColor Red
}

# Return to root
Set-Location ../..
