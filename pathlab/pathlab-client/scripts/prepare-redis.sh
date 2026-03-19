#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

mkdir -p "$ROOT_DIR/resources"

PLATFORM="$(uname -s)"
case "$PLATFORM" in
    MINGW*|MSYS*|CYGWIN*)
        IS_WINDOWS=1
        DEST="$ROOT_DIR/resources/redis-server.exe"
        ;;
    *)
        IS_WINDOWS=0
        DEST="$ROOT_DIR/resources/redis-server"
        ;;
esac

if [ -f "$DEST" ]; then
    echo "[prepare-redis] Already exists: $DEST"
    exit 0
fi

if [ "$IS_WINDOWS" = "1" ]; then
    echo "[prepare-redis] Windows detected — downloading Microsoft Garnet (Redis-compatible)..."

    TMP_DIR="$(mktemp -d)"
    cleanup() { rm -rf "$TMP_DIR"; }
    trap cleanup EXIT

    GARNET_VERSION="${GARNET_VERSION:-}"
    if [ -z "$GARNET_VERSION" ]; then
        GARNET_VERSION=$(curl -sSL "https://api.github.com/repos/microsoft/garnet/releases/latest" \
            | grep '"tag_name"' | sed 's/.*"v\([^"]*\)".*/\1/' 2>/dev/null || true)
    fi
    if [ -z "$GARNET_VERSION" ]; then
        GARNET_VERSION="1.1.1"
    fi

    echo "[prepare-redis] Garnet version: ${GARNET_VERSION}"
    GARNET_URL="https://github.com/microsoft/garnet/releases/download/v${GARNET_VERSION}/garnet-win-x64.zip"
    echo "[prepare-redis] Downloading: $GARNET_URL"
    curl -sSL "$GARNET_URL" -o "$TMP_DIR/garnet.zip"

    unzip -q "$TMP_DIR/garnet.zip" -d "$TMP_DIR/garnet"

    GARNET_EXE="$(find "$TMP_DIR/garnet" -name "*.exe" | head -1)"
    if [ -z "$GARNET_EXE" ]; then
        echo "[prepare-redis] ERROR: No .exe found in Garnet zip"
        exit 1
    fi

    cp "$GARNET_EXE" "$DEST"
    chmod 755 "$DEST"
    echo "[prepare-redis] Garnet placed at: $DEST"
    exit 0
fi

if command -v redis-server &>/dev/null; then
    SRC="$(which redis-server)"
    echo "[prepare-redis] Copying from system: $SRC -> $DEST"
    cp "$SRC" "$DEST"
    chmod 755 "$DEST"
    echo "[prepare-redis] Done."
    exit 0
fi

for candidate in \
    /usr/bin/redis-server \
    /usr/local/bin/redis-server \
    /opt/homebrew/bin/redis-server \
    /opt/homebrew/opt/redis/bin/redis-server; do
    if [ -f "$candidate" ]; then
        echo "[prepare-redis] Copying from: $candidate -> $DEST"
        cp "$candidate" "$DEST"
        chmod 755 "$DEST"
        echo "[prepare-redis] Done."
        exit 0
    fi
done

echo "[prepare-redis] redis-server not found, compiling from source (requires build-essential)..."
REDIS_VER="7.4.2"
TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

curl -sSL "https://download.redis.io/releases/redis-${REDIS_VER}.tar.gz" -o "$TMP_DIR/redis.tar.gz"
tar -xzf "$TMP_DIR/redis.tar.gz" -C "$TMP_DIR"
make -C "$TMP_DIR/redis-${REDIS_VER}" -j"$(nproc)" MALLOC=libc BUILD_TLS=no

cp "$TMP_DIR/redis-${REDIS_VER}/src/redis-server" "$DEST"
chmod 755 "$DEST"
echo "[prepare-redis] Compiled and placed at: $DEST"
