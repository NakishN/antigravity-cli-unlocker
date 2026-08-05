#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  AppImage Builder for Antigravity CLI Unlocker               ║
# ╚══════════════════════════════════════════════════════════════╝
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${ROOT_DIR}/build/AppDir"
DIST_DIR="${ROOT_DIR}/dist"

mkdir -p "${APP_DIR}/usr/bin"
mkdir -p "${DIST_DIR}"

# 1. Build PyInstaller binary
python3 "${ROOT_DIR}/packaging/build_binaries.py"

# 2. Copy binary to AppDir
cp "${DIST_DIR}/antigravity-unlock" "${APP_DIR}/usr/bin/antigravity-unlock"

# 3. Create AppRun launcher
cat > "${APP_DIR}/AppRun" << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "${HERE}/usr/bin/antigravity-unlock" "$@"
EOF
chmod +x "${APP_DIR}/AppRun"

# 4. Create Desktop Entry & Icon
cat > "${APP_DIR}/antigravity-unlock.desktop" << 'EOF'
[Desktop Entry]
Name=Antigravity CLI Unlocker
Exec=antigravity-unlock
Icon=antigravity-unlock
Type=Application
Categories=Utility;Network;
Comment=Bypass regional restrictions for Google Antigravity CLI
EOF

# Minimal SVG icon
cat > "${APP_DIR}/antigravity-unlock.svg" << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="45" fill="#4285F4"/>
  <path d="M30 65 L50 25 L70 65 Z" fill="#FFFFFF"/>
</svg>
EOF

# 5. Fetch appimagetool if not present and generate .AppImage
APPIMAGETOOL="/tmp/appimagetool"
if [[ ! -f "${APPIMAGETOOL}" ]]; then
    echo "Downloading appimagetool..."
    curl -sLO "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -o "${APPIMAGETOOL}" || true
    chmod +x "${APPIMAGETOOL}" 2>/dev/null || true
fi

if [[ -x "${APPIMAGETOOL}" ]]; then
    ARCH=x86_64 "${APPIMAGETOOL}" "${APP_DIR}" "${DIST_DIR}/Antigravity_Unlocker-x86_64.AppImage"
    echo "AppImage created at ${DIST_DIR}/Antigravity_Unlocker-x86_64.AppImage"
else
    echo "Notice: AppDir structure prepared at ${APP_DIR}. Install appimagetool to finalize .AppImage bundle."
fi
