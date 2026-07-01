#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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

case "$RUNTIME" in
    docker|podman|apptainer)
        ;;
    *)
        echo "Error: Unsupported runtime: $RUNTIME" >&2
        echo "Supported runtimes: docker, podman, apptainer" >&2
        exit 1
        ;;
esac

if [[ "$RUNTIME" == "docker" || "$RUNTIME" == "podman" ]]; then
    if ! command -v "$RUNTIME" >/dev/null 2>&1; then
        echo "Error: '$RUNTIME' is not installed or not on PATH."
        echo ""
        echo "Install $RUNTIME on the host, then rerun:"
        echo "  container/build.sh --runtime $RUNTIME"
        exit 1
    fi

    first_char="${RUNTIME%${RUNTIME#?}}"
    rest="${RUNTIME#?}"
    first_char_upper="$(printf '%s' "$first_char" | tr '[:lower:]' '[:upper:]')"
    runtime_name="${first_char_upper}${rest}"
    echo "Building ${runtime_name} container..."
    if [[ "$RUNTIME" == "podman" ]]; then
        "$RUNTIME" build --format docker -t agentic-team:latest "$SCRIPT_DIR"
    else
        "$RUNTIME" build -t agentic-team:latest "$SCRIPT_DIR"
    fi
    echo ""
    echo "${runtime_name} image built: agentic-team:latest"
else
    if [[ "$(uname -s)" != "Linux" ]]; then
        echo "Error: Apptainer builds are only supported on Linux hosts. Current host: $(uname -s)"
        echo ""
        echo "Use Docker on this machine:"
        echo "  container/build.sh --runtime docker"
        exit 1
    fi
    if ! command -v apptainer >/dev/null 2>&1; then
        echo "Error: 'apptainer' is not installed or not on PATH."
        echo ""
        echo "Install Apptainer on the Linux host, then rerun:"
        echo "  container/build.sh --runtime apptainer"
        exit 1
    fi

    # Apptainer needs writable tmp with enough space for the build
    STATE_ROOT="${AR_STATE_ROOT:-$HOME/.cache/agentic-team}"
    export APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-$STATE_ROOT/apptainer_cache}"
    export APPTAINER_TMPDIR="${APPTAINER_TMPDIR:-$STATE_ROOT/apptainer_tmp}"
    mkdir -p "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR"

    echo "Building Apptainer container..."
    echo "This may take 5-10 minutes on first build."
    echo ""

    apptainer build \
        --force \
        "$SCRIPT_DIR/agentic_team.sif" \
        "$SCRIPT_DIR/agentic_team.def"

    echo ""
    echo "Container built successfully: $SCRIPT_DIR/agentic_team.sif"

    # SECURITY: Generate integrity checksum
    echo "Generating integrity checksum..."
    (cd "$SCRIPT_DIR" && sha256sum agentic_team.sif > agentic_team.sif.sha256)
    echo "Checksum saved to: $SCRIPT_DIR/agentic_team.sif.sha256"
fi

echo ""
echo "Run with: agentic-team ~/your-project"
