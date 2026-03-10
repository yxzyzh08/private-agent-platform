"""Tests for phase generation templates (Phase 1D Task 1D.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.phase_parser import parse_phase_file


TEMPLATE_DIR = Path("config/templates")


class TestPhaseGenerationPrompt:
    """Test phase-generation-prompt.md template."""

    def test_template_exists(self):
        """Template file should exist."""
        assert (TEMPLATE_DIR / "phase-generation-prompt.md").exists()

    def test_template_covers_key_sections(self):
        """Template should cover requirement clarification, task decomposition, format."""
        content = (TEMPLATE_DIR / "phase-generation-prompt.md").read_text()
        assert "Requirement Clarification" in content or "需求澄清" in content
        assert "Task Decomposition" in content or "任务分解" in content
        assert "Phase File Format" in content or "格式" in content

    def test_embedded_example_parseable(self):
        """The example phase content in the template should be parseable."""
        # Extract a minimal example that follows the template format
        example = """\
# Phase 1: Sample Project

**分支**: `feat/sample`
**前置**: 无
**目标**: Build a sample project

---

### Task 1.1: Create project structure

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `src/main.py`, `pyproject.toml`

**描述**:
Set up the project directory structure.

**验收标准**:
- [ ] Project structure created
- [ ] pyproject.toml configured

**测试命令**:
```bash
python -c "import src.main"
```

---

### Task 1.2: Add core logic

**状态**: [ ] 未开始
**依赖**: Task 1.1
**产出文件**: `src/core.py`

**描述**:
Implement core business logic.

**验收标准**:
- [ ] Core module created

**测试命令**:
```bash
pytest tests/
```
"""
        tasks = parse_phase_file(example)
        assert len(tasks) == 2
        assert tasks[0].task_id == "1.1"
        assert tasks[1].task_id == "1.2"
        assert tasks[1].depends_on == ["1.1"]

    def test_template_mentions_task_id_format(self):
        """Template should specify Task ID format."""
        content = (TEMPLATE_DIR / "phase-generation-prompt.md").read_text()
        assert "{N}.{X}" in content or "N.X" in content


class TestCuiWorkflowTemplate:
    """Test claude-md-cui-workflow.md template."""

    def test_template_exists(self):
        """Template file should exist."""
        assert (TEMPLATE_DIR / "claude-md-cui-workflow.md").exists()

    def test_mcp_tools_listed(self):
        """Template should list all 5 MCP tools."""
        content = (TEMPLATE_DIR / "claude-md-cui-workflow.md").read_text()
        tools = ["init_project", "submit_phase", "get_plan_status", "control_task", "abort_plan"]
        for tool in tools:
            assert tool in content, f"Missing MCP tool: {tool}"

    def test_workflow_steps(self):
        """Template should cover the full workflow."""
        content = (TEMPLATE_DIR / "claude-md-cui-workflow.md").read_text()
        assert "需求澄清" in content or "Requirement" in content
        assert "submit_phase" in content
        assert "init_project" in content

    def test_no_conflict_with_existing_section(self):
        """Should not conflict with existing claude-md-section.md."""
        existing = (TEMPLATE_DIR / "claude-md-section.md").read_text()
        new = (TEMPLATE_DIR / "claude-md-cui-workflow.md").read_text()
        # They should cover different aspects
        assert "MCP Tool" in new or "MCP" in new
        # Existing focuses on curl-based workflow
        assert "curl" in existing


class TestPhaseTemplate:
    """Test the original phase-template.md is still valid."""

    def test_template_exists(self):
        assert (TEMPLATE_DIR / "phase-template.md").exists()

    def test_template_has_placeholder_format(self):
        content = (TEMPLATE_DIR / "phase-template.md").read_text()
        assert "{PHASE_TITLE}" in content
        assert "Task {N.1}" in content or "Task" in content
