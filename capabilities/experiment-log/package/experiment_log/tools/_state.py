"""Private access to the shared Experiment Log state implementation."""

from __future__ import annotations

from pathlib import Path
import sys


LIB_ROOT = Path(__file__).resolve().parents[3] / "lib"
if str(LIB_ROOT) not in sys.path:
    sys.path.insert(0, str(LIB_ROOT))

import experiment_log_common as common  # noqa: E402
import experiment_log_models as models  # noqa: E402


def project_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()
