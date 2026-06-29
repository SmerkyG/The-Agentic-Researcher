#!/bin/bash

register_sandbox_adapter none 40

sandbox_none_image_exists() {
    return 0
}

sandbox_none_build_image() {
    return 0
}

sandbox_none_validate() {
    return 0
}

sandbox_none_setup_environment() {
    export AR_SANDBOX="$AR_SANDBOX"
    export AR_SANDBOX_HOME="$AR_SANDBOX_HOME"
    export AR_INSTALL_DIR
    AR_INSTALL_DIR="$(ar_install_env_path)"
    export AR_NOTES_CLI
    AR_NOTES_CLI="$(ar_notes_cli_env_path)"
    export AR_JOB_BACKEND="${JOB_BACKEND:-none}"
    export AR_CLI_TOOL="$AR_CLI_TOOL"
    export AR_STATE_ROOT="$STATE_ROOT"
    export AR_ORG_NOTES_REPO="${AR_ORG_NOTES_REPO:-}"
    export AR_MAIN_AGENT="${AR_MAIN_AGENT:-research-coordinator}"
    export AR_USER_ID="${AR_USER_ID:-$USER}"
    export AR_PROJECT_ID="${AR_PROJECT_ID:-}"
    export AR_AGENTIC_STATE_BRANCH="${AR_AGENTIC_STATE_BRANCH:-agentic/state}"
    export AR_NOTES_AUTO_REFRESH="${AR_NOTES_AUTO_REFRESH:-true}"
    export AR_NOTES_REFRESH_MODE="${AR_NOTES_REFRESH_MODE:-periodic}"
    export AR_NOTES_REFRESH_INTERVAL_SECONDS="${AR_NOTES_REFRESH_INTERVAL_SECONDS:-120}"
    export AR_RESOLVER_GIT_NAME="${AR_RESOLVER_GIT_NAME:-}"
    export AR_RESOLVER_GIT_EMAIL="${AR_RESOLVER_GIT_EMAIL:-}"
    export AR_NOTES_GIT_NAME="${AR_NOTES_GIT_NAME:-}"
    export AR_NOTES_GIT_EMAIL="${AR_NOTES_GIT_EMAIL:-}"

    if [[ -n "${AR_HTTPS_PROXY:-}" ]]; then
        export https_proxy="$AR_HTTPS_PROXY"
        export http_proxy="${AR_HTTP_PROXY:-$AR_HTTPS_PROXY}"
    fi

    cli_call setup_native_environment

    if [[ -n "${AR_EXTRA_ENV:-}" ]]; then
        local IFS='|'
        local entry
        for entry in $AR_EXTRA_ENV; do
            [[ -n "$entry" ]] && export "$entry"
        done
    fi
}

sandbox_none_run_test() {
    local tool_cmd="$1"
    local pass_count=0
    local fail_count=0
    local warn_count=0

    native_pass() { echo "  [PASS] $1"; pass_count=$((pass_count + 1)); }
    native_fail() { echo "  [FAIL] $1"; fail_count=$((fail_count + 1)); }
    native_warn() { echo "  [WARN] $1"; warn_count=$((warn_count + 1)); }

    echo "=== Sandbox: none ==="
    if [[ "$HOME" != "$AR_SANDBOX_HOME" ]]; then
        native_pass "Using host HOME: $HOME"
    else
        native_warn "HOME is $AR_SANDBOX_HOME; no-sandbox mode normally uses the host HOME"
    fi

    if [[ -d "$WORKSPACE_DIR" ]]; then
        native_pass "Workspace exists: $WORKSPACE_DIR"
    else
        native_fail "Workspace does not exist: $WORKSPACE_DIR"
    fi

    local testfile="$WORKSPACE_DIR/.agentic_researcher_native_test_$$"
    if touch "$testfile" 2>/dev/null; then
        native_pass "Workspace is writable"
        rm -f "$testfile"
    else
        native_fail "Workspace is not writable"
    fi

    echo ""
    echo "=== CLI Tool ==="
    if command -v "$tool_cmd" >/dev/null 2>&1; then
        native_pass "$tool_cmd found ($(command -v "$tool_cmd"))"
    else
        native_fail "$tool_cmd not found on PATH"
    fi

    echo ""
    echo "=== GPU ==="
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
        local gpu_count
        gpu_count=$(nvidia-smi -L 2>/dev/null | wc -l | tr -d ' ')
        native_pass "GPU visible via nvidia-smi ($gpu_count device(s))"
    elif command -v rocm-smi >/dev/null 2>&1 && rocm-smi >/dev/null 2>&1; then
        native_pass "GPU visible via rocm-smi"
    else
        native_warn "No local GPU visible via nvidia-smi or rocm-smi"
    fi

    echo ""
    echo "=== Job Backend: ${JOB_BACKEND:-none} ==="
    case "${JOB_BACKEND:-none}" in
        none)
            native_pass "No external job backend configured"
            ;;
        cluster-run)
            if command -v cluster-run >/dev/null 2>&1 && cluster-run --help >/dev/null 2>&1; then
                native_pass "cluster-run is available"
            else
                native_fail "cluster-run is not available or not runnable"
            fi
            ;;
        remote-run)
            native_fail "remote-run optional skill requires --sandbox apptainer"
            ;;
    esac

    echo ""
    echo "=== Network (optional) ==="
    if command -v curl >/dev/null 2>&1; then
        if curl -sf --max-time 10 https://api.anthropic.com/ >/dev/null 2>&1 || \
           curl -sf --max-time 10 https://www.google.com/ >/dev/null 2>&1; then
            native_pass "Network connectivity (HTTPS)"
        else
            native_warn "No HTTPS connectivity detected"
        fi
    else
        native_warn "curl not found; skipped network check"
    fi

    echo ""
    echo "================================"
    echo "Results: $pass_count passed, $fail_count failed, $warn_count warnings"
    if [[ "$fail_count" -eq 0 ]]; then
        echo "Status: ALL REQUIRED CHECKS PASSED"
        exit 0
    fi

    echo "Status: SOME CHECKS FAILED"
    exit 1
}

sandbox_none_launch() {
    local mode="${1:-run}"
    local tool_cmd
    tool_cmd="$(native_tool_command)"

    sandbox_none_setup_environment

    if [[ "$mode" == "test" ]]; then
        sandbox_none_run_test "$tool_cmd"
    fi

    if ! command -v "$tool_cmd" >/dev/null 2>&1; then
        echo "Error: Sandbox none selected, but '$tool_cmd' is not installed or not on PATH."
        echo "Install the selected CLI tool on the host or use a container sandbox."
        exit 1
    fi

    cd "$WORKSPACE_DIR"
    exec "$tool_cmd" "${TOOL_ARGS[@]}"
}
