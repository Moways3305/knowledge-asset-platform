#!/bin/sh
# Safely attach KAP upload-only rules to an existing mixed-use Nginx site.
set -eu

usage() {
    echo "usage: $0 --check|--install|--verify" >&2
    exit 2
}

[ "$#" -eq 1 ] || usage
mode=$1
case "$mode" in
    --check|--install|--verify) ;;
    *) usage ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_snippet="$script_dir/nginx-host-upload-rules.conf"
site_path=${KAP_NGINX_SITE_PATH:-/etc/nginx/sites-available/kap}
snippet_path=${KAP_NGINX_SNIPPET_PATH:-/etc/nginx/snippets/kap-upload-rules.conf}
include_path=${KAP_NGINX_INCLUDE_PATH:-/etc/nginx/snippets/kap-upload-rules.conf}

: "${KAP_SERVER_NAME:?KAP_SERVER_NAME is required}"
case "$KAP_SERVER_NAME" in
    *[!A-Za-z0-9.-]*|'') echo "invalid KAP_SERVER_NAME" >&2; exit 2 ;;
esac
case "$site_path:$snippet_path:$include_path" in
    *[!A-Za-z0-9_./:-]*) echo "invalid nginx path" >&2; exit 2 ;;
esac
[ -f "$site_path" ] || {
    echo "KAP site not found: $site_path" >&2
    echo "Set KAP_NGINX_SITE_PATH to the existing site containing server_name $KAP_SERVER_NAME." >&2
    exit 2
}
[ -f "$source_snippet" ] || { echo "managed upload snippet is missing" >&2; exit 2; }

inspect_site() {
    awk -v wanted="$KAP_SERVER_NAME" -v include_path="$include_path" '
        function brace_delta(s, opens, closes) {
            opens = gsub(/\{/, "{", s)
            closes = gsub(/\}/, "}", s)
            return opens - closes
        }
        function has_server_name(s, clean, parts, count, i) {
            clean = s
            sub(/#.*/, "", clean)
            gsub(/;/, " ", clean)
            count = split(clean, parts, /[ \t]+/)
            for (i = 1; i <= count; i++) if (parts[i] == wanted) return 1
            return 0
        }
        BEGIN { depth = 0; in_server = 0; server_depth = -1 }
        {
            line = $0
            if (!in_server && line ~ /^[ \t]*server[ \t]*\{/) {
                in_server = 1
                server_depth = depth
                matched = 0
                root = 0
                included = 0
            }
            if (in_server) {
                if (line ~ /^[ \t]*server_name[ \t]+/ && has_server_name(line)) matched = 1
                if (line ~ /^[ \t]*location[ \t]+\/[ \t]*\{/) root++
                if (index(line, "include " include_path ";") > 0) included++
            }
            depth += brace_delta(line)
            if (in_server && depth == server_depth) {
                if (matched) {
                    matches++
                    roots += root
                    includes += included
                }
                in_server = 0
            }
        }
        END { print matches + 0, roots + 0, includes + 0 }
    ' "$site_path"
}

set -- $(inspect_site)
match_count=$1
root_count=$2
include_count=$3
if [ "$match_count" -ne 1 ] || [ "$root_count" -ne 1 ] || [ "$include_count" -gt 1 ]; then
    echo "Cannot safely attach KAP upload rules." >&2
    echo "Expected exactly one server for $KAP_SERVER_NAME with one 'location /' and at most one managed include; found servers=$match_count root_locations=$root_count includes=$include_count." >&2
    echo "Manually add 'include $include_path;' inside the intended server block, then run --check." >&2
    exit 2
fi

check_snippet() {
    [ -f "$snippet_path" ] && cmp -s "$source_snippet" "$snippet_path"
}

if [ "$mode" = "--check" ]; then
    echo "KAP server found: $KAP_SERVER_NAME ($site_path)"
    if [ "$include_count" -eq 1 ]; then
        echo "Managed include found: $include_path"
    else
        echo "Managed include is not installed; --install will add it without replacing the server block."
    fi
    if check_snippet; then
        echo "Managed snippet is current: $snippet_path"
    else
        echo "Managed snippet is missing or differs: $snippet_path"
    fi
    exit 0
fi

if [ "$mode" = "--verify" ]; then
    [ "$include_count" -eq 1 ] || { echo "managed include is not installed" >&2; exit 1; }
    check_snippet || { echo "managed snippet is missing or differs" >&2; exit 1; }
    nginx -t
    echo "Effective KAP upload snippet ($snippet_path):"
    sed -n '/KAP_UPLOAD_RULES_BEGIN/,/KAP_UPLOAD_RULES_END/p' "$snippet_path"
    exit 0
fi

snippet_dir=$(dirname -- "$snippet_path")
site_dir=$(dirname -- "$site_path")
[ -d "$snippet_dir" ] || { echo "nginx snippet directory not found: $snippet_dir" >&2; exit 2; }
[ -d "$site_dir" ] || { echo "nginx site directory not found: $site_dir" >&2; exit 2; }

snippet_candidate=$(mktemp "${snippet_path}.new.XXXXXX")
site_candidate=$(mktemp "${site_path}.new.XXXXXX")
snippet_backup=$(mktemp)
site_backup=$(mktemp)
snippet_existed=false
site_changed=false
cleanup() {
    rm -f "$snippet_candidate" "$site_candidate" "$snippet_backup" "$site_backup"
}
trap cleanup EXIT HUP INT TERM

if [ -f "$snippet_path" ]; then
    cp "$snippet_path" "$snippet_backup"
    snippet_existed=true
fi
cp "$site_path" "$site_backup"
install -m 0644 "$source_snippet" "$snippet_candidate"

if [ "$include_count" -eq 0 ]; then
    awk -v wanted="$KAP_SERVER_NAME" -v include_path="$include_path" '
        function has_server_name(s, clean, parts, count, i) {
            clean = s
            sub(/#.*/, "", clean)
            gsub(/;/, " ", clean)
            count = split(clean, parts, /[ \t]+/)
            for (i = 1; i <= count; i++) if (parts[i] == wanted) return 1
            return 0
        }
        {
            print
            if ($0 ~ /^[ \t]*server_name[ \t]+/ && has_server_name($0))
                print "    include " include_path "; # managed by KAP"
        }
    ' "$site_path" > "$site_candidate"
    chmod 0644 "$site_candidate"
    site_changed=true
else
    cp "$site_path" "$site_candidate"
fi

restore_previous() {
    rollback=$(mktemp "${site_path}.rollback.XXXXXX")
    install -m 0644 "$site_backup" "$rollback"
    mv -f "$rollback" "$site_path"
    if [ "$snippet_existed" = true ]; then
        rollback=$(mktemp "${snippet_path}.rollback.XXXXXX")
        install -m 0644 "$snippet_backup" "$rollback"
        mv -f "$rollback" "$snippet_path"
    else
        rm -f "$snippet_path"
    fi
}

mv -f "$snippet_candidate" "$snippet_path"
if [ "$site_changed" = true ]; then
    mv -f "$site_candidate" "$site_path"
fi

if ! nginx -t; then
    restore_previous
    nginx -t || true
    echo "nginx validation failed; site and snippet restored" >&2
    exit 1
fi
if ! nginx -s reload; then
    restore_previous
    if nginx -t && nginx -s reload; then
        echo "nginx reload failed; site and snippet restored and reloaded" >&2
    else
        echo "nginx reload failed; rollback restored but could not be reloaded" >&2
    fi
    exit 1
fi

echo "KAP upload rules installed; existing server, TLS, ONLYOFFICE, Certbot, and validation locations were preserved."
