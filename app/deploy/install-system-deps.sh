#!/usr/bin/env bash
# Explicit Ubuntu host setup. Does not change database credentials or GPU drivers.
set -euo pipefail
if [[ "${1:-}" == "--help" ]]; then
    echo "sudo bash deploy/install-system-deps.sh (Ubuntu 22.04/24.04)"
    exit 0
fi
source /etc/os-release
[[ "$ID" == ubuntu && "$EUID" == 0 ]] || { echo "Run as root on Ubuntu; see MIGRATION.md."; exit 1; }
apt-get update
apt-get install -y ca-certificates curl git rsync build-essential pkg-config \
    python3 python3-venv python3-pip libopenslide0 openslide-tools libgl1 \
    libglib2.0-0 libgomp1 libjpeg-turbo8 libopenjp2-7 libnuma1 libfuse3-3 \
    postgresql postgresql-client redis-server software-properties-common uidmap \
    fakeroot squashfs-tools fuse-overlayfs libreoffice-writer libreoffice-impress fonts-noto-cjk
if ! command -v apptainer >/dev/null; then
    add-apt-repository -y ppa:apptainer/ppa
    apt-get update
    apt-get install -y apptainer
fi
echo "Install Node 26.13.0 LTS (or supported 22.22.2+/24.15+) and a CUDA-13-compatible NVIDIA driver; see MIGRATION.md."
