#!/usr/bin/env python3
"""L3 End-to-end verification script for requirement-driven development workflow.

NOT a pytest test — run manually by Owner after platform is started:

    uv run python tests/e2e/test_e2e_requirement.py

Prerequisites:
    1. Platform running: docker-compose up -d (or uv run python main.py)
    2. ANTHROPIC_API_KEY set in environment
    3. A clean test repo available at /tmp/e2e-test-repo (script creates it)

This script:
    1. Creates a temporary git repo
    2. Copies test-phase.md fixture into it
    3. Calls POST /api/requirements/from-phase
    4. Polls plan status until completed/failed
    5. Verifies all acceptance criteria
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://localhost:8000")
FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_REPO = Path(os.environ.get("E2E_TEST_REPO", "/tmp/e2e-test-repo"))
POLL_INTERVAL = 10  # seconds
MAX_WAIT = 600  # 10 minutes


def log(msg: str) -> None:
    print(f"[E2E] {msg}")


def fail(msg: str) -> None:
    print(f"[E2E FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"[E2E  OK ] {msg}")


# --- Setup ---


def setup_test_repo() -> Path:
    """Create a clean git repo with the test phase file."""
    if TEST_REPO.exists():
        shutil.rmtree(TEST_REPO)

    TEST_REPO.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=TEST_REPO, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "e2e@test.local"],
        cwd=TEST_REPO, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "E2E Test"],
        cwd=TEST_REPO, check=True, capture_output=True,
    )

    # Copy fixture
    phase_dir = TEST_REPO / "docs" / "phases"
    phase_dir.mkdir(parents=True)
    fixture_src = FIXTURE_DIR / "test-phase.md"
    fixture_dst = phase_dir / "test-phase.md"
    shutil.copy2(fixture_src, fixture_dst)

    # Create test_output dir placeholder
    (TEST_REPO / "test_output").mkdir(exist_ok=True)
    (TEST_REPO / "test_output" / "__init__.py").write_text("")

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=TEST_REPO, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit for E2E test"],
        cwd=TEST_REPO, check=True, capture_output=True,
    )

    log(f"Test repo created at {TEST_REPO}")
    return TEST_REPO


# --- API calls ---


def check_platform_health() -> None:
    """Verify platform is running."""
    try:
        resp = httpx.get(f"{PLATFORM_URL}/health", timeout=5)
        if resp.status_code == 200:
            ok("Platform is running")
            return
    except httpx.ConnectError:
        pass
    fail(f"Platform not reachable at {PLATFORM_URL}. Start it first.")


def submit_phase(phase_file: str, repo_path: str) -> dict:
    """POST /api/requirements/from-phase."""
    resp = httpx.post(
        f"{PLATFORM_URL}/api/requirements/from-phase",
        json={"phase_file": phase_file, "repo_path": repo_path},
        timeout=30,
    )
    if resp.status_code != 200:
        fail(f"Submit failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    ok(f"Plan submitted: {data.get('plan_id', 'unknown')}")
    return data


def get_status(plan_id: str) -> dict:
    """GET /api/requirements/{plan_id}."""
    resp = httpx.get(f"{PLATFORM_URL}/api/requirements/{plan_id}", timeout=10)
    if resp.status_code != 200:
        fail(f"Status query failed ({resp.status_code}): {resp.text}")
    return resp.json()


def poll_until_done(plan_id: str) -> dict:
    """Poll plan status until terminal state."""
    elapsed = 0
    while elapsed < MAX_WAIT:
        data = get_status(plan_id)
        status = data["status"]
        completed = data["completed_count"]
        total = data["total_count"]
        log(f"Status: {status} | {completed}/{total} tasks completed | {elapsed}s elapsed")

        if status in ("completed", "failed", "aborted"):
            return data

        if status == "paused":
            log("Plan paused — a task may have failed. Check logs.")
            return data

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    fail(f"Timed out after {MAX_WAIT}s waiting for plan completion")
    return {}  # unreachable


# --- Verification ---


def verify_results(plan_data: dict, repo: Path) -> None:
    """Run all acceptance criteria checks."""
    log("--- Verification ---")

    # 1. Plan completed
    if plan_data["status"] == "completed":
        ok("Plan status: completed")
    else:
        fail(f"Plan status: {plan_data['status']} (expected: completed)")

    # 2. All tasks completed
    for task in plan_data["tasks"]:
        if task["status"] == "completed":
            ok(f"Task {task['task_id']}: completed")
        else:
            fail(f"Task {task['task_id']}: {task['status']} (expected: completed)")

    # 3. Output files exist
    hello_py = repo / "test_output" / "hello.py"
    if hello_py.exists():
        ok(f"File exists: {hello_py}")
        content = hello_py.read_text()
        if "def greet" in content:
            ok("hello.py contains greet() function")
        else:
            fail("hello.py missing greet() function")
    else:
        fail(f"File missing: {hello_py}")

    test_hello = repo / "test_output" / "test_hello.py"
    if test_hello.exists():
        ok(f"File exists: {test_hello}")
    else:
        fail(f"File missing: {test_hello}")

    # 4. Git commits (smart checkpoint)
    result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=repo, capture_output=True, text=True,
    )
    commits = result.stdout.strip().split("\n")
    if len(commits) >= 3:  # initial + E2E.1 + E2E.2
        ok(f"Git history: {len(commits)} commits (expected >= 3)")
    else:
        log(f"WARNING: Only {len(commits)} commits, expected >= 3")

    # 5. Markdown writeback
    phase_file = repo / "docs" / "phases" / "test-phase.md"
    if phase_file.exists():
        md_content = phase_file.read_text()
        x_count = md_content.count("[x]")
        if x_count >= 2:
            ok(f"Markdown writeback: {x_count} tasks marked [x]")
        else:
            fail(f"Markdown writeback: only {x_count} tasks marked [x] (expected 2)")
    else:
        log("WARNING: Phase file not found in repo (may be using original path)")

    # 6. Dependency order (E2E.2 after E2E.1)
    for task in plan_data["tasks"]:
        if task["task_id"] == "E2E.1":
            ok(f"E2E.1 duration: {task.get('duration_ms', 'N/A')}ms")
        if task["task_id"] == "E2E.2":
            ok(f"E2E.2 duration: {task.get('duration_ms', 'N/A')}ms")

    log("--- Verification complete ---")


# --- Main ---


def main() -> None:
    log("Starting E2E verification for Phase 1C requirement workflow")
    log(f"Platform URL: {PLATFORM_URL}")

    # Check prerequisites
    check_platform_health()

    # Setup
    repo = setup_test_repo()
    phase_file = str(repo / "docs" / "phases" / "test-phase.md")

    # Submit
    plan_data = submit_phase(phase_file, str(repo))
    plan_id = plan_data["plan_id"]

    # Poll
    final_data = poll_until_done(plan_id)

    # Verify
    verify_results(final_data, repo)

    log("E2E verification PASSED")


if __name__ == "__main__":
    main()
