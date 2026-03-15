#!/bin/bash
# prepare-redis.sh — 将 redis-server 二进制拷贝到 resources/
# 打包 Electron 桌面版前必须先执行此脚本。
# 产出：resources/redis-server（由 electron-builder extraResources 打入安装包）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DEST="$ROOT_DIR/resources/redis-server"

mkdir -p "$ROOT_DIR/resources"

if [ -f "$DEST" ]; then
    echo "[prepare-redis] Already exists: $DEST"
    exit 0
fi

# 1. 尝试系统 redis-server
if command -v redis-server &>/dev/null; then
    SRC="$(which redis-server)"
    echo "[prepare-redis] Copying from system: $SRC -> $DEST"
    cp "$SRC" "$DEST"
    chmod 755 "$DEST"
    echo "[prepare-redis] Done."
    exit 0
fi

# 2. 常见固定路径
for candidate in /usr/bin/redis-server /usr/local/bin/redis-server /opt/homebrew/bin/redis-server; do
    if [ -f "$candidate" ]; then
        echo "[prepare-redis] Copying from: $candidate -> $DEST"
        cp "$candidate" "$DEST"
        chmod 755 "$DEST"
        echo "[prepare-redis] Done."
        exit 0
    fi
done

# 3. 编译安装（Linux fallback，需要 build-essential）
echo "[prepare-redis] redis-server not found, attempting to compile from source..."
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
