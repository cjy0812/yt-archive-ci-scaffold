# 项目规则

## 提交流程

### push 前强制检查
在 `git commit` 之前，必须执行全量 Python 文件检查：
```bash
uv run ruff check scripts/ tests/ --fix
uv run ruff format scripts/ tests/
uv run pytest tests/ -v
```
三者全部通过（exit code 0）才允许提交。

### commit 格式
```
feat: <简短标题>

- <详细变更项1>
- <详细变更项2>
- ...
```

- 标题简短明了（中文/英文均可）
- 说明使用无序列表，偏详细
- 每完成一项合格任务后务必及时提交

### 常用命令速查
| 操作     | 命令                                                                                                       |
| -------- | ---------------------------------------------------------------------------------------------------------- |
| 格式检查 | `uv run ruff check scripts/ tests/ --fix`                                                                  |
| 格式化   | `uv run ruff format scripts/ tests/`                                                                       |
| 运行测试 | `uv run pytest tests/ -v`                                                                                  |
| 全量检查 | `uv run ruff check scripts/ tests/ --fix && uv run ruff format scripts/ tests/ && uv run pytest tests/ -v` |

## 项目约束

- Python 依赖管理必须使用 `uv`
- 代码索引优先使用 symdex MCP
- 文档查询优先使用 Context7
- 禁止编造不确定的内容