# Claude Code ↔ Trae IDE Agent 映射表

> 按功能语义映射，不是按文件名一一对应。

## 最终映射

| Claude Code             | 作用                             | Trae 中最接近的机制        | 对应程度 | 迁移建议                         |
| ----------------------- | -------------------------------- | -------------------------- | -------- | -------------------------------- |
| `CLAUDE.md`             | 项目级长期规则、上下文、开发规范 | **Rules / Project Rules**  | ★★★★★    | ✅ 直接迁移思想                   |
| `.claude/skills/`       | 可复用、按需/自动激活的专业能力  | **Skills**                 | ★★★★☆    | ✅ 优先复用                       |
| `.claude/agents/`       | Subagent 定义                    | **Agent / 子 Agent 能力**  | ★★★☆☆    | 🟡 重写格式                       |
| `.claude/commands/`     | 自定义 `/xxx` 命令               | **Workflow / Skill 入口**  | ★★☆☆☆    | 🟡 不要机械复制                   |
| `.claude/.mcp.json`     | MCP Server 配置                  | **MCP**                    | ★★★★★    | ✅ 概念直接对应                   |
| `.claude/hooks/`        | 事件触发自动化                   | **Hooks/自动化机制**       | ★★☆☆☆    | 🔴 先确认 Trae 是否有等价生命周期 |
| `.claude/settings.json` | Claude 行为/权限/Hook 配置       | **Rules + Agent/工具配置** | ★★☆☆☆    | 🟡 不直接迁移                     |
| `.claude/*.local.*`     | 本机私有、不提交 Git 的配置      | **本地规则/用户级配置**    | ★★☆☆☆    | 🟡                                |
| `.claude-plugin/`       | Claude Code Plugin 本体结构      | **无直接等价物**           | ★☆☆☆☆    | ❌ 不迁移                         |
| `scripts/`              | 插件辅助脚本                     | **项目脚本/工具**          | ★★★☆☆    | ✅ 普通代码即可                   |

## 关键映射详解

### CLAUDE.md ↔ Trae Rules（最值得迁移）

```text
CLAUDE.md → 告诉 Agent "这个项目应该怎么工作"
         → Trae Project Rules
```

这是**高度可靠的语义迁移**。

### .claude/skills/ ↔ Trae Skills（最值得复用）

```text
.claude/skills/xxx/SKILL.md → 某一领域的可复用专业知识/工作流程
                          → Trae Skill
```

**这是跨 Agent 复用最优先的一类文件。**

### .claude/.mcp.json ↔ Trae MCP（概念直接对应）

```text
MCP Server 是独立于 Agent 的基础设施层：

                 ┌── Claude Code
MCP Servers ─────┤
                 └── Trae
```

不应各维护一套完全不同的逻辑。

### .claude/hooks/ → 不要强行映射

Claude Code Hook 是事件驱动自动化（SessionStart / PreToolUse / Stop...）。
如果 Trae 没有完全对应的 Hook 生命周期，不能简单改名就认为有效。

## 不建议的架构

```text
.claude/    ← 一整套
.trae/      ← 复制一整套（重复、易不同步）
```

## 推荐的三层架构

```text
project/
│
├── CLAUDE.md / AGENTS.md
│       ↑ 通用项目规则
│
├── docs/ai/
│       ↑ 通用 AI 知识（与 Agent 实现解耦）
│
├── .claude/
│   ├── skills/     ← 权威副本（Git 提交）
│   ├── agents/
│   ├── commands/
│   └── .mcp.json
│
└── .trae/
    └── skills/     ← 本地工作副本（.gitignore）
```

核心思想：**知识与 Agent 实现解耦**。