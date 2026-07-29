"""Frozen connector entry point.

PyInstaller bundles this module, the Python runtime and workbuddy_mcp dependencies into the
platform executable. Runtime configuration still comes only from KAP_BASE_URL and
KAP_AGENT_TOKEN supplied by the user's local MCP configuration.
"""

from workbuddy_mcp.server import main

if __name__ == "__main__":
    main()
