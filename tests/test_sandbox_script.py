from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_SANDBOX = REPO_ROOT / "scripts" / "test_sandbox.sh"


def test_test_sandbox_accepts_codex_login_status_without_api_key() -> None:
    script = TEST_SANDBOX.read_text()

    assert 'codex login status >/dev/null 2>&1' in script
    assert 'pass "Codex login session is available"' in script
    assert 'fail "OPENAI_API_KEY is not set and no Codex login session is available"' in script


def test_test_sandbox_checks_rocm_after_nvidia() -> None:
    script = TEST_SANDBOX.read_text()

    assert "command -v rocm-smi" in script
    assert 'pass "GPU available via rocm-smi"' in script
    assert "nvidia-smi and rocm-smi not found" in script
