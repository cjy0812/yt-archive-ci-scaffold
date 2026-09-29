#!/bin/sh
# pre-push hook
# Trigger ONLY when staged area has .claude/skills/ or .trae/ changes
# 1. Verify .trae/skills/ <-> .claude/skills/ are in sync
# 2. Block push if not synced
# 3. Defensive check: ensure .trae/ files are not staged

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SYNC_SCRIPT="${ROOT_DIR}/scripts/sync-agent-dirs.sh"

STAGED_CLAUDE=$(git diff --cached --name-only -- ".claude/skills/" 2>/dev/null)
STAGED_TRAE=$(git diff --cached --name-only -- ".trae/" 2>/dev/null)

if [ -z "$STAGED_CLAUDE" ] && [ -z "$STAGED_TRAE" ]; then
    exit 0
fi

if [ -f "$SYNC_SCRIPT" ] && [ -d "${ROOT_DIR}/.trae/skills" ]; then
    sh "$SYNC_SCRIPT" --check
    CHECK_RESULT=$?
    if [ $CHECK_RESULT -ne 0 ]; then
        echo ""
        echo "[BLOCKED] .trae/skills/ and .claude/skills/ are NOT in sync!"
        echo "  Run: sh scripts/sync-agent-dirs.sh"
        echo "  Then: git add .claude/skills/ && git commit --amend --no-edit"
        echo ""
        exit 1
    fi
fi

if [ -n "$STAGED_TRAE" ]; then
    echo ""
    echo "[BLOCKED] .trae/ files are staged for commit!"
    echo "  .trae/ should NOT be pushed (it is a local Trae IDE working copy)."
    echo "  Remove from staging: git reset HEAD .trae/"
    echo ""
    exit 1
fi

exit 0