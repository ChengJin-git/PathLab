#!/usr/bin/env bash
set -euo pipefail

PATCH_DIR="patches"
TEMP_PATCH_DIR=".patch-package-active.$$"
mkdir -p "$TEMP_PATCH_DIR"

cleanup() {
  rm -rf "$TEMP_PATCH_DIR"
}
trap cleanup EXIT

copy_patch_if_present() {
  local package_dir="$1"
  local patch_file="$2"

  if [[ -d "$package_dir" && -f "$patch_file" ]]; then
    cp "$patch_file" "$TEMP_PATCH_DIR/"
  fi
}

copy_patch_if_present "node_modules/embedded-postgres" "$PATCH_DIR/embedded-postgres+18.3.0-beta.16.patch"
copy_patch_if_present "node_modules/@embedded-postgres/linux-x64" "$PATCH_DIR/@embedded-postgres+linux-x64+18.3.0-beta.16.patch"

if [[ -n "$(find "$TEMP_PATCH_DIR" -type f -name '*.patch' -print -quit)" ]]; then
  patch-package --patch-dir "$TEMP_PATCH_DIR"
fi
