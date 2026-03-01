#!/bin/bash
# =============================================================================
# Script: install.sh
# Description: Sets up Docker Status Monitor with autostart and taskbar pinning
# Note: This script dynamically detects its location - move the folder anywhere!
# =============================================================================

set -e

# Dynamically detect the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/docker-status-monitor.py"

# Verify Python script exists
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "❌ Error: docker-status-monitor.py not found in ${SCRIPT_DIR}"
    echo "   Make sure this script is in the same folder as the Python script."
    exit 1
fi

APP_NAME="docker-status-monitor"
DESKTOP_FILE="$HOME/.local/share/applications/${APP_NAME}.desktop"
AUTOSTART_DIR="$HOME/.config/autostart"
ICON_DIR="$HOME/.local/share/icons"
ICON_PATH="$ICON_DIR/docker-whale.svg"

echo "🐳 Docker Status Monitor Setup"
echo "==============================="

# Create directories
mkdir -p "$HOME/.local/share/applications"
mkdir -p "$AUTOSTART_DIR"
mkdir -p "$ICON_DIR"

# Create Docker whale SVG icon
echo "🎨 Creating Docker icon..."
cat > "$ICON_PATH" << 'SVGICON'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="256" height="256">
  <path fill="#2496ED" d="M13.983 11.078h2.119a.186.186 0 00.186-.185V9.006a.186.186 0 00-.186-.186h-2.119a.186.186 0 00-.185.186v1.887c0 .102.083.185.185.185m-2.954-5.43h2.118a.186.186 0 00.186-.186V3.574a.186.186 0 00-.186-.185h-2.118a.186.186 0 00-.185.185v1.888c0 .102.082.185.185.186m0 2.716h2.118a.187.187 0 00.186-.186V6.29a.186.186 0 00-.186-.185h-2.118a.186.186 0 00-.185.185v1.887c0 .102.082.186.185.186m-2.93 0h2.12a.186.186 0 00.184-.186V6.29a.185.185 0 00-.185-.185H8.1a.185.185 0 00-.185.185v1.887c0 .102.083.186.185.186m-2.964 0h2.119a.186.186 0 00.185-.186V6.29a.186.186 0 00-.185-.185H5.136a.186.186 0 00-.186.185v1.887c0 .102.084.186.186.186m5.893 2.715h2.118a.186.186 0 00.186-.185V9.006a.186.186 0 00-.186-.186h-2.118a.186.186 0 00-.185.186v1.887c0 .102.082.185.185.185m-2.93 0h2.12a.185.185 0 00.184-.185V9.006a.185.185 0 00-.184-.186h-2.12a.185.185 0 00-.184.186v1.887c0 .102.083.185.185.185m-2.964 0h2.119a.185.185 0 00.185-.185V9.006a.185.185 0 00-.185-.186h-2.119a.185.185 0 00-.186.186v1.887c0 .102.084.185.186.185m-2.92 0h2.12a.185.185 0 00.184-.185V9.006a.185.185 0 00-.184-.186h-2.12a.186.186 0 00-.185.186v1.887c0 .102.083.185.185.185M23.763 9.89c-.065-.051-.672-.51-1.954-.51-.338.001-.676.03-1.01.087-.248-1.7-1.653-2.53-1.716-2.566l-.344-.199-.226.327c-.284.438-.49.922-.612 1.43-.23.97-.09 1.882.403 2.661-.595.332-1.55.413-1.744.42H.751a.751.751 0 00-.75.748 11.376 11.376 0 00.692 4.062c.545 1.428 1.355 2.48 2.41 3.124 1.18.723 3.1 1.137 5.275 1.137.983.003 1.963-.086 2.93-.266a12.248 12.248 0 003.823-1.389c.98-.567 1.86-1.288 2.61-2.136 1.252-1.418 1.998-2.997 2.553-4.4h.221c1.372 0 2.215-.549 2.68-1.009.309-.293.55-.65.707-1.046l.098-.288z"/>
</svg>
SVGICON
echo "  ✓ Docker whale icon created"

# Create desktop entry
echo "📝 Creating desktop entry..."

# Escape spaces in path for desktop file Exec line
ESCAPED_SCRIPT_DIR=$(echo "$SCRIPT_DIR" | sed 's/ /\\ /g')

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Docker Monitor
Comment=Monitor Docker containers status
Exec=/usr/bin/python3 "${SCRIPT_DIR}/docker-status-monitor.py"
Icon=${ICON_PATH}
Terminal=false
Type=Application
Categories=Development;System;Monitor;
StartupNotify=true
StartupWMClass=docker-status-monitor
EOF
echo "  ✓ Desktop entry created"

# Setup autostart (skip if already exists)
if [ -L "$AUTOSTART_DIR/${APP_NAME}.desktop" ] || [ -f "$AUTOSTART_DIR/${APP_NAME}.desktop" ]; then
    echo "  ✓ Autostart already configured (skipped)"
else
    ln -sf "$DESKTOP_FILE" "$AUTOSTART_DIR/${APP_NAME}.desktop"
    echo "  ✓ Autostart enabled"
fi

# Pin to taskbar (GNOME/Ubuntu dock)
echo "📌 Pinning to taskbar..."
if command -v gsettings &> /dev/null; then
    # Get current favorites
    CURRENT_FAVORITES=$(gsettings get org.gnome.shell favorite-apps 2>/dev/null || echo "[]")
    
    # Check if already pinned
    if echo "$CURRENT_FAVORITES" | grep -q "${APP_NAME}.desktop"; then
        echo "  ✓ Already pinned to taskbar (skipped)"
    else
        # Add to favorites
        NEW_FAVORITES=$(echo "$CURRENT_FAVORITES" | sed "s/]$/, '${APP_NAME}.desktop']/")
        # Fix if it was empty
        NEW_FAVORITES=$(echo "$NEW_FAVORITES" | sed "s/\[, /[/")
        gsettings set org.gnome.shell favorite-apps "$NEW_FAVORITES" 2>/dev/null && \
            echo "  ✓ Pinned to taskbar" || \
            echo "  ⚠ Could not pin to taskbar (may need manual pinning)"
    fi
else
    echo "  ⚠ gsettings not found - please pin manually by right-clicking the app"
fi

# Update desktop database
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo ""
echo "==============================="
echo "✅ Setup complete!"
echo ""
echo "You can now:"
echo "  • Find 'Docker Monitor' in your applications menu"
echo "  • See it pinned in your taskbar"
echo "  • It will auto-start on login"
echo ""
echo "To launch now, run:"
echo "  python3 ${SCRIPT_DIR}/docker-status-monitor.py"
