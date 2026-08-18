"""Native research report append operation."""

from __future__ import annotations

import os
from pathlib import Path
import re

from agentic_tools import PythonTool, Record, Value


PAGE_PATTERN = re.compile(r"report_page(\d+)\.md")


class ReportAppendResult(Record):
    page: str
    page_number: int
    created: bool
    previous_lines: int
    lines: int


def _line_count(text: str) -> int:
    return len(text.splitlines())


def _report_pages(branch_records_dir: Path) -> list[tuple[int, Path]]:
    pages: list[tuple[int, Path]] = []
    for path in branch_records_dir.glob("report_page*.md"):
        match = PAGE_PATTERN.fullmatch(path.name)
        if match:
            pages.append((int(match.group(1)), path))
    return sorted(pages)


def _append_section(page: Path, content: str) -> None:
    existing = page.read_text(encoding="utf-8") if page.exists() else ""
    separator = "\n\n" if existing.rstrip() else ""
    page.write_text(
        existing.rstrip() + separator + content.strip() + "\n",
        encoding="utf-8",
    )


class ReportAppendTool(PythonTool[ReportAppendResult]):
    """Append one section to the latest numbered research report page."""

    content: str = Value("Complete report section to append")
    branch_records_dir: str | None = Value(
        "Explicit branch records directory, or null to use AR_BRANCH_RECORDS_DIR",
        default=None,
    )
    max_lines: int = Value(
        "Line count at which a new numbered report page is started",
        default=300,
    )

    def execute(self) -> ReportAppendResult:
        content = self.content.strip()
        if not content:
            raise ValueError("content must be a non-empty string")
        if (
            not isinstance(self.max_lines, int)
            or isinstance(self.max_lines, bool)
            or self.max_lines < 1
        ):
            raise ValueError("max_lines must be a positive integer")

        work_state_value = self.branch_records_dir or os.environ.get("AR_BRANCH_RECORDS_DIR")
        if not work_state_value:
            raise ValueError("branch_records_dir or AR_BRANCH_RECORDS_DIR is required")
        branch_records_dir = Path(work_state_value).expanduser().resolve()
        if not branch_records_dir.is_dir():
            raise ValueError(f"branch records directory does not exist: {branch_records_dir}")

        pages = _report_pages(branch_records_dir)
        previous_lines = (
            _line_count(pages[-1][1].read_text(encoding="utf-8"))
            if pages
            else 0
        )
        if not pages or previous_lines >= self.max_lines:
            page_number = pages[-1][0] + 1 if pages else 1
            page = branch_records_dir / f"report_page{page_number}.md"
            created = True
        else:
            page_number, page = pages[-1]
            created = False

        _append_section(page, content)
        return ReportAppendResult(
            page=str(page),
            page_number=page_number,
            created=created,
            previous_lines=previous_lines,
            lines=_line_count(page.read_text(encoding="utf-8")),
        )
