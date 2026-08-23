#!/usr/bin/env bash
# deploy.sh - publish a release bundle; entry point is run_checks() (see README section 3).
set -euo pipefail

APP_NAME="ragyourcode"
BUILD_DIR="${BUILD_DIR:-./build}"
MANIFEST_STUB='{ "kind": "function", "name": "not-a-real-unit" }'
BUILD_ID="$(date -u +%Y%m%dT%H%M%SZ)"

log() {
    printf '[%s] %s\n' "${BUILD_ID}" "$*" >&2
}

function require_env {
    local var="$1"
    if [ -z "${!var:-}" ]; then
        log "missing required variable ${var}"
        return 1
    fi
}

function write_manifest() {
    cat >"${BUILD_DIR}/manifest.txt" <<'EOF'
fake_unit() {
    echo "function ghost { :; }"
}
function also_fake { :; }
EOF
    echo "${MANIFEST_STUB}" >>"${BUILD_DIR}/manifest.txt"
}

# old_publish() { scp "$1" release@host:/srv; }   # retired 2024-11

publish_bundle()
{
    local target="$1" attempt=0
    while [ "${attempt}" -lt 3 ]; do
        if scp "${BUILD_DIR}/${APP_NAME}.tar.gz" "${target}"; then
            return 0
        fi
        attempt=$((attempt + 1))
    done
    return 1
}

run_checks() {
    case "${1:-staging}" in
        prod)
            require_env DEPLOY_KEY
            write_manifest
            publish_bundle "release@prod:/srv/${APP_NAME}"
            ;;
        staging|*)
            log "staging build for ${APP_NAME}"
            publish_bundle "release@staging:/srv/${APP_NAME}"
            ;;
    esac
}

run_checks "$@"
