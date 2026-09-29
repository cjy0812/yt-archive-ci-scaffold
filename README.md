# yt-archive-ci

[English](README_en.md)

一个基于 GitHub Actions 的增量式 YouTube 归档流水线。

## 目标

- 每天检查一次已配置的 YouTube 频道。
- 避免反复扫描/下载旧视频。
- 优先使用 YouTube 原生字幕；只有在没有可用字幕时才运行 Whisper。
- 将字幕保存到 Git 中。
- 将媒体保存为短期 Actions 产物，并发布到定期的 GitHub Release 中。
- 使用基于资源预算的媒体策略：
  1. 普通视频 <= 18 分钟：优先 720p；
  2. 如果预估的 720p 资源过大，则下载 720p，并且仅在值得时进行 HEVC 压缩；
  3. 如果 HEVC 仍超出预算，则回退到 480p/420p；
  4. 如果视频仍然过大，则仅保留音频；
  5. 直播/超长内容：仅保留音频。
- 永远不要将视频/音频二进制文件提交到 Git 历史中。

## 重要

本项目适用于你有权归档/再分发的内容。GitHub Actions/Release 不应用于不受限制的视频 CDN，也不应用于绕过 YouTube 访问控制。

## 目录结构

```text
channels.txt
config.toml
scripts/
  discover.py
  process.py
  subtitle.py
  release.py
subtitles/
  <channel>/
.github/workflows/
  daily.yml
  weekly-release.yml
```

## 本地开发

使用 Python 3.11+。

```bash
python -m venv .venv
# Windows：
.venv\Scripts\activate
# Linux/macOS：
# source .venv/bin/activate
pip install -r requirements.txt
```

生产工作流应安装固定版本的工具，并使用 GitHub 托管运行器自带的 ffmpeg。

## 策略

在启用公开 Releases 之前，请参阅 `POLICY.md`。