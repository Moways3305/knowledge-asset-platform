#!/bin/sh
set -eu

origin=${ONLYOFFICE_ORIGIN:-}

# Empty keeps the default self-only CSP. Any configured value must be exactly
# one HTTP(S) origin; reject before nginx's envsubst entrypoint renders it.
if [ -z "$origin" ]; then
    exit 0
fi

if ! awk -v origin="$origin" '
    BEGIN {
        if (origin !~ /^https?:\/\/(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?)(:[0-9]+)?$/) {
            exit 1
        }

        authority = origin
        sub(/^https?:\/\//, "", authority)
        port = ""
        if (authority ~ /^\[/) {
            closing_bracket = index(authority, "]")
            suffix = substr(authority, closing_bracket + 1)
            if (suffix != "") {
                port = substr(suffix, 2)
            }
        } else if (index(authority, ":") != 0) {
            port = substr(authority, index(authority, ":") + 1)
        }

        if (port != "" && (length(port) > 5 || port + 0 < 1 || port + 0 > 65535)) {
            exit 1
        }
    }
'; then
    echo "Invalid ONLYOFFICE_ORIGIN: expected one HTTP(S) origin" >&2
    exit 1
fi
