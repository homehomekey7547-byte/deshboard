Write-Host '=== 行動量儀表板 更新 + 部署工具 ===' -ForegroundColor Cyan
Write-Host ''

# ── 1. 取得 Notion 憑證 ──
$envFile = Join-Path $PSScriptRoot '.env'
if (-not $env:NOTION_TOKEN) {
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^NOTION_TOKEN=(.+)') { $env:NOTION_TOKEN = $Matches[1] }
            if ($_ -match '^DB_ID=(.+)') { $env:DB_ID = $Matches[1] }
        }
        Write-Host '已從 .env 載入 Notion 憑證' -ForegroundColor Green
    } else {
        $env:NOTION_TOKEN = Read-Host '請輸入 Notion Token'
        $env:DB_ID = Read-Host '請輸入 DB_ID'
    }
}
if (-not $env:NOTION_TOKEN -or -not $env:DB_ID) {
    Write-Host '錯誤：缺少 Notion 憑證，無法更新' -ForegroundColor Red
    pause; exit
}

# ── 2. 執行 Build ──
Write-Host '正在從 Notion 擷取最新資料並更新儀表板...' -ForegroundColor Yellow
$py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'py' }
& $py -m pip install requests -q
$script = Join-Path $PSScriptRoot 'build_jun_v2.py'
& $py $script
if ($LASTEXITCODE -ne 0) {
    Write-Host '❌ 更新失敗，請確認 Python 與 Notion 連線正常。' -ForegroundColor Red
    pause; exit
}
Write-Host '✅ 更新完成！' -ForegroundColor Green

# ── 3. Commit + Push 到 GitHub Pages ──
Write-Host '正在上傳至 GitHub Pages...' -ForegroundColor Yellow
Set-Location $PSScriptRoot
git add -A
git commit -m "更新資料 $(Get-Date -Format 'yyyy/MM/dd HH:mm')"
if ($LASTEXITCODE -eq 0) {
    git push
    if ($LASTEXITCODE -eq 0) {
        Write-Host '✅ 已上傳至 https://homehomekey7547-byte.github.io/deshboard/' -ForegroundColor Green
        Write-Host '   等待 1-2 分鐘後重新整理即可看到最新內容' -ForegroundColor Green
    } else {
        Write-Host '❌ push 失敗，請檢查 GitHub 連線' -ForegroundColor Red
    }
} else {
    Write-Host 'ℹ️  沒有新的變更需要上傳' -ForegroundColor Cyan
}

# ── 4. 開啟本機檔案 ──
$html = Join-Path $PSScriptRoot 'index.html'
Start-Process $html
pause