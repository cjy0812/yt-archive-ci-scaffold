# 同步协议与数据流

## 数据流模型

```
                    ┌─────────────────────────────┐
                    │       Git Repository        │
                    │  (只含 .claude/skills/)     │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │ push           │ pull/checkout  │
              ↓                │                ↓
        ┌──────────┐          │          ┌──────────┐
        │  Remote  │          │          │  Local   │
        └──────────┘          │          └──────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
     .claude/skills/               .trae/skills/
     (权威副本, Git跟踪)           (工作副本, .gitignore)
              │                               │
              │    pre-commit: Trae→Claude    │
              │    post-checkout: Claude→Trae │
              │                               │
              └─────────── sync ──────────────┘
```

## 同步方向决策

| 事件                           | 方向                                | 原因                         |
| ------------------------------ | ----------------------------------- | ---------------------------- |
| `git commit` (pre-commit)      | `.trae/skills/` → `.claude/skills/` | Trae 端编辑需要进入 Git      |
| `git checkout` (post-checkout) | `.claude/skills/` → `.trae/skills/` | 分支切换后更新 Trae 工作副本 |
| 手动双向检测                   | 较新一方 → 较旧一方                 | 基于文件修改时间戳自动判断   |

## 同步内容范围

**当前同步**: `.claude/skills/` ↔ `.trae/skills/`

**不同步的内容**（按设计）:

| 内容                    | 原因                                         |
| ----------------------- | -------------------------------------------- |
| `.claude/settings.json` | Agent 行为配置，非知识，格式不兼容           |
| `.claude/commands/`     | Claude 专属入口，Trae 用 Workflow/Skill 入口 |
| `.claude/hooks/`        | 事件生命周期可能不同                         |
| `.claude/agents/`       | 职责相似但格式不兼容                         |
| `.claude/.mcp.json`     | MCP 是基础设施，各自配置                     |

## 冲突处理

### 场景：双端同时编辑同一 Skill

```
时间线:
  T1: 用户在 Trae 编辑 .trae/skills/foo/SKILL.md
  T2: 用户在 Claude 编辑 .claude/skills/foo/SKILL.md
  T3: git commit 触发 pre-commit
```

**处理策略**：pre-commit 执行 `--trae-to-claude`，Trae 端覆盖 Claude 端。

**理由**：
- pre-commit 发生在 commit 时，此时用户意图是"提交当前工作"
- Trae 端的编辑是"最新意图"，应优先
- 如果需要 Claude 端的修改，用户应在 commit 后重新编辑

### 防止冲突的最佳实践

1. **不要同时在两个 Agent 中编辑同一 Skill**
2. **编辑前先 `--check`**：确认双端同步
3. **commit 前让 hook 自动同步**：不要手动 `git add .claude/skills/`

## 同步脚本接口

```sh
sync-agent-dirs.sh              # 双向自动检测并同步
sync-agent-dirs.sh --check      # 仅检查，exit 0=同步, 1=不同步, 2=错误
sync-agent-dirs.sh --trae-to-claude  # 单向: .trae/skills/ → .claude/skills/
sync-agent-dirs.sh --claude-to-trae  # 单向: .claude/skills/ → .trae/skills/
```

## 比较算法

使用 `git diff --no-index --quiet` 进行目录比较：

- 优点：语义级比较（忽略空白、换行符差异）
- 优点：Git 自带，无需额外依赖
- 注意：`--no-index` 使 git diff 跳出仓库限制，比较任意两个路径