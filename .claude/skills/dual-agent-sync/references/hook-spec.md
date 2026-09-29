# Hook 触发条件与行为规格

> 所有 hook 均为纯 POSIX sh，跨平台兼容（Linux / macOS / Git Bash / WSL）。

## 总览

| Hook          | 事件           | 主要职责    | 触发条件                                |
| ------------- | -------------- | ----------- | --------------------------------------- |
| pre-commit    | `git commit`   | 同步 + 防御 | 暂存区有 `.claude/skills/` 或双端不同步 |
| pre-push      | `git push`     | 验证 + 阻止 | 暂存区有 `.claude/skills/` 或 `.trae/`  |
| post-checkout | `git checkout` | 同步到 Trae | `.trae/` 存在且双端不同步               |

---

## pre-commit

### 触发条件（满足任一即触发）

```
条件 1: 暂存区包含 .claude/skills/ 相关文件
条件 2: .trae/skills/ 与 .claude/skills/ 内容不同步（Trae 端有编辑）
```

### 行为

```
1. 检测暂存区是否有 .trae/ 文件
   → 有: 自动 git reset HEAD -- .trae/ (防线 Layer 2)
2. 检测是否需要同步
   → 不需要: exit 0 (静默跳过)
3. 执行 .trae/skills/ → .claude/skills/ 同步
4. 如果 .claude/skills/ 有变更: git add .claude/skills/
```

### 不触发场景

- 暂存区无 `.claude/skills/` 或 `.trae/` 变更，且双端已同步
- 无 `.trae/skills/` 目录

---

## pre-push

### 触发条件（满足任一即触发）

```
条件 1: 暂存区包含 .claude/skills/ 相关文件
条件 2: 暂存区包含 .trae/ 相关文件
```

### 行为

```
1. 暂存区无相关文件 → exit 0 (静默跳过)
2. 验证 .trae/skills/ <-> .claude/skills/ 同步
   → 不同步: BLOCKED, exit 1
3. 检测暂存区是否有 .trae/ 文件
   → 有: BLOCKED, exit 1 (防线 Layer 3)
```

### 阻止信息

```
[BLOCKED] .trae/skills/ and .claude/skills/ are NOT in sync!
  Run: sh scripts/sync-agent-dirs.sh
  Then: git add .claude/skills/ && git commit --amend --no-edit

[BLOCKED] .trae/ files are staged for commit!
  .trae/ should NOT be pushed (it is a local Trae IDE working copy).
  Remove from staging: git reset HEAD .trae/
```

---

## post-checkout

### 触发条件（同时满足才触发）

```
条件 1: .trae/skills/ 目录存在
条件 2: .claude/skills/ 与 .trae/skills/ 内容不同步
```

### 行为

```
1. .trae/ 不存在 → exit 0 (纯 Claude Code 环境)
2. 双端已同步 → exit 0 (无需操作)
3. 执行 .claude/skills/ → .trae/skills/ 同步
```

### 不触发场景

- 无 `.trae/` 目录（纯 Claude Code 项目）
- 双端已同步

---

## 防线纵深模型

```
攻击向量                          .gitignore    pre-commit    pre-push
─────────────────────────────────────────────────────────────────────
git add .trae/                   ✅ 阻止       —            —
git add -A (含.trae/)           ✅ 过滤       —            —
git add -f .trae/               ❌ 绕过       ✅ auto-unstage ✅ 阻止
git commit --no-verify          —            ❌ 跳过       ✅ 阻止
git push --no-verify            —            —            ❌ 跳过
```

**最终保障**：即使所有 hook 被 `--no-verify` 跳过，`.trae/` 仍需 `git add -f` 才能进入暂存区，且 `.gitignore` 是项目级配置，团队成员都会继承。