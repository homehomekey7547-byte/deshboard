Write-Host '正在從 Notion 擷取最新資料並更新儀表板...'
$py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'py' }
$script = Join-Path $PSScriptRoot 'build_jun_v2.py'
# Ensure requests is installed
& $py -m pip install requests -q
if ($LASTEXITCODE -ne 0) { Write-Host 'pip install requests 失敗'; pause; exit }
& $py $script
if ($LASTEXITCODE -ne 0) {
    Write-Host '更新失敗，請確認 Python 與 Notion 連線正常。'
    pause
    exit
}
Write-Host '更新完成！'

# ── 上傳至 Netlify ──
$cfg = Join-Path $PSScriptRoot '.netlify_deploy_config'
if (Test-Path $cfg) {
    $cfgLines = Get-Content $cfg
    $token = ($cfgLines | Where-Object { $_ -match '^TOKEN=' } | ForEach-Object { $_ -replace '^TOKEN=', '' })
    $siteId = ($cfgLines | Where-Object { $_ -match '^SITE_ID=' } | ForEach-Object { $_ -replace '^SITE_ID=', '' })
    $src = Join-Path $PSScriptRoot 'index.html'
    $tmpDir = Join-Path $env:TEMP "netlify_site_$(Get-Random)"
    New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
    Copy-Item $src (Join-Path $tmpDir 'index.html') -Force
    $headers = '/* Content-Type: text/html; charset=utf-8'
    Set-Content -Path (Join-Path $tmpDir '_headers') -Value $headers -Encoding UTF8
    $zip = Join-Path $env:TEMP 'netlify_deploy.zip'
    Compress-Archive -Path "$tmpDir\*" -DestinationPath $zip -Force
    Remove-Item $tmpDir -Recurse -Force
    $resp = curl.exe -s -X POST -H "Content-Type: application/zip" -H "Authorization: Bearer $token" --data-binary "@$zip" "https://api.netlify.com/api/v1/sites/$siteId/deploys" 2>&1
    Remove-Item $zip -Force
    Write-Host "已上傳至 https://legendary-bombolone-78a57c.netlify.app"
} else {
    Write-Host "找不到 .netlify_deploy_config，跳過上傳"
}

$html = Join-Path $PSScriptRoot 'index.html'
Start-Process $html
pause