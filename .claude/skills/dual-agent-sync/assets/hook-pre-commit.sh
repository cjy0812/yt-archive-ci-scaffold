#!/bin/sh
# pre-commit hook
# Trigger ONLY when staged area has .claude/skills/ or .trae/ changes,
# OR when .trae/skills/ and .claude/skills/ are out of sync (Trae-side edits)

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SYNC_SCRIPT="${ROOT_DIR}/scripts/sync-agent-dirs.sh"

if [ ! -f "$SYNC_SCRIPT" ]; then
    exit 0
fi

STAGED_CLAUDE=$(git diff --cached --name-only -- ".claude/skills/" 2>/dev/null)
STAGED_TRAE=$(git diff --cached --name-only -- ".trae/" 2>/dev/null)
NEED_SYNC=false

if [ -n "$STAGED_TRAE" ]; then
    echo "[WARN] .trae/ files found in staging area, auto-unstaging..."
    git reset HEAD -- .trae/ >/dev/null 2>&1
    STAGED_TRAE=""
fi

if [ -n "$STAGED_CLAUDE" ]; then
    NEED_SYNC=true
fi

if [ -d "${ROOT_DIR}/.trae/skills" ]; then
    if ! sh "$SYNC_SCRIPT" --check >/dev/null 2>&1; then
        NEED_SYNC=true
    fi
fi

if [ "$NEED_SYNC" = "false" ]; then
    exit 0
fi

sh "$SYNC_SCRIPT" --trae-to-claude
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to sync .trae/skills/ -> .claude/skills/"
    exit 1
fi

UNCHANGED=$(git diff --name-only -- ".claude/skills/" 2>/dev/null)
if [ -n "$UNCHANGED" ]; then
    git add ".claude/skills/"
fi

exit 0