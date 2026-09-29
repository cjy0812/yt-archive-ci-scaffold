---
name: "dual-agent-sync"
description: "Sync .claude/skills/ <-> .trae/skills/ across Claude Code and Trae IDE, block .trae/ from Git. Invoke when setting up dual-agent projects or .trae/ sync issues arise."
---

# Dual Agent Sync

在 **Claude Code + Trae IDE** 双 Agent 环境下，保证 `.claude/skills/` 与 `.trae/skills/` 双向同步，只 push `.claude/`，阻止 `.trae/` 进入 Git 历史。

---

## 核心原则

1. **`.claude/` 是权威副本**（Git 提交、团队共享）
2. **`.trae/` 是本地工作副本**（.gitignore、不提交）
3. **同步方向由事件驱动**：commit 时 Trae→Claude，checkout 时 Claude→Trae
4. **防线纵深**：.gitignore → pre-commit 自动 unstage → pre-push 阻止

---

## 触发场景

| 场景                                 | 说明                                                   |
| ------------------------------------ | ------------------------------------------------------ |
| 项目同时使用 Claude Code 和 Trae IDE | 需要双端 Agent 配置一致                                |
| Trae IDE 中编辑了 Skills             | 需要同步回 `.claude/skills/` 以便提交                  |
| 切换分支后                           | `.claude/skills/` 可能变了，需要同步到 `.trae/skills/` |
| push 前验证                          | 确保双端同步且 `.trae/` 不会被上传                     |
| 新项目初始化                         | 安装 hook 和 .gitignore 规则                           |

---

## 执行步骤

### Step 1: 安装

```sh
sh .claude/skills/dual-agent-sync/scripts/install-hooks.sh
```

此脚本会：

- 复制 hook 模板到 `.githooks/`
- 复制同步脚本到 `scripts/`
- 追加 `.gitignore` 片段
- 设置 `core.hooksPath`

### Step 2: 日常使用（自动）

| Git 事件       | Hook 行为                                                        | 触发条件                                          |
| -------------- | ---------------------------------------------------------------- | ------------------------------------------------- |
| `git commit`   | pre-commit: 同步 `.trae/skills/` → `.claude/skills/` + `git add` | 暂存区有 `.claude/skills/` 变更 **或** 双端不同步 |
| `git push`     | pre-push: 验证同步 + 阻止 `.trae/`                               | 暂存区有 `.claude/skills/` 或 `.trae/` 变更       |
| `git checkout` | post-checkout: 同步 `.claude/skills/` → `.trae/skills/`          | `.trae/` 存在且双端不同步                         |

### Step 3: 手动同步（可选）

```sh
sh scripts/sync-agent-dirs.sh              # 双向自动检测
sh scripts/sync-agent-dirs.sh --check      # 仅检查
sh scripts/sync-agent-dirs.sh --trae-to-claude  # 单向
sh scripts/sync-agent-dirs.sh --claude-to-trae  # 单向
```

### Step 4: 验证

```sh
sh scripts/sync-agent-dirs.sh --check
# 期望输出: [OK] .trae/skills/ <-> .claude/skills/ in sync
```

---

## 防线纵深

```
Layer 1: .gitignore          → git add 自然忽略 .trae/
Layer 2: pre-commit          → git add -f 绕过时自动 git reset HEAD
Layer 3: pre-push            → 最终拦截，阻止 .trae/ 进入远程
```

即使 `git add -f .trae/` 绕过 .gitignore：

- pre-commit 自动 unstage
- pre-push 再次拦截（双保险）

---

## 输出标准

安装完成后，项目应满足：

- [x] `.githooks/pre-commit` 存在且可执行
- [x] `.githooks/pre-push` 存在且可执行
- [x] `.githooks/post-checkout` 存在且可执行
- [x] `scripts/sync-agent-dirs.sh` 存在且可执行
- [x] `.gitignore` 包含 `.trae/` 规则
- [x] `git config core.hooksPath` 指向 `.githooks`
- [x] `sh scripts/sync-agent-dirs.sh --check` 返回 exit 0

---

## Agent 映射参考

详见 [references/agent-mapping.md](references/agent-mapping.md) — Claude Code ↔ Trae IDE 的语义映射表。

## Hook 规格参考

详见 [references/hook-spec.md](references/hook-spec.md) — 各 hook 的精确触发条件与行为规格。

## 同步协议参考

详见 [references/sync-protocol.md](references/sync-protocol.md) — 数据流、同步方向决策、冲突处理。
