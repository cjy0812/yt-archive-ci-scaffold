#!/bin/sh
# install-hooks.sh
# Install dual-agent-sync hooks into a project
# Pure POSIX sh - cross-platform
#
# Usage:
#   install-hooks.sh              # install into current project
#   install-hooks.sh /path/to/proj  # install into specified project

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="${1:-$(pwd)}"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { printf "${CYAN}[INFO]${NC} %s\n" "$1"; }
log_ok()    { printf "${GREEN}[OK]${NC} %s\n" "$1"; }
log_error() { printf "${RED}[ERROR]${NC} %s\n" "$1"; }

if [ ! -d "$TARGET_DIR/.git" ] && [ ! -f "$TARGET_DIR/.git" ]; then
    log_error "Not a Git repository: $TARGET_DIR"
    exit 1
fi

log_info "Installing dual-agent-sync into: $TARGET_DIR"

# 1. Create .githooks directory
mkdir -p "$TARGET_DIR/.githooks"

# 2. Copy hook templates
for hook in pre-commit pre-push post-checkout; do
    SRC="${SCRIPT_DIR}/assets/hook-${hook}.sh"
    DST="$TARGET_DIR/.githooks/${hook}"
    if [ -f "$SRC" ]; then
        cp "$SRC" "$DST"
        chmod +x "$DST" 2>/dev/null || true
        log_ok "Installed .githooks/${hook}"
    else
        log_error "Template not found: $SRC"
    fi
done

# 3. Copy sync script
mkdir -p "$TARGET_DIR/scripts"
SRC="${SCRIPT_DIR}/scripts/sync-agent-dirs.sh"
DST="$TARGET_DIR/scripts/sync-agent-dirs.sh"
if [ -f "$SRC" ]; then
    cp "$SRC" "$DST"
    chmod +x "$DST" 2>/dev/null || true
    log_ok "Installed scripts/sync-agent-dirs.sh"
else
    log_error "Sync script not found: $SRC"
fi

# 4. Append .gitignore fragment
GITIGNORE="$TARGET_DIR/.gitignore"
FRAGMENT="${SCRIPT_DIR}/assets/gitignore-fragment.txt"
if [ -f "$FRAGMENT" ]; then
    NEED_ADD=1
    if [ -f "$GITIGNORE" ]; then
        if grep -q '^\.trae/' "$GITIGNORE" 2>/dev/null; then
            NEED_ADD=0
        fi
    fi
    if [ "$NEED_ADD" = "1" ]; then
        printf "\n# Dual Agent Sync: .trae/ is a local Trae IDE working copy\n" >> "$GITIGNORE"
        cat "$FRAGMENT" >> "$GITIGNORE"
        log_ok "Appended .gitignore fragment"
    else
        log_ok ".gitignore already contains .trae/ rule"
    fi
fi

# 5. Set core.hooksPath
CURRENT_HOOKS=$(git -C "$TARGET_DIR" config --local core.hooksPath 2>/dev/null || echo "")
if [ "$CURRENT_HOOKS" != ".githooks" ]; then
    git -C "$TARGET_DIR" config --local core.hooksPath .githooks
    log_ok "Set core.hooksPath = .githooks"
else
    log_ok "core.hooksPath already set to .githooks"
fi

# 6. Remove .trae/ from git tracking if present
STAGED_TRAE=$(git -C "$TARGET_DIR" ls-files --cached -- ".trae/" 2>/dev/null || echo "")
if [ -n "$STAGED_TRAE" ]; then
    log_info "Removing .trae/ from Git tracking..."
    git -C "$TARGET_DIR" rm -r --cached .trae/ >/dev/null 2>&1 || true
    log_ok "Removed .trae/ from Git index (local files preserved)"
fi

echo ""
log_ok "Installation complete!"
echo ""
echo "Verify: sh $TARGET_DIR/scripts/sync-agent-dirs.sh --check"