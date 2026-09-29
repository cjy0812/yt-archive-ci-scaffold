#!/bin/sh
# post-checkout hook
# After git checkout/switch/clone, sync .claude/skills/ -> .trae/skills/
# Trigger ONLY when .trae/ exists AND content is out of sync
#
# Arguments: $1=prev_head $2=new_head $3=is_branch_checkout (1=branch, 0=file)

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SYNC_SCRIPT="${ROOT_DIR}/scripts/sync-agent-dirs.sh"

if [ ! -d "${ROOT_DIR}/.trae/skills" ]; then
    exit 0
fi

if [ ! -f "$SYNC_SCRIPT" ]; then
    exit 0
fi

if sh "$SYNC_SCRIPT" --check >/dev/null 2>&1; then
    exit 0
fi

sh "$SYNC_SCRIPT" --claude-to-trae

exit 0