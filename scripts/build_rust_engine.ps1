<#
.SYNOPSIS
    Builds the native EvoScrapper Rust streaming micro-daemon (evostreamer-rs).
.DESCRIPTION
    Checks for the Rust toolchain, compiles streamer-rs in release mode,
    and stages the optimized binary for EvoScrapper.
#>

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path "$scriptDir\.."
$streamerRsDir = Join-Path $repoRoot "streamer-rs"
$binDir = Join-Path $repoRoot "bin"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  EvoScrapper Native Rust Streaming Engine Builder v2.7.0" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Locate cargo / rustc
$cargoPath = Get-Command cargo -ErrorAction SilentlyContinue
if (-not $cargoPath) {
    $userCargo = Join-Path $env:USERPROFILE ".cargo\bin\cargo.exe"
    if (Test-Path $userCargo) {
        $env:PATH = "$env:USERPROFILE\.cargo\bin;" + $env:PATH
        $cargoPath = Get-Command cargo -ErrorAction SilentlyContinue
    }
}

if (-not $cargoPath) {
    Write-Host "[!] Rust toolchain (cargo/rustc) not found in PATH." -ForegroundColor Yellow
    Write-Host "    Install Rust via winget:" -ForegroundColor Yellow
    Write-Host "    winget install --id Rustlang.Rustup" -ForegroundColor White
    Write-Host "    Or visit: https://rustup.rs" -ForegroundColor White
    exit 1
}

Write-Host "[+] Found Cargo: $(cargo --version)" -ForegroundColor Green

# 2. Build streamer-rs in release mode
Set-Location $streamerRsDir
Write-Host "[*] Compiling evostreamer-rs (--release)..." -ForegroundColor Cyan
cargo build --release

$builtBinary = Join-Path $streamerRsDir "target\release\evostreamer.exe"
if (-not (Test-Path $builtBinary)) {
    $builtBinary = Join-Path $streamerRsDir "target\release\evostreamer"
}

if (-not (Test-Path $builtBinary)) {
    Write-Host "[!] Build failed: binary not found at $builtBinary" -ForegroundColor Red
    exit 1
}

# 3. Stage into bin directory
if (-not (Test-Path $binDir)) {
    New-Item -ItemType Directory -Path $binDir | Out-Null
}

Copy-Item $builtBinary -Destination $binDir -Force
Write-Host "[+] Successfully built & staged native Rust streaming engine!" -ForegroundColor Green
Write-Host "    Binary: $builtBinary" -ForegroundColor White
Set-Location $repoRoot
