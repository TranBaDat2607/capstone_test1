# Build the thesis PDF locally with MiKTeX.
#   powershell -ExecutionPolicy Bypass -File build.ps1
# Runs the full pdflatex -> bibtex -> pdflatex -> pdflatex cycle that a document
# with a bibliography and cross-references needs. No compile-time limit, unlike
# Overleaf's free plan.

$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

$bin = "$env:LOCALAPPDATA\Programs\MiKTeX\miktex\bin\x64"
if (Test-Path $bin) { $env:PATH = "$bin;$env:PATH" }

$pdflatex = (Get-Command pdflatex -ErrorAction SilentlyContinue)
if (-not $pdflatex) { Write-Host "pdflatex not found on PATH"; exit 1 }

$flags = @('-interaction=nonstopmode', '-halt-on-error=0', '-file-line-error', 'main.tex')

Write-Host "`n=== pass 1/4: pdflatex ==="
& pdflatex @flags | Out-Null
Write-Host "=== pass 2/4: bibtex ==="
& bibtex main | Out-Null
Write-Host "=== pass 3/4: pdflatex ==="
& pdflatex @flags | Out-Null
Write-Host "=== pass 4/4: pdflatex ==="
& pdflatex @flags | Out-Null

if (Test-Path main.pdf) {
    $kb = [math]::Round((Get-Item main.pdf).Length / 1KB)
    Write-Host "`nmain.pdf written ($kb KB)"
} else {
    Write-Host "`nNo PDF produced - see main.log"
}

# Surface the things that actually matter, not the whole log.
Write-Host "`n--- errors ---"
Select-String -Path main.log -Pattern '^!|^.*:\d+: ' -ErrorAction SilentlyContinue |
    Select-Object -First 25 | ForEach-Object { $_.Line }
Write-Host "`n--- undefined references / citations ---"
Select-String -Path main.log -Pattern 'Citation .* undefined|Reference .* undefined|There were undefined' -ErrorAction SilentlyContinue |
    Select-Object -First 25 | ForEach-Object { $_.Line }
Write-Host "`n--- overfull boxes over 20pt (layout overflow) ---"
Select-String -Path main.log -Pattern 'Overfull \\hbox \((\d{2,})' -ErrorAction SilentlyContinue |
    Where-Object { [int]($_.Matches[0].Groups[1].Value) -ge 20 } |
    Select-Object -First 20 | ForEach-Object { $_.Line }
