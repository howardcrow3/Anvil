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
RW_DMG="$BUILD_DIR/Anvil-rw.dmg"

echo "=== Packaging Anvil ${VERSION} DMG ==="

# Remove old DMGs
rm -f "$DMG_PATH" "$RW_DMG"

# Calculate required size (source + 50MB overhead for filesystem metadata)
SRC_SIZE_MB=$(( $(du -sm "$APP_BUNDLE" | cut -f1) + 50 ))

echo "Creating read-write DMG (${SRC_SIZE_MB}MB)..."
hdiutil create \
    -volname "Anvil" \
    -size "${SRC_SIZE_MB}m" \
    -fs HFS+ \
    -layout NONE \
    "$RW_DMG"

# Mount the RW image
MOUNT_DIR=$(hdiutil attach -readwrite -noverify -noautoopen "$RW_DMG" | grep "/Volumes/" | sed 's|.*\(/Volumes/.*\)|\1|')
echo "Mounted at: $MOUNT_DIR"

# Copy app bundle and create Applications symlink
cp -r "$APP_BUNDLE" "$MOUNT_DIR/"
ln -s /Applications "$MOUNT_DIR/Applications"

# Unmount
hdiutil detach "$MOUNT_DIR" -quiet

# Convert to compressed read-only UDBZ
echo "Compressing to UDBZ..."
hdiutil convert "$RW_DMG" -format UDBZ -o "$DMG_PATH"
rm -f "$RW_DMG"

# Optional codesign
if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    echo "Signing app bundle with identity: $CODESIGN_IDENTITY"
    codesign --deep --force --options runtime \
        --sign "$CODESIGN_IDENTITY" \
        --entitlements "$PROJECT_ROOT/Anvil.entitlements" \
        "$APP_BUNDLE"
    echo "Re-creating signed DMG..."
    rm -f "$DMG_PATH" "$RW_DMG"
    hdiutil create -volname "Anvil" -size "${SRC_SIZE_MB}m" -fs HFS+ -layout NONE "$RW_DMG"
    MOUNT_DIR=$(hdiutil attach -readwrite -noverify -noautoopen "$RW_DMG" | grep "/Volumes/" | sed 's|.*\(/Volumes/.*\)|\1|')
    cp -r "$APP_BUNDLE" "$MOUNT_DIR/"
    ln -s /Applications "$MOUNT_DIR/Applications"
    hdiutil detach "$MOUNT_DIR" -quiet
    hdiutil convert "$RW_DMG" -format UDBZ -o "$DMG_PATH"
    rm -f "$RW_DMG"
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
