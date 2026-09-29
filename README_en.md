# yt-archive-ci

A GitHub Actions based, incremental YouTube archive pipeline.

## Goals

- Check configured YouTube channels once per day.
- Avoid scanning/downloading old videos repeatedly.
- Prefer native YouTube subtitles; run Whisper only when no usable subtitle exists.
- Save subtitles in Git.
- Save media as short-lived Actions artifacts and publish them to a periodic GitHub Release.
- Use a resource-budget based media policy:
  1. ordinary video <= 18 min: prefer 720p;
  2. if the estimated 720p asset is too large, download 720p and HEVC-compress only when worthwhile;
  3. if HEVC still exceeds the budget, fall back to 480p/420p;
  4. if video remains too large, keep audio only;
  5. live/very long content: audio only.
- Never commit video/audio binaries to Git history.

## Important

This project is intended for content you are authorized to archive/re-distribute. GitHub Actions/Release is not intended to be used as an unrestricted video CDN or as a way to bypass YouTube access controls.

## Layout

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

## Local development

Use Python 3.11+.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate
pip install -r requirements.txt
```

The production workflow should install pinned tool versions and use the GitHub-hosted runner's ffmpeg.

## Policy

See `POLICY.md` before enabling public Releases.
