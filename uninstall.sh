#!/bin/bash
# =============================================================================
# Script: uninstall.sh
# Description: Removes Docker Status Monitor setup (desktop entry, autostart, taskbar pin)
# Note: This does NOT delete the Python script or this folder
# =============================================================================

set -e

APP_NAME="docker-status-monitor"
DESKTOP_FILE="$HOME/.local/share/applications/${APP_NAME}.desktop"
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/${APP_NAME}.desktop"
ICON_PATH="$HOME/.local/share/icons/docker-whale.svg"
LOCK_FILE="/tmp/docker-status-monitor.lock"

echo "🐳 Docker Status Monitor Uninstall"
echo "==================================="

# Kill any running instance
echo "🔍 Checking for running instance..."
if [ -f "$LOCK_FILE" ]; then
    OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "  ⏹ Stopping running instance (PID: $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 0.5
    fi
    rm -f "$LOCK_FILE"
    echo "  ✓ Lock file removed"
else
    echo "  ✓ No running instance found"
fi

# Remove from taskbar (GNOME/Ubuntu dock)
echo "📌 Removing from taskbar..."
if command -v gsettings &> /dev/null; then
    CURRENT_FAVORITES=$(gsettings get org.gnome.shell favorite-apps 2>/dev/null || echo "[]")
    
    if echo "$CURRENT_FAVORITES" | grep -q "${APP_NAME}.desktop"; then
        # Remove from favorites
        NEW_FAVORITES=$(echo "$CURRENT_FAVORITES" | sed "s/, '${APP_NAME}.desktop'//g" | sed "s/'${APP_NAME}.desktop', //g" | sed "s/'${APP_NAME}.desktop'//g")
        gsettings set org.gnome.shell favorite-apps "$NEW_FAVORITES" 2>/dev/null && \
            echo "  ✓ Removed from taskbar" || \
            echo "  ⚠ Could not remove from taskbar"
    else
        echo "  ✓ Not pinned to taskbar (skipped)"
    fi
else
    echo "  ⚠ gsettings not found - may need manual unpinning"
fi

# Remove autostart
echo "🚀 Removing autostart..."
if [ -L "$AUTOSTART_FILE" ] || [ -f "$AUTOSTART_FILE" ]; then
    rm -f "$AUTOSTART_FILE"
    echo "  ✓ Autostart removed"
else
    echo "  ✓ No autostart entry found (skipped)"
fi

# Remove desktop entry
echo "📝 Removing desktop entry..."
if [ -f "$DESKTOP_FILE" ]; then
    rm -f "$DESKTOP_FILE"
    echo "  ✓ Desktop entry removed"
else
    echo "  ✓ No desktop entry found (skipped)"
fi

# Remove icon (optional - ask user)
if [ -f "$ICON_PATH" ]; then
    echo "🎨 Removing icon..."
    rm -f "$ICON_PATH"
    echo "  ✓ Icon removed"
fi

# Update desktop database
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo ""
echo "==================================="
echo "✅ Uninstall complete!"
echo ""
echo "The following were removed:"
echo "  • Desktop entry (applications menu)"
echo "  • Autostart on login"
echo "  • Taskbar pin"
echo "  • Application icon"
echo ""
echo "Note: The Python script and this folder were NOT deleted."
echo "      To reinstall, run: ./install.sh"
