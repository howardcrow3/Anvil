#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build"
APP_BUNDLE="$BUILD_DIR/Anvil.app"

# Check that the .app bundle exists
if [ ! -d "$APP_BUNDLE" ]; then
    echo "ERROR: $APP_BUNDLE not found."
    echo "Run ./Scripts/build-app.sh first to build the app bundle."
    exit 1
fi

# Read version from Info.plist
VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP_BUNDLE/Contents/Info.plist" 2>/dev/null || echo "0.0.0")
DMG_NAME="Anvil-${VERSION}.dmg"
DMG_PATH="$BUILD_DIR/$DMG_NAME"

echo "=== Packaging Anvil ${VERSION} DMG ==="

# Remove old DMG if it exists
rm -f "$DMG_PATH"

# Create a temporary directory for DMG contents
DMG_TEMP=$(mktemp -d)
trap "rm -rf '$DMG_TEMP'" EXIT

cp -r "$APP_BUNDLE" "$DMG_TEMP/"
ln -s /Applications "$DMG_TEMP/Applications"

# Create DMG with UDBZ compression
echo "Creating DMG with UDBZ compression..."
hdiutil create \
    -volname "Anvil" \
    -srcfolder "$DMG_TEMP" \
    -ov \
    -format UDBZ \
    "$DMG_PATH"

# Optional codesign
if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    echo "Signing app bundle with identity: $CODESIGN_IDENTITY"
    codesign --deep --force --options runtime \
        --sign "$CODESIGN_IDENTITY" \
        --entitlements "$PROJECT_ROOT/Anvil.entitlements" \
        "$APP_BUNDLE"
    echo "Re-creating signed DMG..."
    rm -f "$DMG_PATH"
    hdiutil create \
        -volname "Anvil" \
        -srcfolder "$DMG_TEMP" \
        -ov \
        -format UDBZ \
        "$DMG_PATH"
    codesign --sign "$CODESIGN_IDENTITY" "$DMG_PATH"
    echo "Signing complete."
fi

# Optional notarization
if [ "${NOTARIZE:-0}" = "1" ]; then
    echo "Submitting for notarization..."
    if [ -z "${APPLE_ID:-}" ] || [ -z "${APPLE_TEAM_ID:-}" ]; then
        echo "ERROR: NOTARIZE=1 requires APPLE_ID and APPLE_TEAM_ID environment variables."
        exit 1
    fi
    xcrun notarytool submit "$DMG_PATH" \
        --apple-id "$APPLE_ID" \
        --team-id "$APPLE_TEAM_ID" \
        --keychain-profile "anvil-notary" \
        --wait
    xcrun stapler staple "$DMG_PATH"
    echo "Notarization complete."
fi

# Print results
DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
echo ""
echo "=== DMG Packaging Complete ==="
echo "  Path: $DMG_PATH"
echo "  Size: $DMG_SIZE"
