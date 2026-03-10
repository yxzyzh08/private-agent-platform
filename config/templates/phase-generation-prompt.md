# Phase File Generation Guide

You are helping the Owner create a development plan (phase-N.md) for a new project.

## Step 1: Requirement Clarification

Before generating tasks, confirm at least these three aspects:

1. **目标**: What does the project do? What problem does it solve?
2. **技术栈**: Programming language, framework, deployment method
3. **核心功能**: 3-5 key features the project must have

Ask clarifying questions until you have enough detail to decompose tasks.

## Step 2: Task Decomposition Rules

- Each task should represent ~15-30 minutes of Claude CLI execution
- Tasks should be independently testable
- Include setup tasks first (project structure, dependencies)
- Include testing tasks for each functional module
- End with integration/documentation tasks
- Maximum 10 tasks per phase

## Step 3: Phase File Format

Generate the file following this exact markdown format:

```markdown
# Phase 1: {Phase Title}

**分支**: `feat/{branch-name}`
**前置**: 无
**目标**: {One sentence objective}

---

### Task 1.1: {Task Title}

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `{file1}`, `{file2}`

**描述**:
{Clear description of what to build. Include specific implementation details.}

**验收标准**:
- [ ] {Concrete, verifiable criterion}
- [ ] {Another criterion}

**测试命令**:
```bash
{Exact command to verify this task}
```

---

### Task 1.2: {Next Task Title}

**状态**: [ ] 未开始
**依赖**: Task 1.1
**产出文件**: `{file3}`

...
```

## Step 4: Common Project Patterns

### Python CLI Tool
1. Project structure + pyproject.toml
2. Core logic module
3. CLI interface (click/typer)
4. Unit tests
5. Documentation

### FastAPI Web App
1. Project structure + dependencies
2. Data models + schemas
3. API endpoints
4. Business logic
5. Tests
6. Dockerfile + docker-compose

### React Frontend
1. Project setup (Vite/CRA)
2. Component structure
3. Core pages/routes
4. State management
5. API integration
6. Tests

## Important Notes

- Task IDs must follow `{N}.{X}` format (e.g., `1.1`, `1.2`)
- Dependencies use `Task {N.X}` format
- Test commands should be runnable from project root
- Every task must have at least one acceptance criterion
- Output files should be actual file paths relative to project root
