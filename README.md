# yt-archive-ci

基于 GitHub Actions 的增量式 YouTube 归档流水线。

## 目标

- 每天检查一次已配置的 YouTube 频道。
- 按视频 ID 增量去重，避免重复扫描/下载。
- **视频与直播分流**：分别配置、分别归档、分别统计。
- **元数据优先**：先获取 duration / live status / formats / filesize，再决策下载策略。
- 优先使用 YouTube 原生字幕；仅在无可用字幕时运行 Whisper ASR。
- 字幕/封面/链接提交到 Git；媒体文件通过 GitHub Release 分发。
- 基于资源预算的多级媒体策略（720p → HEVC → 480p/420p → 仅音频）。
- 永远不将视频/音频二进制文件提交到 Git 历史。

## 重要

本项目适用于你**有权归档/再分发**的内容。GitHub Actions/Release 不应用于：
- 不受限制的视频 CDN
- 绕过 YouTube 访问控制
- 版权侵权内容

## 快速开始

### 1. Fork / Clone

```bash
git clone https://github.com/<your-username>/yt-archive-ci-scaffold.git
cd yt-archive-ci-scaffold
```

### 2. 配置频道

编辑 `channels.txt`：

```ini
[videos]
@XMSR                # 普通视频频道

[live]
# @ExampleLiveChannel  # 直播频道
```

- 支持 `@handle`、频道 URL、纯 handle 名
- `[videos]` 段处理普通视频，`[live]` 段处理直播

### 3. 调整策略

编辑 `config.toml`：

```toml
[discovery]
mode = "count"           # "count" = 按数量回溯 | "time" = 按时间范围
max_history_count = 10   # count 模式：每个频道回溯最近 N 条
publish_after = ""       # time 模式：起始日期 (YYYY-MM-DD)
publish_before = ""      # time 模式：截止日期 (空 = 至今)

# 媒体策略阈值
normal_max_minutes = 60       # 超过此时长 → 仅音频
preferred_720p_minutes = 18  # 低于此阈值优先 720p
long_form_minutes = 60        # 长内容处理阈值

[budget]
native_720p_mb = 300    # 原生 720p 预算
hevc_720p_mb = 200      # HEVC 720p 预算
fallback_480p_mb = 150  # 480p 回退预算
audio_mb = 100          # 仅音频预算
```

### 4. 启用 GitHub Actions

推送到 GitHub 后，在仓库 `Settings > Actions > General` 中确保 Workflow permissions 为 **Read and write**。

工作流将自动运行：
- **每日归档** (`daily.yml`)：凌晨 2:17 UTC 触发
- **每周发布** (`weekly-release.yml`)：周日 5:41 UTC 触发

也可以手动触发：`Actions → Daily YouTube archive → Run workflow`

### 5. 本地开发

```bash
# 安装依赖
uv sync

# 格式检查 + 测试
uv run ruff check scripts/ tests/ --fix
uv run ruff format scripts/ tests/
uv run pytest tests/ -v

# 本地 dry-run（不下载，仅决策）
uv run python scripts/discover.py
uv run python scripts/process.py --dry-run --candidates work/candidates.jsonl
```

## 目录结构

```text
channels.txt              # 频道配置
config.toml               # 策略配置
scripts/
  discover.py             # 发现阶段：获取平坦元数据
  process.py              # 媒体策略引擎 + 下载管线
  subtitle.py             # 字幕获取/ASR
  release.py              # 周度 Release 聚合
  state.py                # 状态管理（幂等）
tests/
  test_policy.py          # 策略引擎单元测试 (41 个)
work/                     # 工作目录（暂态）
  candidates.jsonl        # 候选视频清单
media/                    # 媒体文件（仅本地/CI 暂存）
  <频道>/videos/YYYY/MM/YYYYMMDD_标题/
  <频道>/live/YYYY/MM/YYYYMMDD_标题/
thumbnails/               # 封面 (WebP 98%) → Git
  <频道>/videos/YYYY/MM/YYYYMMDD_标题/<video_id>.webp
urls/                     # 视频链接存档 → Git
  <频道>/videos/YYYY/MM/<video_id>.json
subtitles/                # 字幕文件 → Git
  <频道>/<video_id>.<语言>.vtt
state/                    # 处理状态 → Git
  <video_id>.json
  archive.json
staging/                  # CI 暂存产物 (14天保留)
release/                  # 发布聚合
.github/workflows/
  daily.yml               # 每日归档 Workflow
  weekly-release.yml      # 每周发布 Workflow
```

## 处理流程

```
discover.py          process.py           subtitle.py        release.py
  │                    │                    │                  │
  ├─ 读取 channels.txt  ├─ 读取 candidates   ├─ 读取 candidates ├─ 下载 staging
  ├─ 平坦元数据提取      ├─ 详细元数据提取      ├─ 下载字幕/ASR     ├─ 去重验证
  ├─ archive 去重       ├─ 策略决策引擎        ├─ 写入 subtitles/  ├─ 聚合统计
  ├─ 输出 candidates →   ├─ 下载媒体            └─ 更新状态        ├─ 创建 Release
  └─ 更新 archive        ├─ 封面 WebP 压缩                        └─ 写入 manifest
                         ├─ 保存 URL 存档
                         └─ 提交 Git
```

### 状态机

```
discovered → processing → media_ready → subtitle_ready → staged → released
                                      (任意阶段 → failed)
```

## 媒体策略引擎

决策优先级（详见 `POLICY.md`）：

| 优先级 | 条件                                        | 决策          |
| ------ | ------------------------------------------- | ------------- |
| 1      | 直播 + audio_only_live=true                 | **仅音频**    |
| 2      | 时长 >= long_form_minutes                   | **仅音频**    |
| 3      | <=preferred_720p_minutes + 原生720p <= 预算 | **原生 720p** |
| 4      | 原生720p超预算 + HEVC在预算内               | **HEVC 720p** |
| 5      | HEVC超预算 + 480p可用                       | **回退 480p** |
| 6      | 480p不可用或超预算 + 420p可用               | **回退 420p** |
| 7      | 以上均失败                                  | **仅音频**    |

## 字幕优先级

1. **手动/原生字幕**（YouTube 手动上传）
2. **YouTube 自动字幕**（`--write-auto-subs`）
3. **Whisper ASR**（faster-whisper, CPU, INT8, 最长 90 分钟）

配置语言：`zh-Hans`, `zh-Hant`, `zh`, `en`

## CI 参数

### 手动触发 Daily Workflow 参数

| 参数                | 类型    | 默认值  | 说明                     |
| ------------------- | ------- | ------- | ------------------------ |
| `discovery_mode`    | choice  | `count` | 发现模式：`count`/`time` |
| `max_history_count` | string  | `10`    | count 模式回溯条数       |
| `publish_after`     | string  | `""`    | time 模式起始日期        |
| `publish_before`    | string  | `""`    | time 模式截止日期        |
| `skip_download`     | boolean | `false` | 仅发现+决策，不下载      |

### 手动触发 Weekly Release 参数

| 参数            | 类型    | 默认值  | 说明                       |
| --------------- | ------- | ------- | -------------------------- |
| `days_lookback` | string  | `10`    | 回溯天数                   |
| `force_dry_run` | boolean | `false` | 仅生成清单，不创建 Release |
| `custom_title`  | string  | `""`    | 自定义 Release 标题        |

## 提交规则

```bash
# push 前强制检查
uv run ruff check scripts/ tests/ --fix
uv run ruff format scripts/ tests/
uv run pytest tests/ -v
```

Commit 格式：
```
feat: <简短标题>

- <详细变更项1>
- <详细变更项2>
```

## 权限要求

GitHub Actions 需要：
- `contents: write` — 提交字幕/封面/链接/状态，创建 Release
- `actions: read` — 下载之前的 staging artifacts

## 许可证

本项目为脚手架模板，使用时请遵守 YouTube 服务条款及目标频道的内容政策。