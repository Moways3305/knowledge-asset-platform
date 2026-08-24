#!/bin/sh
# Install the versioned KAP host-Nginx site atomically, validate, then reload.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
template="$script_dir/nginx-host-kap.conf.template"
site_path=${KAP_NGINX_SITE_PATH:-/etc/nginx/conf.d/kap.conf}

: "${KAP_SERVER_NAME:?KAP_SERVER_NAME is required}"
: "${KAP_TLS_CERTIFICATE:?KAP_TLS_CERTIFICATE is required}"
: "${KAP_TLS_CERTIFICATE_KEY:?KAP_TLS_CERTIFICATE_KEY is required}"

case "$KAP_SERVER_NAME" in
    *[!A-Za-z0-9.-]*|'') echo "invalid KAP_SERVER_NAME" >&2; exit 2 ;;
esac
case "$KAP_TLS_CERTIFICATE:$KAP_TLS_CERTIFICATE_KEY:$site_path" in
    *[!A-Za-z0-9_./:-]*) echo "invalid nginx path" >&2; exit 2 ;;
esac
[ -f "$KAP_TLS_CERTIFICATE" ] || { echo "TLS certificate not found" >&2; exit 2; }
[ -f "$KAP_TLS_CERTIFICATE_KEY" ] || { echo "TLS certificate key not found" >&2; exit 2; }

site_dir=$(dirname -- "$site_path")
[ -d "$site_dir" ] || { echo "nginx site directory not found" >&2; exit 2; }

# The candidate must live beside the target so mv is a same-filesystem atomic rename.
rendered=$(mktemp "${site_path}.new.XXXXXX")
backup=$(mktemp)
rollback_candidate=""
cleanup() {
    rm -f "$rendered" "$backup"
    if [ -n "$rollback_candidate" ]; then
        rm -f "$rollback_candidate"
    fi
}
trap cleanup EXIT HUP INT TERM

sed \
    -e "s|__KAP_SERVER_NAME__|$KAP_SERVER_NAME|g" \
    -e "s|__KAP_TLS_CERTIFICATE__|$KAP_TLS_CERTIFICATE|g" \
    -e "s|__KAP_TLS_CERTIFICATE_KEY__|$KAP_TLS_CERTIFICATE_KEY|g" \
    "$template" > "$rendered"

had_previous=false
if [ -f "$site_path" ]; then
    cp "$site_path" "$backup"
    had_previous=true
fi

restore_previous_site() {
    if [ "$had_previous" = true ]; then
        rollback_candidate=$(mktemp "${site_path}.rollback.XXXXXX")
        install -m 0644 "$backup" "$rollback_candidate"
        mv -f "$rollback_candidate" "$site_path"
        rollback_candidate=""
    else
        rm -f "$site_path"
    fi
}

chmod 0644 "$rendered"
mv -f "$rendered" "$site_path"

if ! nginx -t; then
    restore_previous_site
    nginx -t || true
    echo "nginx validation failed; previous site restored" >&2
    exit 1
fi

if ! nginx -s reload; then
    restore_previous_site
    if ! nginx -t; then
        echo "nginx reload failed; previous site restored but its validation failed" >&2
        exit 1
    fi
    if ! nginx -s reload; then
        echo "nginx reload failed; previous site restored but rollback reload also failed" >&2
        exit 1
    fi
    echo "nginx reload failed; previous site restored and reloaded" >&2
    exit 1
fi

echo "KAP host nginx site installed and reloaded"
