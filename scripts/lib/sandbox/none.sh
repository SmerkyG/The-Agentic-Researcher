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
    export_ar_runtime_env

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
    local cli__cmd="$1"
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

    local testfile="$WORKSPACE_DIR/.agentic_team_native_test_$$"
    if touch "$testfile" 2>/dev/null; then
        native_pass "Workspace is writable"
        rm -f "$testfile"
    else
        native_fail "Workspace is not writable"
    fi

    echo ""
    echo "=== CLI ==="
    if command -v "$cli__cmd" >/dev/null 2>&1; then
        native_pass "$cli__cmd found ($(command -v "$cli__cmd"))"
    else
        native_fail "$cli__cmd not found on PATH"
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
            native_fail "remote-run capability requires --sandbox apptainer"
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
    local cli__cmd
    cli__cmd="$(native_cli_command)"

    sandbox_none_setup_environment

    if [[ "$mode" == "test" ]]; then
        sandbox_none_run_test "$cli__cmd"
    fi

    if ! command -v "$cli__cmd" >/dev/null 2>&1; then
        echo "Error: Sandbox none selected, but '$cli__cmd' is not installed or not on PATH."
        echo "Install the selected CLI on the host or use a container sandbox."
        exit 1
    fi

    cd "$WORKSPACE_DIR"
    "$cli__cmd" "${CLI_ARGS[@]}"
}
