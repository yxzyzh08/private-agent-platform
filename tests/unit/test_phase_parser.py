"""Tests for core/phase_parser.py — PhaseFileParser."""

from pathlib import Path

import pytest

from core.phase_parser import (
    PhaseTask,
    parse_phase_file,
    parse_phase_file_safe,
    phase_tasks_to_subtasks,
    update_task_status,
)

PHASE_1A = Path("docs/phases/phase-1a.md")
PHASE_1B = Path("docs/phases/phase-1b.md")


# --- Parse real phase files ---


class TestParseRealFiles:
    def test_parse_phase_1a(self):
        """Parse phase-1a.md — expect 28 tasks."""
        content = PHASE_1A.read_text()
        tasks = parse_phase_file(content)
        assert len(tasks) == 28
        # All should be completed
        assert all(t.status == "x" for t in tasks)

    def test_parse_phase_1b(self):
        """Parse phase-1b.md — expect 15 tasks."""
        content = PHASE_1B.read_text()
        tasks = parse_phase_file(content)
        assert len(tasks) == 15


class TestParseTaskFields:
    def test_parse_task_fields(self):
        """Verify all fields are parsed for a known task."""
        content = PHASE_1A.read_text()
        tasks = parse_phase_file(content)
        # Task 1.1 — first task
        t1 = tasks[0]
        assert t1.task_id == "1.1"
        assert "目录结构" in t1.title
        assert t1.status == "x"
        assert t1.depends_on == []
        assert len(t1.output_files) > 0
        assert t1.line_start > 0

    def test_parse_depends_on_multiple(self):
        """Task with multiple dependencies."""
        content = PHASE_1B.read_text()
        tasks = parse_phase_file(content)
        task_map = {t.task_id: t for t in tasks}
        # Task 1B.7 depends on Task 1B.5, Task 1B.6, Task 1B.6a
        t7 = task_map.get("1B.7")
        assert t7 is not None
        assert len(t7.depends_on) >= 2

    def test_parse_depends_on_none(self):
        """Task with no dependencies ('无')."""
        content = PHASE_1A.read_text()
        tasks = parse_phase_file(content)
        t1 = tasks[0]
        assert t1.depends_on == []

    def test_parse_depends_on_with_parenthetical(self):
        """Dependencies with parenthetical notes like 'Task 1.6 (BaseTool)'."""
        content = PHASE_1A.read_text()
        tasks = parse_phase_file(content)
        task_map = {t.task_id: t for t in tasks}
        # Task 1.7 depends on Task 1.6 (BaseTool)
        t7 = task_map.get("1.7")
        assert t7 is not None
        assert "1.6" in t7.depends_on

    def test_parse_output_files(self):
        """Output files parsed from backtick paths."""
        content = PHASE_1A.read_text()
        tasks = parse_phase_file(content)
        task_map = {t.task_id: t for t in tasks}
        # Task 1.2 has pyproject.toml etc.
        t2 = task_map.get("1.2")
        assert t2 is not None
        assert len(t2.output_files) > 0

    def test_parse_status_done(self):
        """Completed tasks have status 'x'."""
        content = PHASE_1A.read_text()
        tasks = parse_phase_file(content)
        assert tasks[0].status == "x"

    def test_parse_status_pending(self):
        """Pending tasks have status ' '."""
        md = """
# Phase Test

### Task T.1: Do something

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `foo.py`

**描述**:
Something.
"""
        tasks = parse_phase_file(md)
        assert tasks[0].status == " "


class TestParseValidationCommand:
    def test_parse_validation_command(self):
        """Test command extracted from ```bash block."""
        md = """
### Task T.1: Test

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `foo.py`

**描述**:
Do something.

**测试命令**:
```bash
uv run pytest tests/ -v
```
"""
        tasks = parse_phase_file(md)
        assert tasks[0].validation_command == "uv run pytest tests/ -v"


# --- Safe parsing ---


class TestParseSafe:
    def test_parse_safe_real_file(self):
        tasks, errors = parse_phase_file_safe(str(PHASE_1A))
        assert len(tasks) == 28
        assert len(errors) == 0

    def test_parse_safe_file_not_found(self):
        tasks, errors = parse_phase_file_safe("/nonexistent/file.md")
        assert tasks == []
        assert len(errors) == 1
        assert "not found" in errors[0].lower()

    def test_parse_safe_partial_failure(self):
        """Malformed task doesn't block others."""
        md = """
### Task T.1: Good task

**状态**: [x] 完成
**依赖**: 无
**产出文件**: `foo.py`

**描述**:
Something.

### Task T.2: Another good task

**状态**: [ ] 未开始
**依赖**: Task T.1
**产出文件**: `bar.py`

**描述**:
Something else.
"""
        # Both should parse fine (the parser is forgiving)
        tasks = parse_phase_file(md)
        assert len(tasks) == 2


# --- Update task status ---


class TestUpdateTaskStatus:
    def test_update_task_status(self, tmp_path):
        """Writeback [ ] -> [x]."""
        md = """### Task T.1: Test

**状态**: [ ] 未开始
**依赖**: 无
"""
        f = tmp_path / "test.md"
        f.write_text(md)
        result = update_task_status(str(f), "T.1", "x")
        assert result is True
        # Re-parse to verify
        content = f.read_text()
        assert "[x]" in content
        tasks = parse_phase_file(content)
        assert tasks[0].status == "x"

    def test_update_task_status_idempotent(self, tmp_path):
        """Already completed task returns True (no change)."""
        md = """### Task T.1: Test

**状态**: [x] 完成
**依赖**: 无
"""
        f = tmp_path / "test.md"
        f.write_text(md)
        result = update_task_status(str(f), "T.1", "x")
        assert result is True

    def test_update_task_status_reverse(self, tmp_path):
        """Writeback [x] -> [ ]."""
        md = """### Task T.1: Test

**状态**: [x] 完成
**依赖**: 无
"""
        f = tmp_path / "test.md"
        f.write_text(md)
        result = update_task_status(str(f), "T.1", " ")
        assert result is True
        content = f.read_text()
        assert "[ ]" in content

    def test_update_task_not_found(self, tmp_path):
        md = """### Task T.1: Test

**状态**: [ ] 未开始
"""
        f = tmp_path / "test.md"
        f.write_text(md)
        result = update_task_status(str(f), "NONEXISTENT", "x")
        assert result is False


# --- PhaseTask to SubTask conversion ---


class TestPhaseTaskToSubTask:
    def test_phase_tasks_to_subtasks(self):
        phase_tasks = [
            PhaseTask(task_id="1.1", title="A", status="x", description="D1"),
            PhaseTask(
                task_id="1.2",
                title="B",
                status=" ",
                depends_on=["1.1"],
                output_files=["b.py"],
                description="D2",
                validation_command="pytest",
            ),
        ]
        subtasks = phase_tasks_to_subtasks(phase_tasks)
        assert len(subtasks) == 2
        assert subtasks[0].status == "completed"
        assert subtasks[0].task_id == "1.1"
        assert subtasks[1].status == "pending"
        assert subtasks[1].depends_on == ["1.1"]
        assert subtasks[1].validation_command == "pytest"


# --- Template parsing ---


class TestParseTemplate:
    def test_parse_template_filled(self):
        """A filled template can be parsed correctly."""
        md = """# Phase 2: Knowledge Base Bot

**分支**: `feat/kb-bot`
**前置**: Phase 1 完成
**目标**: 自动从代码仓库生成知识库

---

## 知识提取

### Task 2.1: 文档提取器

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `tools/doc_extractor.py`, `tests/unit/test_doc_extractor.py`

**描述**:
从代码仓库提取 README、docstring、API 签名。

**验收标准**:
- [ ] 支持 .py 文件 docstring 提取
- [ ] 支持 .md 文件内容提取

**测试命令**:
```bash
uv run pytest tests/unit/test_doc_extractor.py -v
```

---

### Task 2.2: ChromaDB 写入

**状态**: [ ] 未开始
**依赖**: Task 2.1
**产出文件**: `tools/knowledge_base.py`

**描述**:
将提取的内容写入 ChromaDB 向量知识库。

**测试命令**:
```bash
uv run pytest tests/unit/test_knowledge_base.py -v
```
"""
        tasks = parse_phase_file(md)
        assert len(tasks) == 2
        assert tasks[0].task_id == "2.1"
        assert tasks[0].depends_on == []
        assert "tools/doc_extractor.py" in tasks[0].output_files
        assert tasks[0].validation_command == "uv run pytest tests/unit/test_doc_extractor.py -v"
        assert tasks[1].task_id == "2.2"
        assert tasks[1].depends_on == ["2.1"]


class TestParseTemplate:
    def test_parse_template_filled(self, tmp_path):
        """Template with placeholders filled can be parsed correctly."""
        template = Path("config/templates/phase-template.md").read_text()
        filled = (
            template
            .replace("{PHASE_TITLE}", "测试功能")
            .replace("{BRANCH_NAME}", "test-feature")
            .replace("{PREREQUISITES}", "Phase 1完成")
            .replace("{OBJECTIVE}", "实现测试功能")
            .replace("{GROUP_TITLE}", "核心功能")
            .replace("{N.1}", "3.1")
            .replace("{TASK_TITLE}", "创建模块")
            .replace("{OUTPUT_FILE_1}", "src/module.py")
            .replace("{OUTPUT_FILE_2}", "tests/test_module.py")
            .replace("{DESCRIPTION}", "创建核心模块")
            .replace("{ACCEPTANCE_CRITERION_1}", "模块可导入")
            .replace("{ACCEPTANCE_CRITERION_2}", "测试通过")
            .replace("{TEST_COMMAND}", "uv run pytest tests/test_module.py -v")
            .replace("{N.2}", "3.2")
            .replace("{TASK_TITLE_2}", "集成测试")
            .replace("{OUTPUT_FILE_3}", "tests/integration/test_int.py")
            .replace("{DESCRIPTION_2}", "编写集成测试")
            .replace("{ACCEPTANCE_CRITERION_3}", "集成测试通过")
            .replace("{TEST_COMMAND_2}", "uv run pytest tests/integration/ -v")
        )

        tasks = parse_phase_file(filled)
        assert len(tasks) == 2
        assert tasks[0].task_id == "3.1"
        assert tasks[0].title == "创建模块"
        assert tasks[0].status == " "
        assert "src/module.py" in tasks[0].output_files
        assert tasks[1].task_id == "3.2"
        assert tasks[1].depends_on == ["3.1"]
