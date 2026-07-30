# Connector installation smoke checks

The packaged executable is the stable WorkBuddy process entry. The installer never embeds a
personal token or a KAP configuration file.

## Windows x64

1. Run the installer and verify the default directory is
   `C:\Program Files\KAP WorkBuddy Connector`.
2. Repeat with a custom directory containing spaces.
3. Confirm `<selected directory>\kap-workbuddy-connector.exe` starts as a stdio child process.
4. Run the same installer again (repair/reinstall) and confirm it reuses the previous directory and
   replaces the same executable entry.
5. Generate the KAP configuration with the actual executable path and make one read-only MCP call.

## macOS arm64 and x64

1. Run the matching `macos-arm64.pkg` or `macos-x64.pkg`.
2. Confirm the package installs
   `/Applications/KAP WorkBuddy Connector.app/Contents/MacOS/kap-workbuddy-connector`.
3. Run the package again and confirm the same app entry is replaced.
4. Start that entry as a stdio child process and make one read-only MCP call.
5. If the app was manually moved, either reinstall it at `/Applications` or generate the KAP
   configuration with its actual POSIX executable path.

The platform CI jobs build each native installer and validate its inputs, signatures, notarization,
checksums, and manifest target. Process launch and repair behavior remain manual smoke checks because
Windows and macOS installers cannot be executed end-to-end on the opposite development platform.
