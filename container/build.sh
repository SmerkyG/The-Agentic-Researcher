#!/bin/bash
set -e

CONTAINER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$(cd "$CONTAINER_DIR/.." && pwd)"
REGISTERED_COMPONENTS=()

source "$SCRIPT_DIR/scripts/lib/launcher/registry.sh"
load_sandbox_adapters

# Load config if available
CONFIG_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/agentic-team/config.sh"
if [[ -f "$CONFIG_FILE" ]]; then
    source "$CONFIG_FILE"
fi

# Proxy: config → environment → nothing
if [[ -n "${AR_HTTPS_PROXY:-}" ]]; then
    export https_proxy="$AR_HTTPS_PROXY"
    export http_proxy="${AR_HTTP_PROXY:-$AR_HTTPS_PROXY}"
fi
# Also honor pre-existing env vars
[[ -n "${https_proxy:-}" ]] && export https_proxy
[[ -n "${http_proxy:-}" ]] && export http_proxy

detect_default_oci_runtime() {
    if command -v docker >/dev/null 2>&1; then
        printf '%s\n' "docker"
    elif command -v podman >/dev/null 2>&1; then
        printf '%s\n' "podman"
    else
        printf '%s\n' "docker"
    fi
}

show_help() {
    cat <<'EOF'
Usage:
  container/build.sh [--runtime docker|podman|apptainer]

Build the Agentic Team container image for the selected container runtime.
EOF
}

RUNTIME="${AR_BUILD_RUNTIME:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --runtime)
            if [[ -z "${2:-}" || "$2" =~ ^- ]]; then
                echo "Error: --runtime requires a value (docker|podman|apptainer)." >&2
                exit 1
            fi
            RUNTIME="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "Error: Unknown build option: $1" >&2
            echo "" >&2
            show_help >&2
            exit 1
            ;;
    esac
done

if [[ -z "$RUNTIME" ]]; then
    RUNTIME="$(detect_default_oci_runtime)"
    if [[ "$RUNTIME" == "podman" ]] && ! command -v docker >/dev/null 2>&1; then
        echo "Docker not found, falling back to Podman."
    fi
fi

if ! is_registered_sandbox "$RUNTIME" || [[ "$RUNTIME" == "none" ]]; then
    echo "Error: Unsupported runtime: $RUNTIME" >&2
    echo "Supported runtimes: docker, podman, apptainer" >&2
    exit 1
fi

AR_SANDBOX="$RUNTIME"
sandbox_call_required build_image

echo ""
echo "Run with: agentic-team ~/your-project"
