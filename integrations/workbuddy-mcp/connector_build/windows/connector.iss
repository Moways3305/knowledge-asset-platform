#define ConnectorVersion GetEnv("CONNECTOR_VERSION")
#define ConnectorBinary GetEnv("CONNECTOR_BINARY")
#define ConnectorOutput GetEnv("CONNECTOR_OUTPUT")

[Setup]
AppId={{38DBEB78-691E-4CFD-B81B-1896A06D2329}
AppName=KAP WorkBuddy Connector
AppVersion={#ConnectorVersion}
DefaultDirName={autopf}\KAP WorkBuddy Connector
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ConnectorOutput}
OutputBaseFilename=kap-workbuddy-connector-{#ConnectorVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=KAP WorkBuddy Connector

[Files]
Source: "{#ConnectorBinary}"; DestDir: "{app}"; DestName: "kap-workbuddy-connector.exe"; Flags: ignoreversion
