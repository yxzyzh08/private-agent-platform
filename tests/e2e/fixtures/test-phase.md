# Phase E2E-Test: 端到端验收

**分支**: `feat/e2e-test`
**目标**: 验证需求驱动开发工作流

---

### Task E2E.1: 创建测试文件

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `test_output/hello.py`

**描述**:
创建一个简单的 Python 文件 `test_output/hello.py`，内容为一个 `greet()` 函数。

**验收标准**:
- [ ] `test_output/hello.py` 存在
- [ ] 包含 `def greet()` 函数

**测试命令**:
```bash
python -c "from test_output.hello import greet; print(greet())"
```

---

### Task E2E.2: 创建测试用例

**状态**: [ ] 未开始
**依赖**: Task E2E.1
**产出文件**: `test_output/test_hello.py`

**描述**:
为 `test_output/hello.py` 编写 pytest 测试。

**验收标准**:
- [ ] `test_output/test_hello.py` 存在
- [ ] pytest 通过

**测试命令**:
```bash
python -m pytest test_output/test_hello.py -v
```
