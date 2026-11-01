#!/usr/bin/env bash
# scripts/build_rust_engine.sh — Builds evostreamer-rs native daemon on POSIX systems
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STREAMER_RS_DIR="$REPO_ROOT/streamer-rs"
BIN_DIR="$REPO_ROOT/bin"

echo "=========================================================="
echo "  EvoScrapper Native Rust Streaming Engine Builder v2.7.0"
echo "=========================================================="

if ! command -v cargo &> /dev/null; then
    if [ -f "$HOME/.cargo/bin/cargo" ]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    else
        echo "[!] Rust toolchain (cargo) not found. Install from https://rustup.rs"
        exit 1
    fi
fi

echo "[+] Found Cargo: $(cargo --version)"
cd "$STREAMER_RS_DIR"
echo "[*] Compiling evostreamer-rs (--release)..."
cargo build --release

BUILT_BIN="$STREAMER_RS_DIR/target/release/evostreamer"
if [ ! -f "$BUILT_BIN" ]; then
    echo "[!] Build failed: binary not found at $BUILT_BIN"
    exit 1
fi

mkdir -p "$BIN_DIR"
cp -f "$BUILT_BIN" "$BIN_DIR/"
echo "[+] Successfully built & staged native Rust streaming engine!"
echo "    Binary: $BIN_DIR/evostreamer"
