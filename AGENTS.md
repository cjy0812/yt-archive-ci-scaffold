# Claude Agent 实现规范

你正在实现一个基于 GitHub Actions 的增量式 YouTube 归档系统。

## 0. 不可协商的约束

- docs等描述除技术术语可以使用英语外，其他所有内容都必须使用中文。
- 不要把它变成一个通用下载器服务。
- 不要添加 Web 服务器、API 端点、公开上传端点或任意 URL 下载器。
- 只处理来自 `channels.txt` 的 URL。
- 永远不要将媒体二进制文件提交到 Git。
- 永远不要将 YouTube cookies/密钥存储到 Git。
- 不要绕过 DRM、认证、付费墙、地理/访问控制或其他访问控制,并及时汇报等待指示。
- 保持幂等性：重新运行任何作业都不得重复下载或字幕。
- 在下载媒体之前，优先进行仅元数据操作。
- 默认媒体处理最大并发数：1。
- 当标准库或现有依赖已足够时，不要仅为方便而引入依赖。

## 1. 仓库架构

实现以下分层：

1. 发现
2. 决策/策略
3. 媒体下载/转码
4. 字幕获取/ASR
5. 状态/归档
6. 每日暂存产物
7. 每周 Release 聚合

保持它们可独立测试。

推荐文件：

- `scripts/discover.py`
- `scripts/process.py`
- `scripts/subtitle.py`
- `scripts/release.py`
- `tests/`
- `state/`
- `manifests/`

为策略决策添加测试，且不需要网络访问。

## 2. 发现

尽可能以编程方式使用 yt-dlp。

对于每个已配置的频道：

- 仅检查最新的 `max_candidates_per_channel`；
- 在足够时使用扁平提取；
- 仅对尚未归档的候选获取完整元数据；
- 识别：
  - 视频 ID
  - URL
  - 标题
  - 频道
  - 上传日期
  - 时长
  - 直播状态
  - 可用字幕语言
  - 可用格式
  - 预估文件大小/filesize_approx
  - 编解码器/容器
  - 高度
  - 帧率
  - 可用时的比特率

使用以视频 ID 为键的归档/状态文件。

不要每天重新扫描完整的历史频道。

## 3. 媒体决策引擎

实现确定性策略。

输入：

- 时长（秒）
- 直播状态
- 可用格式
- 预估大小
- 配置预算

输出：

```json
{
  "video_id": "...",
  "media_mode": "native_720p|hevc_720p|fallback_480p|fallback_420p|audio",
  "reason": "...",
  "estimated_mb": 123.4
}
```

规则，按顺序：

### 直播

如果 `audio_only_live=true` 且 yt-dlp 相应表示 live/is_live/upcoming：

- 不下载视频；
- 仅音频；
- 字幕流水线仍然运行。

### 长内容

如果时长 >= `long_form_minutes`：

- 默认仅音频。

### 普通视频 <= preferred_720p_minutes

- 检查支持 720p 的格式。
- 在下载前估算输出大小。
- 如果预期大小 <= `native_720p_mb`，下载原生 720p。
- 否则考虑 HEVC。

### HEVC

仅在以下情况使用 HEVC：

1. 原生 720p 超出预算；
2. 源实际上可下载；
3. 预估的 HEVC 结果明显小于原生；
4. 结果仍在 HEVC 预算内。

使用 FFmpeg `libx265`。

默认：
- CRF 28
- preset medium
- 复制音频
- 视情况使用 MP4/MKV
- 除非必要，永远不要重新编码音频。

不要声称可以精确预测 HEVC 输出大小。使用基于时长和目标比特率/CRF 启发式的保守估算。

### 回退

如果预计 HEVC 超出预算：

1. 尝试 480p；
2. 如果不可用或仍高于预算，尝试 420p；
3. 如果仍高于媒体预算，仅音频。

如果元数据提供了足够可靠的大小估算，不要仅仅为了发现 720p 文件太大而下载它。

### 未知大小

如果文件大小未知：

- 在可用时使用 `tbr * duration`；
- 否则使用保守的比特率估算；
- 将估算置信度标记为 `low`；
- 永远不要让未知估算绕过安全限制。

## 4. 音频

优先直接使用 `bestaudio`。

默认避免 MP3 转换。

尽可能使用原始音频流/容器。如果需要一致的容器，则重新封装而不是重新编码。

音频是最终回退。

## 5. 字幕

优先级：

1. 手动/原生字幕；
2. YouTube 自动字幕；
3. 使用 faster-whisper 进行本地 ASR。

使用 yt-dlp 字幕支持：

- `--write-subs`
- `--write-auto-subs`
- `--sub-langs`
- `--sub-format`
- `--convert-subs vtt`

优先使用配置的语言：

`zh-Hans`、`zh-Hant`、`zh`、`en`

如果存在可用字幕：

- 不运行 Whisper。

如果不存在可用字幕：

- 临时下载 bestaudio；
- 运行 faster-whisper CPU INT8；
- 写入 WebVTT；
- 立即删除临时音频。

默认 ASR：

- model: small
- device: cpu
- compute_type: int8
- 最大自动 ASR 时长：90 分钟

对于超过 ASR 限制的音频：

- 不要静默运行巨大的 ASR 作业；
- 将字幕状态标记为 `asr_skipped_duration_limit`；
- 保留音频。

ASR 必须按视频隔离。一个失败不得中止所有其他视频。

## 6. 字幕 Git 布局

使用：

```text
subtitles/<safe-channel>/<video_id>.<language>.vtt
```

同时维护：

```text
manifests/<video_id>.json
```

人类可读字幕

```text
subtitles/<safe-channel>/<video_id>.<language>.txt
```

清单记录：

- 源 URL
- 视频 ID
- 标题
- 频道
- 上传日期
- 时长
- 所选媒体模式
- 媒体文件名
- 字幕来源：`native|auto|asr|none`
- 字幕语言
- 时间戳
- 工具版本
- 决策原因

不要在清单中存储 cookies、认证头或个人信息。

## 7. 幂等性和状态

按视频 ID 维护状态。

状态至少应包括：

- discovered
- processing
- media_ready
- subtitle_ready
- staged
- released
- failed

使用原子写入。

如果一次运行中途失败：

- 后续运行必须能够恢复；
- 已完成的字幕不得再次调用 ASR；
- 已完成的媒体不得再次下载，除非校验和/文件验证失败。

在有帮助的地方使用 yt-dlp 的下载归档；同时维护项目级 JSON 状态，因为项目需要比 yt-dlp 归档更丰富的状态。

## 8. 每日工作流

每日工作流必须：

1. checkout；
2. 安装固定版本的依赖；
3. 运行发现；
4. 仅处理新候选；
5. 获取原生/自动字幕；
6. 仅在必要时运行 ASR；
7. 提交字幕/状态/清单；
8. 打包媒体；
9. 上传短期 Actions 产物。

将产物保留期设置为 80 天。

永远不要将产物用作永久存储。

默认每日安全限制：

- 每次运行最多 6 个新视频
- 每次运行最多下载 1500 MB 媒体
- 最大 1 个并发媒体作业
- 最大 300 分钟工作流运行时间

如果超出限制：

- 优雅停止；
- 将剩余 ID 留待后续运行处理；
- 不要删除现有状态。

## 9. 每周发布

每周工作流必须：

1. 在最近的暂存窗口内查找成功的每日运行；
2. 下载它们的产物；
3. 按视频 ID 去重；
4. 验证文件；
5. 执行单个资源和总限制；
6. 创建/更新一个每周 GitHub Release；
7. 上传媒体资源；
8. 写入 `release-manifest.json`；
9. 仅在上传成功后标记项目为 `released`。

使用 `gh` CLI 和 `GITHUB_TOKEN`，而不是添加不必要的第三方 release action。

不要依赖已过期的产物。

如果一个产物缺失：

- 发布仍然可用的文件；
- 在清单中记录缺失的运行；
- 不要将这些视频标记为已发布。

## 10. GitHub Actions 效率

- 使用一个并发槽。
- 不要为每个视频运行矩阵作业。
- 默认不要使用 `--concurrent-fragments` > 1。
- 不要并行运行 Whisper。
- 避免在每一步都执行 `pip install`；合并设置步骤。
- 固定主版本，并在验证后最好固定确切的 Python 包版本。
- 仅在测量表明有帮助时使用缓存；不要缓存大型媒体。
- 保持产物保留期短。
- 安排在非整点分钟。

## 11. 测试

为以下内容实现单元测试：

- 时长分类；
- 直播分类；
- 原生 720p 预算；
- HEVC 预算；
- 480p 回退；
- 420p 回退；
- 音频回退；
- 未知文件大小；
- 零比特率；
- 字幕优先级；
- ASR 时长限制；
- 重复视频 ID；
- 幂等重跑；
- 发布去重。

测试不得访问 YouTube。

添加 `--dry-run` 模式，在不下载的情况下打印决策。

## 12. CLI

最终脚本应支持：

```text
python scripts/discover.py
python scripts/process.py
python scripts/subtitle.py
python scripts/release.py
```

并且最好支持：

```text
python scripts/process.py --dry-run
python scripts/process.py --video-id ID
python scripts/subtitle.py --video-id ID
```

## 13. 错误处理

对错误进行分类：

- 瞬时网络错误
- 提取器失败
- 不可用/已删除视频
- 不支持的格式
- FFmpeg 失败
- ASR 失败
- Git 失败
- 产物失败
- Release 上传失败

对瞬时失败使用有界指数退避进行重试。

不要无限重试永久性错误。

## 14. 安全

将标题/频道名称视为不受信任的字符串。

清理文件名。

永远不要将标题直接插值到 shell 命令中。

不要将元数据作为代码执行。

尽可能使用 subprocess 参数数组而不是 shell 字符串。

## 15. 最终验收标准

在宣布完成之前，在本地测试：

- 一个带原生字幕的短视频；
- 一个仅有自动字幕的短视频；
- 一个没有字幕的视频 -> ASR；
- 一个 >18 分钟的视频；
- 一个长内容视频；
- 一个直播元数据样本；
- 一个预估 720p 大小超出预算的视频；
- 一个 HEVC 回退；
- 一个 480/420 回退；
- 重复重跑。

然后使用 `workflow_dispatch` 手动运行 GitHub Actions。

在以下条件满足之前，不要说“完成”：
- 没有媒体被提交到 Git；
- 重复运行是幂等的；
- 仅字幕变更会创建 Git 提交；
- 暂存产物已创建；
- 每周发布聚合正常工作；
- 单个视频失败不会导致整个批次失败。