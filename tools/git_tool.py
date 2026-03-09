"""Git tool — repository operations and GitHub API.

Supports clone, checkout, commit, push, and PR creation via PyGitHub.
"""

from __future__ import annotations

import asyncio
import os
import time

from core.audit import log_tool_call
from tools.base import BaseTool, ToolResult

_VALID_OPERATIONS = ("clone", "checkout", "commit", "push", "create_pr", "create_issue")


class GitTool(BaseTool):
    """Git repository operations and GitHub PR management."""

    name = "git"
    description = "Perform git operations: clone, checkout, commit, push, create_pr"
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": list(_VALID_OPERATIONS),
                "description": "The git operation to perform",
            },
            "repo_url": {"type": "string", "description": "Repository URL (for clone)"},
            "branch": {"type": "string", "description": "Branch name (for checkout)"},
            "message": {"type": "string", "description": "Commit message (for commit)"},
            "working_directory": {"type": "string", "description": "Repository working directory"},
            "pr_title": {"type": "string", "description": "PR title (for create_pr)"},
            "pr_body": {"type": "string", "description": "PR body (for create_pr)"},
            "pr_base": {"type": "string", "description": "PR base branch (default: main)"},
            "pr_head": {"type": "string", "description": "PR head branch (for create_pr)"},
            "repo_owner": {"type": "string", "description": "GitHub repo owner"},
            "repo_name": {"type": "string", "description": "GitHub repo name"},
            "issue_title": {"type": "string", "description": "Issue title (for create_issue)"},
            "issue_body": {"type": "string", "description": "Issue body (for create_issue)"},
        },
        "required": ["operation"],
    }

    async def execute(self, params: dict) -> ToolResult:
        await self.validate_input(params)
        start_time = time.monotonic()

        operation = params["operation"]
        handlers = {
            "clone": self._clone,
            "checkout": self._checkout,
            "commit": self._commit,
            "push": self._push,
            "create_pr": self._create_pr,
            "create_issue": self._create_issue,
        }

        handler = handlers.get(operation)
        if not handler:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")

        result = await handler(params)
        duration_ms = int((time.monotonic() - start_time) * 1000)
        log_tool_call(
            agent_id="unknown",
            tool_name=self.name,
            params=params,
            result_status="success" if result.success else "error",
            duration_ms=duration_ms,
        )
        return result

    async def _run_git(self, args: list[str], cwd: str = ".") -> tuple[int, str, str]:
        """Run a git command as async subprocess."""
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await process.communicate()
        return (
            process.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def _clone(self, params: dict) -> ToolResult:
        repo_url = params.get("repo_url")
        if not repo_url:
            return ToolResult(success=False, error="repo_url is required for clone")

        cwd = params.get("working_directory", ".")
        returncode, stdout, stderr = await self._run_git(["clone", repo_url], cwd=cwd)
        if returncode != 0:
            return ToolResult(success=False, error=f"git clone failed: {stderr}")
        return ToolResult(success=True, data={"output": stdout.strip()})

    async def _checkout(self, params: dict) -> ToolResult:
        branch = params.get("branch")
        if not branch:
            return ToolResult(success=False, error="branch is required for checkout")

        cwd = params.get("working_directory", ".")
        returncode, stdout, stderr = await self._run_git(["checkout", branch], cwd=cwd)
        if returncode != 0:
            # Try creating the branch
            returncode, stdout, stderr = await self._run_git(["checkout", "-b", branch], cwd=cwd)
            if returncode != 0:
                return ToolResult(success=False, error=f"git checkout failed: {stderr}")
        return ToolResult(success=True, data={"branch": branch})

    async def _commit(self, params: dict) -> ToolResult:
        message = params.get("message")
        if not message:
            return ToolResult(success=False, error="message is required for commit")

        cwd = params.get("working_directory", ".")
        # Stage all changes
        returncode, _, stderr = await self._run_git(["add", "-A"], cwd=cwd)
        if returncode != 0:
            return ToolResult(success=False, error=f"git add failed: {stderr}")

        returncode, stdout, stderr = await self._run_git(["commit", "-m", message], cwd=cwd)
        if returncode != 0:
            return ToolResult(success=False, error=f"git commit failed: {stderr}")
        return ToolResult(success=True, data={"output": stdout.strip()})

    async def _push(self, params: dict) -> ToolResult:
        cwd = params.get("working_directory", ".")
        branch = params.get("branch")
        args = ["push"]
        if branch:
            args.extend(["origin", branch])

        returncode, stdout, stderr = await self._run_git(args, cwd=cwd)
        if returncode != 0:
            return ToolResult(success=False, error=f"git push failed: {stderr}")
        return ToolResult(success=True, data={"output": (stdout or stderr).strip()})

    async def _create_pr(self, params: dict) -> ToolResult:
        """Create a GitHub PR using PyGitHub."""
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            return ToolResult(success=False, error="GITHUB_TOKEN environment variable not set")

        required = ["repo_owner", "repo_name", "pr_title", "pr_head"]
        missing = [k for k in required if not params.get(k)]
        if missing:
            return ToolResult(success=False, error=f"Missing required params: {', '.join(missing)}")

        try:
            from github import Github

            g = Github(token)
            repo = g.get_repo(f"{params['repo_owner']}/{params['repo_name']}")
            pr = repo.create_pull(
                title=params["pr_title"],
                body=params.get("pr_body", ""),
                base=params.get("pr_base", "main"),
                head=params["pr_head"],
            )
            return ToolResult(success=True, data={"pr_url": pr.html_url, "pr_number": pr.number})
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to create PR: {e}")

    async def _create_issue(self, params: dict) -> ToolResult:
        """Create a GitHub Issue using PyGitHub."""
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            return ToolResult(success=False, error="GITHUB_TOKEN environment variable not set")

        required = ["repo_owner", "repo_name", "issue_title"]
        missing = [k for k in required if not params.get(k)]
        if missing:
            return ToolResult(success=False, error=f"Missing required params: {', '.join(missing)}")

        try:
            from github import Github

            g = Github(token)
            repo = g.get_repo(f"{params['repo_owner']}/{params['repo_name']}")
            issue = repo.create_issue(
                title=params["issue_title"],
                body=params.get("issue_body", ""),
            )
            return ToolResult(
                success=True,
                data={
                    "issue_url": issue.html_url,
                    "issue_number": issue.number,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to create issue: {e}")
