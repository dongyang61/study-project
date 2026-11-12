<#
  启动 MCP 依赖：宠物医院 REST(8080)、PetHospital MCP(8090)、AnythingLLM MCP(8765)
  用法：powershell -ExecutionPolicy Bypass -File .\start-mcp.ps1
#>
$ErrorActionPreference = 'Stop'
$Office = Split-Path -Parent $MyInvocation.MyCommand.Path
$PetExe = 'D:\study\study one-pethospital\pethospital.exe'
$PetDir = Split-Path -Parent $PetExe
$AnythingDir = 'D:\study\LLM\anytingLLM-MCP'

function Test-Port([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1', $Port); $true }
    catch { $false }
    finally { $client.Dispose() }
}

function Start-Local([string]$Name, [int]$Port, [scriptblock]$Starter) {
    if (Test-Port $Port) { Write-Host "[skip] $Name 已在 $Port 监听"; return }
    & $Starter
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-Port $Port) { Write-Host "[ok] $Name -> $Port"; return }
    }
    Write-Warning "[fail] $Name 未在 $Port 就绪"
}

Start-Local 'pethospital.exe' 8080 {
    Start-Process -FilePath $PetExe -WorkingDirectory $PetDir -ArgumentList '-no-color' -WindowStyle Hidden
}

Start-Local 'PetHospital MCP' 8090 {
    Start-Process -FilePath 'python' -ArgumentList @((Join-Path $Office 'pethospital-mcp\server.py')) -WorkingDirectory $Office -WindowStyle Hidden
}

Start-Local 'AnythingLLM MCP' 8765 {
    Start-Process -FilePath 'python' -ArgumentList @((Join-Path $AnythingDir 'server.py')) -WorkingDirectory $AnythingDir -WindowStyle Hidden
}

Write-Host ''
Write-Host 'MCP 端点：'
Write-Host '  http://127.0.0.1:8090/mcp  (PetHospitalMCP)'
Write-Host '  http://127.0.0.1:8765/mcp  (AnythingLLMMCP)'
