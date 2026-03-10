"""REST API endpoints for project initialization (Phase 1D).

Provides endpoint for creating new project repositories with git init,
directory structure, and phase-N.md skeleton.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.errors import ProjectInitError
from core.logging import get_logger, set_trace_id

logger = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

PROJECT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


# --- Request/Response models ---


class ProjectInitRequest(BaseModel):
    name: str
    description: str = ""
    base_path: str | None = None


class ProjectInitResponse(BaseModel):
    project_name: str
    repo_path: str
    phase_file: str
    git_initialized: bool


# --- Helpers ---


def _validate_project_name(name: str) -> None:
    """Validate project name against allowlist pattern."""
    if not name:
        raise HTTPException(
            status_code=400,
            detail="Project name must not be empty",
        )
    if ".." in name or "/" in name:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid project name: must match {PROJECT_NAME_PATTERN.pattern}",
        )
    if not PROJECT_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid project name: must match {PROJECT_NAME_PATTERN.pattern}",
        )


def _resolve_base_path(base_path: str | None, config: dict) -> Path:
    """Resolve and validate base_path against config whitelist."""
    init_cfg = config.get("project_initialization", {})
    allowed_paths = init_cfg.get("allowed_base_paths", [])

    if base_path is None:
        if not allowed_paths:
            raise HTTPException(
                status_code=400,
                detail="No allowed_base_paths configured and no base_path provided",
            )
        base_path = allowed_paths[0]

    resolved = Path(base_path).resolve()

    # Check whitelist
    if allowed_paths:
        allowed_resolved = [Path(p).resolve() for p in allowed_paths]
        if not any(resolved == ap or resolved in ap.parents or ap in resolved.parents
                   for ap in allowed_resolved):
            # Strict check: resolved must equal or be a child of an allowed path
            if not any(str(resolved).startswith(str(ap)) for ap in allowed_resolved):
                raise HTTPException(
                    status_code=400,
                    detail=f"Base path not in allowed list: {base_path}",
                )

    if not resolved.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Base path does not exist: {base_path}",
        )

    return resolved


async def _run_git(cmd: list[str], cwd: Path) -> str:
    """Run a git command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        "git", *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise ProjectInitError(
            f"git {' '.join(cmd)} failed: {stderr.decode().strip()}"
        )
    return stdout.decode().strip()


async def _init_project(
    name: str,
    description: str,
    base_path: Path,
    config: dict,
) -> ProjectInitResponse:
    """Create project directory, git init, and phase skeleton."""
    project_dir = base_path / name
    if project_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Project directory already exists: {project_dir}",
        )

    init_cfg = config.get("project_initialization", {})
    git_user = init_cfg.get("git_user", {})
    git_name = git_user.get("name", "Claude Dev Bot")
    git_email = git_user.get("email", "bot@private-agent-platform.local")

    try:
        # Create directories
        project_dir.mkdir(parents=True)
        phases_dir = project_dir / "docs" / "phases"
        phases_dir.mkdir(parents=True)

        # Copy phase template
        template_path = Path("config/templates/phase-template.md")
        phase_file = phases_dir / "phase-1.md"
        if template_path.exists():
            shutil.copy2(template_path, phase_file)
        else:
            phase_file.write_text(
                "# Phase 1: Initial Development\n\n"
                "**目标**: TODO\n\n---\n\n"
                "### Task 1.1: TODO\n\n"
                "**状态**: [ ] 未开始\n"
                "**依赖**: 无\n"
                "**产出文件**: `TODO`\n\n"
                "**描述**:\nTODO\n\n"
                "**验收标准**:\n- [ ] TODO\n\n"
                "**测试命令**:\n```bash\necho TODO\n```\n",
                encoding="utf-8",
            )

        # Create .gitignore
        gitignore = project_dir / ".gitignore"
        gitignore.write_text(
            "# Python\n"
            "__pycache__/\n*.py[cod]\n*$py.class\n*.egg-info/\ndist/\nbuild/\n"
            ".eggs/\n*.egg\n\n"
            "# Environment\n.env\n.env.*\n.venv/\nvenv/\n\n"
            "# IDE\n.idea/\n.vscode/\n*.swp\n*.swo\n\n"
            "# OS\n.DS_Store\nThumbs.db\n",
            encoding="utf-8",
        )

        # Git init
        await _run_git(["init"], cwd=project_dir)
        await _run_git(["config", "user.name", git_name], cwd=project_dir)
        await _run_git(["config", "user.email", git_email], cwd=project_dir)
        await _run_git(["add", "."], cwd=project_dir)
        await _run_git(
            ["commit", "-m", f"init: scaffold project {name}"],
            cwd=project_dir,
        )

        logger.info(
            "Project initialized: %s at %s",
            name,
            project_dir,
        )

        return ProjectInitResponse(
            project_name=name,
            repo_path=str(project_dir),
            phase_file=str(phase_file),
            git_initialized=True,
        )

    except HTTPException:
        raise
    except Exception as e:
        # Cleanup on failure (atomicity guarantee)
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)
            logger.warning("Cleaned up failed project dir: %s", project_dir)
        raise HTTPException(
            status_code=500,
            detail=f"Project initialization failed: {e}",
        ) from e


# --- Endpoint ---


@router.post("/init")
async def init_project(body: ProjectInitRequest, request: Request):
    """Initialize a new project with git repo and phase skeleton."""
    set_trace_id()
    config = getattr(request.app.state, "config", {})

    _validate_project_name(body.name)
    base_path = _resolve_base_path(body.base_path, config)

    result = await _init_project(
        name=body.name,
        description=body.description,
        base_path=base_path,
        config=config,
    )
    return result
