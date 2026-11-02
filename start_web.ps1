# 小波 · 本地 Web 工作台启动脚本
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$Port = if ($env:DY_WEB_PORT) { $env:DY_WEB_PORT } else { "19527" }
$Url = "http://127.0.0.1:$Port/"

Write-Host ""
Write-Host " ========================================" -ForegroundColor White
Write-Host "  小波 · 抖音采集工作台" -ForegroundColor White
Write-Host "  $Url" -ForegroundColor White
Write-Host " ========================================" -ForegroundColor White
Write-Host ""

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[错误] 未找到 python，请先安装并加入 PATH。" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "[提示] 已从 .env.example 生成 .env，请到「会话配置」粘贴 Cookie。" -ForegroundColor Yellow
    } else {
        Write-Host "[警告] 未找到 .env，启动后请在页面里配置 Cookie。" -ForegroundColor Yellow
    }
    Write-Host ""
}

$owners = Get-NetTCPConnection -LocalPort ([int]$Port) -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $owners) {
    Write-Host "[提示] 端口 $Port 已被占用，结束 PID $procId ..." -ForegroundColor Yellow
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}

Write-Host "[启动] python -m webapp.server" -ForegroundColor Green
Write-Host "[提示] 按 Ctrl+C 可停止服务" -ForegroundColor DarkGray
Write-Host ""

Start-Process $Url
python -m webapp.server
