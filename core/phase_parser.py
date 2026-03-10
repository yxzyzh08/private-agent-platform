"""Phase file parser — markdown to task data structures.

Parses phase-N.md files into structured task data. Provides writeback
functionality to update task status checkboxes in the markdown.
Uses only re + dataclasses (no external dependencies).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from core.errors import PhaseParseError
from core.logging import get_logger
from core.task_planner import SubTask

logger = get_logger(__name__)

# --- Regex patterns ---

_TASK_HEADER = re.compile(r"^### Task ([\w.]+):\s*(.+)", re.MULTILINE)
_STATUS = re.compile(r"^\*\*状态\*\*:\s*\[([ x])\]", re.MULTILINE)
_DEPENDS = re.compile(r"^\*\*依赖\*\*:\s*(.+)", re.MULTILINE)
_OUTPUT = re.compile(r"^\*\*产出文件\*\*:\s*(.+)", re.MULTILINE)
_TASK_ID_REF = re.compile(r"Task ([\w.]+)")
_BACKTICK_PATH = re.compile(r"`([^`]+)`")


@dataclass
class PhaseTask:
    """Raw task data parsed from markdown."""

    task_id: str
    title: str
    status: str  # "x" or " "
    depends_on: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    description: str = ""
    validation_command: str | None = None
    line_start: int = 0


def _extract_test_command(block: str) -> str | None:
    """Extract the last ```bash code block from a task block."""
    # Find all ```bash blocks, take the last one (usually the test command)
    parts = block.split("```bash")
    if len(parts) < 2:
        return None
    # The last ```bash block
    last_block = parts[-1]
    end = last_block.find("```")
    if end == -1:
        return None
    cmd = last_block[:end].strip()
    return cmd if cmd else None


def _parse_depends(text: str) -> list[str]:
    """Parse dependency field, extracting Task IDs."""
    text = text.strip()
    if text == "无" or text.lower() == "none":
        return []
    # Extract all Task X.Y references, ignoring parenthetical notes and Phase refs
    return _TASK_ID_REF.findall(text)


def _parse_output_files(text: str) -> list[str]:
    """Parse output files from backtick-wrapped paths."""
    return _BACKTICK_PATH.findall(text.strip())


def parse_phase_file(content: str) -> list[PhaseTask]:
    """Parse phase-N.md content into a list of PhaseTask objects.

    Raises:
        PhaseParseError: If no tasks are found.
    """
    tasks, errors = _parse_phase_content(content)
    if not tasks and not errors:
        raise PhaseParseError("No tasks found in phase file")
    if errors and not tasks:
        raise PhaseParseError(f"All tasks failed to parse: {errors}")
    return tasks


def parse_phase_file_safe(file_path: str) -> tuple[list[PhaseTask], list[str]]:
    """Safe version: returns (tasks, errors). Partial failures don't block."""
    path = Path(file_path)
    if not path.exists():
        return [], [f"File not found: {file_path}"]
    content = path.read_text(encoding="utf-8")
    return _parse_phase_content(content)


def _parse_phase_content(content: str) -> tuple[list[PhaseTask], list[str]]:
    """Internal parser. Returns (tasks, errors)."""
    lines = content.split("\n")
    tasks: list[PhaseTask] = []
    errors: list[str] = []

    # Find all task header positions
    header_positions: list[tuple[int, str, str]] = []  # (line_idx, task_id, title)
    for i, line in enumerate(lines):
        m = _TASK_HEADER.match(line)
        if m:
            header_positions.append((i, m.group(1), m.group(2).strip()))

    # Parse each task block
    for idx, (line_idx, task_id, title) in enumerate(header_positions):
        # Task block extends to next header or end of file
        end_idx = (
            header_positions[idx + 1][0] if idx + 1 < len(header_positions) else len(lines)
        )
        block = "\n".join(lines[line_idx:end_idx])

        try:
            task = _parse_task_block(block, task_id, title, line_idx + 1)
            tasks.append(task)
        except Exception as e:
            errors.append(f"Task {task_id}: {e}")
            logger.warning("Failed to parse task %s: %s", task_id, e)

    return tasks, errors


def _parse_task_block(
    block: str, task_id: str, title: str, line_start: int
) -> PhaseTask:
    """Parse a single task block into a PhaseTask."""
    # Status
    status_match = _STATUS.search(block)
    status = status_match.group(1) if status_match else " "

    # Dependencies
    dep_match = _DEPENDS.search(block)
    depends_on = _parse_depends(dep_match.group(1)) if dep_match else []

    # Output files
    out_match = _OUTPUT.search(block)
    output_files = _parse_output_files(out_match.group(1)) if out_match else []

    # Description: everything between the metadata fields and the end
    # Find the **描述**: marker
    desc_match = re.search(r"^\*\*描述\*\*:\s*\n?", block, re.MULTILINE)
    description = ""
    if desc_match:
        # Description is from after **描述**: to end of block
        description = block[desc_match.end():].strip()

    # Validation command
    validation_command = _extract_test_command(block)

    return PhaseTask(
        task_id=task_id,
        title=title,
        status=status,
        depends_on=depends_on,
        output_files=output_files,
        description=description,
        validation_command=validation_command,
        line_start=line_start,
    )


def update_task_status(
    file_path: str, task_id: str, new_status: str = "x"
) -> bool:
    """Update a task's checkbox in the markdown file.

    Args:
        file_path: Path to the phase-N.md file.
        task_id: The task ID to update (e.g., "1C.3").
        new_status: "x" for completed, " " for pending.

    Returns:
        True if the status was updated, False if task not found.
    """
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Find the task header line
    header_pattern = re.compile(rf"^### Task {re.escape(task_id)}:\s")
    task_line_idx = None
    for i, line in enumerate(lines):
        if header_pattern.match(line):
            task_line_idx = i
            break

    if task_line_idx is None:
        return False

    # Find the status line within the next few lines
    old_check = "[x]" if new_status == " " else "[ ]"
    new_check = f"[{new_status}]"
    for i in range(task_line_idx + 1, min(task_line_idx + 5, len(lines))):
        if lines[i].startswith("**状态**:") and old_check in lines[i]:
            lines[i] = lines[i].replace(old_check, new_check, 1)
            path.write_text("\n".join(lines), encoding="utf-8")
            logger.info("Updated task %s status to [%s]", task_id, new_status)
            return True

    # Already in the desired status
    for i in range(task_line_idx + 1, min(task_line_idx + 5, len(lines))):
        if lines[i].startswith("**状态**:") and new_check in lines[i]:
            return True  # idempotent

    return False


def phase_tasks_to_subtasks(tasks: list[PhaseTask]) -> list[SubTask]:
    """Convert PhaseTask list to SubTask list with runtime defaults."""
    return [
        SubTask(
            task_id=t.task_id,
            title=t.title,
            description=t.description,
            status="completed" if t.status == "x" else "pending",
            depends_on=t.depends_on,
            output_files=t.output_files,
            validation_command=t.validation_command,
        )
        for t in tasks
    ]
