# yt-archive-ci

[中文](README.md)

A GitHub Actions-based incremental YouTube archiving pipeline.

## Goals

- Daily checks of configured YouTube channels.
- Incremental deduplication by video ID to avoid re-scanning/downloading.
- **Video vs Live separation**: separate configuration, separate archiving, separate statistics.
- **Metadata-first**: fetch duration / live status / formats / filesize before deciding download strategy.
- Prefer YouTube native subtitles; only run Whisper ASR when no subtitles are available.
- Subtitles/thumbnails/URLs committed to Git; media distributed via GitHub Release.
- Multi-tier media strategy based on resource budget (720p → HEVC → 480p/420p → audio-only).
- Never commit video/audio binaries to Git history.

## Important

This project is for content you **have the right to archive/redistribute**. GitHub Actions/Release should not be used for:
- Unrestricted video CDN
- Circumventing YouTube access controls
- Copyright-infringing content

## Quick Start

### 1. Fork / Clone

```bash
git clone https://github.com/<your-username>/yt-archive-ci-scaffold.git
cd yt-archive-ci-scaffold
```

### 2. Configure Channels

Edit `channels.txt`:

```ini
[videos]
@XMSR                # Regular video channel

[live]
# @ExampleLiveChannel  # Live stream channel
```

- Supports `@handle`, channel URL, or plain handle name
- `[videos]` section for regular videos, `[live]` section for live streams

### 3. Adjust Strategy

Edit `config.toml`:

```toml
[discovery]
mode = "count"           # "count" = backtrack by count | "time" = by date range
max_history_count = 10   # count mode: backtrack N items per channel
publish_after = ""       # time mode: start date (YYYY-MM-DD)
publish_before = ""      # time mode: end date (empty = present)

# Media strategy thresholds
normal_max_minutes = 60       # Above this → audio only
preferred_720p_minutes = 18  # Below this, prefer 720p
long_form_minutes = 60        # Long-form threshold

[budget]
native_720p_mb = 300    # Native 720p budget
hevc_720p_mb = 200      # HEVC 720p budget
fallback_480p_mb = 150  # 480p fallback budget
audio_mb = 100          # Audio-only budget
```

### 4. Enable GitHub Actions

After pushing to GitHub, ensure **Read and write** permissions under `Settings > Actions > General`.

Workflows run automatically:
- **Daily Archive** (`daily.yml`): triggers at 2:17 AM UTC
- **Weekly Release** (`weekly-release.yml`): triggers Sunday at 5:41 AM UTC

Manual triggers: `Actions → Daily YouTube archive → Run workflow`

### 5. Local Development

```bash
# Install dependencies
uv sync

# Lint + test
uv run ruff check scripts/ tests/ --fix
uv run ruff format scripts/ tests/
uv run pytest tests/ -v

# Local dry-run (decision only, no download)
uv run python scripts/discover.py
uv run python scripts/process.py --dry-run --candidates work/candidates.jsonl
```

## Directory Structure

```text
channels.txt              # Channel config
config.toml               # Strategy config
scripts/
  discover.py             # Discovery: flat metadata extraction
  process.py              # Media policy engine + download pipeline
  subtitle.py             # Subtitle fetching / ASR
  release.py              # Weekly release aggregation
  state.py                # State management (idempotent)
tests/
  test_policy.py          # Policy engine unit tests (41)
work/                     # Working directory (transient)
  candidates.jsonl        # Candidate video list
media/                    # Media files (local/CI staging only)
  <channel>/videos/YYYY/MM/YYYYMMDD_title/
  <channel>/live/YYYY/MM/YYYYMMDD_title/
thumbnails/               # Cover images (WebP 98%) → Git
  <channel>/videos/YYYY/MM/YYYYMMDD_title/<video_id>.webp
urls/                     # Video URL archive → Git
  <channel>/videos/YYYY/MM/<video_id>.json
subtitles/                # Subtitle files → Git
  <channel>/<video_id>.<lang>.vtt
state/                    # Processing state → Git
  <video_id>.json
  archive.json
staging/                  # CI staging artifacts (14-day retention)
release/                  # Release aggregation
.github/workflows/
  daily.yml               # Daily archive workflow
  weekly-release.yml      # Weekly release workflow
```

## Pipeline Flow

```
discover.py          process.py           subtitle.py        release.py
  │                    │                    │                  │
  ├─ Read channels.txt  ├─ Read candidates   ├─ Read candidates ├─ Download staging
  ├─ Flat metadata      ├─ Detailed metadata ├─ Fetch subs/ASR   ├─ Deduplicate
  ├─ Archive dedup      ├─ Policy engine     ├─ Write subtitles/ ├─ Aggregate
  ├─ Output candidates→ ├─ Download media    └─ Update state     ├─ Create Release
  └─ Update archive     ├─ Thumbnail WebP                        └─ Write manifest
                        ├─ Save URL archive
                        └─ Git commit
```

### State Machine

```
discovered → processing → media_ready → subtitle_ready → staged → released
                                      (any stage → failed)
```

## Media Policy Engine

Decision priority (see `POLICY.md` for details):

| Priority | Condition                                             | Decision          |
| -------- | ----------------------------------------------------- | ----------------- |
| 1        | Live stream + audio_only_live=true                    | **Audio only**    |
| 2        | Duration >= long_form_minutes                         | **Audio only**    |
| 3        | <= preferred_720p_minutes + native 720p within budget | **Native 720p**   |
| 4        | Native 720p exceeds budget + HEVC within budget       | **HEVC 720p**     |
| 5        | HEVC exceeds budget + 480p available                  | **Fallback 480p** |
| 6        | 480p unavailable or exceeds budget + 420p available   | **Fallback 420p** |
| 7        | All above failed                                      | **Audio only**    |

## Subtitle Priority

1. **Manual/native subtitles** (manually uploaded on YouTube)
2. **YouTube auto subtitles** (`--write-auto-subs`)
3. **Whisper ASR** (faster-whisper, CPU, INT8, max 90 minutes)

Configured languages: `zh-Hans`, `zh-Hant`, `zh`, `en`

## CI Parameters

### Manual Daily Workflow Parameters

| Parameter           | Type    | Default | Description                              |
| ------------------- | ------- | ------- | ---------------------------------------- |
| `discovery_mode`    | choice  | `count` | Discovery mode: `count`/`time`           |
| `max_history_count` | string  | `10`    | Items to backtrack in count mode         |
| `publish_after`     | string  | `""`    | Start date in time mode                  |
| `publish_before`    | string  | `""`    | End date in time mode                    |
| `skip_download`     | boolean | `false` | Discovery + decision only, skip download |

### Manual Weekly Release Parameters

| Parameter       | Type    | Default | Description                                   |
| --------------- | ------- | ------- | --------------------------------------------- |
| `days_lookback` | string  | `10`    | Days to look back for staging artifacts       |
| `force_dry_run` | boolean | `false` | Generate manifest only, skip Release creation |
| `custom_title`  | string  | `""`    | Custom Release title                          |

## Commit Rules

```bash
# Pre-push checks
uv run ruff check scripts/ tests/ --fix
uv run ruff format scripts/ tests/
uv run pytest tests/ -v
```

Commit format:
```
feat: <short title>

- <detailed change 1>
- <detailed change 2>
```

## Permissions

GitHub Actions requires:
- `contents: write` — commit subtitles/thumbnails/URLs/state, create Releases
- `actions: read` — download previous staging artifacts

## License

This is a scaffold template. Comply with YouTube's Terms of Service and target channel content policies when using.