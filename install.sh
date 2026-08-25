#!/bin/sh

set -eu

DOMAIN="sceneglow"
CONFIG_DIR="${HA_CONFIG_DIR:-}"
STAGING_DIR=""
BACKUP_DIR=""

usage() {
    printf '%s\n' "Usage: $0 [--config-dir PATH]"
    printf '%s\n' ""
    printf '%s\n' "Install or upgrade SceneGlow in a Home Assistant configuration directory."
    printf '%s\n' "If PATH is omitted, HA_CONFIG_DIR, /config, and ~/.homeassistant are tried."
}

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

cleanup() {
    if [ -n "$STAGING_DIR" ] && [ -d "$STAGING_DIR" ]; then
        rm -rf -- "$STAGING_DIR"
    fi
}

trap cleanup EXIT HUP INT TERM

while [ "$#" -gt 0 ]; do
    case "$1" in
        --config-dir)
            [ "$#" -ge 2 ] || fail "--config-dir requires a path"
            CONFIG_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            if [ -z "$CONFIG_DIR" ]; then
                CONFIG_DIR="$1"
                shift
            else
                fail "unexpected argument: $1"
            fi
            ;;
    esac
done

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
SOURCE_DIR="$SCRIPT_DIR/custom_components/$DOMAIN"
[ -f "$SOURCE_DIR/manifest.json" ] || fail "run this script from an extracted SceneGlowHA release"

if [ -z "$CONFIG_DIR" ]; then
    if [ -d /config ]; then
        CONFIG_DIR="/config"
    elif [ -n "${HOME:-}" ] && [ -d "$HOME/.homeassistant" ]; then
        CONFIG_DIR="$HOME/.homeassistant"
    else
        fail "Home Assistant config directory not found; use --config-dir PATH"
    fi
fi

[ -d "$CONFIG_DIR" ] || fail "config directory does not exist: $CONFIG_DIR"
CONFIG_DIR=$(CDPATH= cd -- "$CONFIG_DIR" && pwd -P)
[ "$CONFIG_DIR" != "/" ] || fail "refusing to use the filesystem root as a config directory"

VERSION=$(awk -F '"' '/"version"[[:space:]]*:/ { print $4; exit }' "$SOURCE_DIR/manifest.json")
[ -n "$VERSION" ] || fail "could not read the integration version"

CUSTOM_COMPONENTS="$CONFIG_DIR/custom_components"
TARGET_DIR="$CUSTOM_COMPONENTS/$DOMAIN"
BACKUP_ROOT="$CONFIG_DIR/.sceneglow-backups"
mkdir -p "$CUSTOM_COMPONENTS"
STAGING_DIR=$(mktemp -d "$CUSTOM_COMPONENTS/.sceneglow-install.XXXXXX")
cp -R "$SOURCE_DIR/." "$STAGING_DIR/"
[ -f "$STAGING_DIR/manifest.json" ] || fail "staged integration is incomplete"

if [ -e "$TARGET_DIR" ]; then
    [ -d "$TARGET_DIR" ] || fail "installation target is not a directory: $TARGET_DIR"
    mkdir -p "$BACKUP_ROOT"
    TIMESTAMP=$(date -u '+%Y%m%d-%H%M%S')
    BACKUP_DIR="$BACKUP_ROOT/sceneglow-pre-$VERSION-$TIMESTAMP-$$"
    mv "$TARGET_DIR" "$BACKUP_DIR"
fi

if ! mv "$STAGING_DIR" "$TARGET_DIR"; then
    if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
        mv "$BACKUP_DIR" "$TARGET_DIR"
    fi
    fail "installation failed; the previous version was restored"
fi
STAGING_DIR=""

printf 'SceneGlow %s installed in %s\n' "$VERSION" "$TARGET_DIR"
if [ -n "$BACKUP_DIR" ]; then
    printf 'Previous installation backed up to %s\n' "$BACKUP_DIR"
fi
printf '%s\n' "Restart Home Assistant, then add SceneGlow from Settings > Devices & services."
