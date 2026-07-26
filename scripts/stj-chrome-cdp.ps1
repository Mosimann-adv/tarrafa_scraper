# Abre Google Chrome com remote debugging para tarrafa stj --cdp
# Uso:
#   .\scripts\stj-chrome-cdp.ps1
#   # em outro terminal:
#   tarrafa stj --warmup --cdp http://127.0.0.1:9222 --save-storage .\stj_storage.json
#   tarrafa stj --cdp http://127.0.0.1:9222 --urls-file seeds.txt --out-dir .\pdfs --out stj.json

$ErrorActionPreference = "Stop"
$port = 9222
$profile = Join-Path $env:USERPROFILE ".tarrafa\chrome-stj-profile"
New-Item -ItemType Directory -Force -Path $profile | Out-Null

$candidates = @(
  "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
  Write-Error "Google Chrome não encontrado. Instale o Chrome ou edite este script para o caminho do msedge.exe"
}

Write-Host "Chrome: $chrome"
Write-Host "Perfil: $profile"
Write-Host "CDP:    http://127.0.0.1:$port"
Write-Host ""
Write-Host "1) Na janela do Chrome, abra https://scon.stj.jus.br/SCON/ e resolva o captcha se aparecer."
Write-Host "2) Em outro terminal, rode tarrafa stj --cdp http://127.0.0.1:$port ..."
Write-Host ""

# Feche instâncias Chrome que usem ESTE perfil (não mexe no Chrome do dia a dia)
& $chrome `
  --remote-debugging-port=$port `
  --user-data-dir=$profile `
  --no-first-run `
  --no-default-browser-check `
  "https://scon.stj.jus.br/SCON/"
