"""Local GPU discovery operations and normalization."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import ArgvTool, CommandResult, WorkflowRecord


class LocalGpuCapacity(WorkflowRecord):
    """Normalized capacity from local NVIDIA and ROCm probes."""

    vendor: Literal["nvidia", "rocm", "none"]
    device_ids: list[str]
    status_text: str = ""


class ReadEnvironmentVariableTool(ArgvTool[CommandResult]):
    argv_template: ClassVar[tuple[str, ...]] = ("sh", "-lc")
    name: str
    default: str = ""

    def argv(self) -> list[str]:
        return [*self.argv_template, f'printf "%s" "${{{self.name}:-{self.default}}}"']


class NvidiaSmiGpuIdsTool(ArgvTool[CommandResult]):
    argv_template: ClassVar[tuple[str, ...]] = (
        "nvidia-smi", "--query-gpu=index", "--format=csv,noheader",
    )


class RocmSmiGpuIdsTool(ArgvTool[CommandResult]):
    argv_template: ClassVar[tuple[str, ...]] = ("rocm-smi", "--showid", "--csv")


def discover_local_gpu_capacity() -> LocalGpuCapacity:
    nvidia: CommandResult = NvidiaSmiGpuIdsTool().run()
    if nvidia.returncode == 0 and nvidia.stdout.strip():
        return LocalGpuCapacity(
            vendor="nvidia",
            device_ids=[line.strip() for line in nvidia.stdout.splitlines() if line.strip()],
            status_text=nvidia.stdout,
        )

    rocm: CommandResult = RocmSmiGpuIdsTool().run()
    if rocm.returncode == 0 and rocm.stdout.strip():
        device_ids = [
            line.split(",", 1)[0].strip()
            for line in rocm.stdout.splitlines()
            if line.lower().startswith(("card", "gpu"))
        ]
        if device_ids:
            return LocalGpuCapacity(vendor="rocm", device_ids=device_ids, status_text=rocm.stdout)

    return LocalGpuCapacity(
        vendor="none",
        device_ids=[],
        status_text="\n".join(text for text in (nvidia.stderr, rocm.stderr) if text),
    )
