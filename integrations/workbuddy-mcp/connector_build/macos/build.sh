#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?version required}"
CHANNEL="${2:-internal}"
ARCH="${3:?arm64 or x64 required}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RELEASE="$ROOT/release"
WORK="$ROOT/build-$ARCH"
APP="$WORK/KAP WorkBuddy Connector.app"
PAYLOAD="$WORK/payload"
FILENAME="kap-workbuddy-connector-$VERSION-macos-$ARCH.pkg"
ARTIFACT="$RELEASE/$FILENAME"
BINARY="$WORK/binary/kap-workbuddy-connector"

if [[ "$CHANNEL" != "internal" && "$CHANNEL" != "production" ]]; then
  echo "channel must be internal or production" >&2
  exit 2
fi
export CONNECTOR_ARCH="$ARCH"
python "$ROOT/connector_build/build_binary.py" --output-dir "$WORK/binary" --work-dir "$WORK"
if [[ ! -f "$BINARY" || ! -s "$BINARY" ]]; then
  echo "Missing or empty connector binary for macos-$ARCH (build-$ARCH/binary/kap-workbuddy-connector)." >&2
  exit 4
fi
rm -rf "$APP" "$PAYLOAD"
mkdir -p "$APP/Contents/MacOS" "$PAYLOAD/Applications" "$RELEASE"
cp "$BINARY" "$APP/Contents/MacOS/kap-workbuddy-connector"
chmod 755 "$APP/Contents/MacOS/kap-workbuddy-connector"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>kap-workbuddy-connector</string>
  <key>CFBundleIdentifier</key>
  <string>com.bowei.kap.workbuddy-connector</string>
  <key>CFBundleName</key>
  <string>KAP WorkBuddy Connector</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>$VERSION</string>
  <key>CFBundleVersion</key>
  <string>$VERSION</string>
  <key>LSBackgroundOnly</key>
  <true/>
</dict>
</plist>
PLIST

SIGNED=false
NOTARIZED=false
if [[ "$CHANNEL" == "production" ]]; then
  required=(APPLE_DEVELOPER_ID_APPLICATION APPLE_DEVELOPER_ID_INSTALLER APPLE_ID APPLE_TEAM_ID APPLE_APP_PASSWORD)
  for name in "${required[@]}"; do
    if [[ -z "${!name:-}" ]]; then
      echo "Production macOS release requires all Developer ID and notarization credentials." >&2
      exit 3
    fi
  done
  codesign --force --options runtime --timestamp \
    --entitlements "$ROOT/connector_build/macos/entitlements.plist" \
    --sign "$APPLE_DEVELOPER_ID_APPLICATION" "$APP/Contents/MacOS/kap-workbuddy-connector"
  codesign --force --options runtime --timestamp \
    --sign "$APPLE_DEVELOPER_ID_APPLICATION" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
fi

if [[ ! -f "$APP/Contents/MacOS/kap-workbuddy-connector" || ! -s "$APP/Contents/MacOS/kap-workbuddy-connector" ]]; then
  echo "Missing or empty app binary before payload copy for macos-$ARCH." >&2
  exit 4
fi
cp -R "$APP" "$PAYLOAD/Applications/"
if [[ ! -f "$PAYLOAD/Applications/KAP WorkBuddy Connector.app/Contents/MacOS/kap-workbuddy-connector" || ! -s "$PAYLOAD/Applications/KAP WorkBuddy Connector.app/Contents/MacOS/kap-workbuddy-connector" ]]; then
  echo "Missing or empty package input before pkgbuild for macos-$ARCH." >&2
  exit 4
fi
UNSIGNED="$WORK/unsigned.pkg"
pkgbuild --root "$PAYLOAD" \
  --identifier "com.bowei.kap.workbuddy-connector" \
  --version "$VERSION" \
  --install-location "/" "$UNSIGNED"

if [[ "$CHANNEL" == "production" ]]; then
  productsign --sign "$APPLE_DEVELOPER_ID_INSTALLER" "$UNSIGNED" "$ARTIFACT"
  pkgutil --check-signature "$ARTIFACT"
  xcrun notarytool submit "$ARTIFACT" \
    --apple-id "$APPLE_ID" \
    --password "$APPLE_APP_PASSWORD" \
    --team-id "$APPLE_TEAM_ID" \
    --wait
  xcrun stapler staple "$ARTIFACT"
  xcrun stapler validate "$ARTIFACT"
  spctl --assess --type install --verbose=2 "$ARTIFACT"
  SIGNED=true
  NOTARIZED=true
else
  mv "$UNSIGNED" "$ARTIFACT"
fi

if [[ ! -f "$ARTIFACT" || ! -s "$ARTIFACT" ]]; then
  echo "Missing or empty installer artifact for macos-$ARCH." >&2
  exit 4
fi
python - "$RELEASE/$FILENAME.metadata.json" "$FILENAME" "$ARCH" "$SIGNED" "$NOTARIZED" <<'PY'
import json
import sys

path, filename, arch, signed, notarized = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "platform": "macos",
            "architecture": arch,
            "filename": filename,
            "signed": signed == "true",
            "notarized": notarized == "true",
        },
        handle,
        indent=2,
    )
PY
