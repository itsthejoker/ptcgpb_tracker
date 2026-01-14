#!/usr/bin/env bash

# Build a distributable ZIP (Linux) using uv + PyInstaller
# - Produces an onedir bundle under dist/<name>/ and a ZIP archive dist/<name>-<version>-linux.zip
# - Requires: uv (https://docs.astral.sh/uv/), zip

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' is not installed. Install from https://docs.astral.sh/uv/ (e.g., curl -LsSf https://astral.sh/uv/install.sh | sh)" >&2
  exit 1
fi

if ! command -v zip >/dev/null 2>&1; then
  echo "Error: 'zip' is required to create the distributable archive (sudo apt-get install zip)." >&2
  exit 1
fi

# Extract name and version from pyproject.toml (simple grep; avoids needing specific Python version)
PROJECT_NAME="$(sed -n 's/^name\s*=\s*"\(.*\)"/\1/p' pyproject.toml | head -n1)"
PROJECT_VERSION="$(sed -n 's/^version\s*=\s*"\(.*\)"/\1/p' pyproject.toml | head -n1)"

# Allow overrides via environment
APP_NAME="${APP_NAME:-${PROJECT_NAME:-PTCGP-Companion}}"
APP_VERSION="${APP_VERSION:-${PROJECT_VERSION:-0.0.0}}"

ENTRYPOINT="${ENTRYPOINT:-main.py}"

echo "Building ${APP_NAME} v${APP_VERSION} (entry: ${ENTRYPOINT})"

# Clean previous builds
rm -rf build dist

# Common PyInstaller options (Linux)
PYI_OPTS=(
  --noconfirm
  --clean
  --name "${APP_NAME}"
  --windowed
  --icon=_internal\ptcgpb-companion-icon.ico
)

# Data assets to include (src:dest within bundle)
# example:
#ADD_DATA=(
#  "resources/card_imgs:resources/card_imgs"
#)
ADD_DATA=(
  "_internal/ptcgpb-companion-icon.ico:_internal/ptcgpb-companion-icon.ico",
)

for spec in "${ADD_DATA[@]}"; do
  PYI_OPTS+=( --add-data "$spec" )
done

# If you have an application icon (e.g., resources/icons/app.ico or .png), uncomment and adjust:
# PYI_OPTS+=( --icon resources/icons/app.ico )

echo "Running PyInstaller via uv run..."
uv run --with pyinstaller pyinstaller "${PYI_OPTS[@]}" "${ENTRYPOINT}"

# Create versioned ZIP of the onedir distribution
DIST_DIR="dist/${APP_NAME}"
if [[ ! -d "${DIST_DIR}" ]]; then
  echo "Error: Expected output directory '${DIST_DIR}' not found. PyInstaller may have failed." >&2
  exit 1
fi

ZIP_NAME="dist/${APP_NAME}-${APP_VERSION}-linux.zip"
echo "Packaging ${DIST_DIR} -> ${ZIP_NAME}"
(cd dist && zip -rq "../${ZIP_NAME#dist/}" "${APP_NAME}")

echo "\nBuild complete: ${ZIP_NAME}"
echo "To run: unzip the archive and execute './${APP_NAME}/${APP_NAME}'"
