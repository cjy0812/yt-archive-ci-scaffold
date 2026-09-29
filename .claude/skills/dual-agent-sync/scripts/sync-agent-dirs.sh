#!/bin/sh
# sync-agent-dirs.sh
# Bidirectional sync: .claude/skills/ <-> .trae/skills/
# Pure POSIX sh - works on Linux, macOS, Git Bash (Windows)
#
# Usage:
#   sync-agent-dirs.sh              # bidirectional sync (detect & sync)
#   sync-agent-dirs.sh --check      # check only, exit 0=sync, 1=diff, 2=error
#   sync-agent-dirs.sh --trae-to-claude  # one-way: .trae/skills/ -> .claude/skills/
#   sync-agent-dirs.sh --claude-to-trae  # one-way: .claude/skills/ -> .trae/skills/

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_SKILLS="${ROOT_DIR}/.claude/skills"
TRAE_SKILLS="${ROOT_DIR}/.trae/skills"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { printf "${CYAN}[INFO]${NC} %s\n" "$1"; }
log_ok()    { printf "${GREEN}[OK]${NC} %s\n" "$1"; }
log_warn()  { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }
log_error() { printf "${RED}[ERROR]${NC} %s\n" "$1"; }

dir_diff() {
    _src="$1"
    _dst="$2"
    if [ ! -d "$_src" ]; then
        return 2
    fi
    if [ ! -d "$_dst" ]; then
        return 1
    fi
    git diff --no-index --quiet "$_src" "$_dst" >/dev/null 2>&1
    return $?
}

sync_dir() {
    _src="$1"
    _dst="$2"
    _label="$3"

    if [ ! -d "$_src" ]; then
        log_error "Source directory not found: $_src"
        return 2
    fi

    if [ -d "$_dst" ]; then
        rm -rf "$_dst"
    fi

    mkdir -p "$(dirname "$_dst")"
    cp -r "$_src" "$_dst"

    log_ok "Synced: $_label"
}

MODE="${1:-sync}"

if [ ! -d "$TRAE_SKILLS" ]; then
    if [ "$MODE" = "--check" ]; then
        log_warn ".trae/skills/ not found, skip sync check"
        exit 0
    fi
    log_warn ".trae/skills/ not found, nothing to sync"
    exit 0
fi

if [ ! -d "$CLAUDE_SKILLS" ]; then
    if [ "$MODE" = "--check" ]; then
        log_warn ".claude/skills/ not found, treating as empty"
        exit 1
    fi
fi

case "$MODE" in
    --check)
        if dir_diff "$TRAE_SKILLS" "$CLAUDE_SKILLS"; then
            log_ok ".trae/skills/ <-> .claude/skills/ in sync"
            exit 0
        else
            log_error ".trae/skills/ <-> .claude/skills/ NOT in sync!"
            exit 1
        fi
        ;;

    --trae-to-claude)
        log_info "Syncing .trae/skills/ -> .claude/skills/ ..."
        sync_dir "$TRAE_SKILLS" "$CLAUDE_SKILLS" ".trae/skills/ -> .claude/skills/"
        exit 0
        ;;

    --claude-to-trae)
        log_info "Syncing .claude/skills/ -> .trae/skills/ ..."
        sync_dir "$CLAUDE_SKILLS" "$TRAE_SKILLS" ".claude/skills/ -> .trae/skills/"
        exit 0
        ;;

    sync|"")
        if dir_diff "$TRAE_SKILLS" "$CLAUDE_SKILLS"; then
            log_ok ".trae/skills/ <-> .claude/skills/ already in sync"
            exit 0
        fi

        log_warn "Detected difference between .trae/skills/ and .claude/skills/"

        if [ ! -d "$CLAUDE_SKILLS" ]; then
            log_info "No .claude/skills/ found, syncing .trae -> .claude"
            sync_dir "$TRAE_SKILLS" "$CLAUDE_SKILLS" ".trae/skills/ -> .claude/skills/"
            exit 0
        fi

        trae_newer=0
        claude_newer=0
        if [ -d "$TRAE_SKILLS" ]; then
            trae_ts=$(find "$TRAE_SKILLS" -type f -newer "$CLAUDE_SKILLS" 2>/dev/null | head -1)
            if [ -n "$trae_ts" ]; then
                trae_newer=1
            fi
        fi
        if [ -d "$CLAUDE_SKILLS" ]; then
            claude_ts=$(find "$CLAUDE_SKILLS" -type f -newer "$TRAE_SKILLS" 2>/dev/null | head -1)
            if [ -n "$claude_ts" ]; then
                claude_newer=1
            fi
        fi

        if [ "$trae_newer" = "1" ] && [ "$claude_newer" = "0" ]; then
            log_info ".trae/skills/ is newer, syncing -> .claude/skills/"
            sync_dir "$TRAE_SKILLS" "$CLAUDE_SKILLS" ".trae/skills/ -> .claude/skills/"
        elif [ "$claude_newer" = "1" ] && [ "$trae_newer" = "0" ]; then
            log_info ".claude/skills/ is newer, syncing -> .trae/skills/"
            sync_dir "$CLAUDE_SKILLS" "$TRAE_SKILLS" ".claude/skills/ -> .trae/skills/"
        else
            log_warn "Both sides modified or timestamps unclear"
            log_info "Defaulting: .trae/skills/ -> .claude/skills/ (commit-time priority)"
            sync_dir "$TRAE_SKILLS" "$CLAUDE_SKILLS" ".trae/skills/ -> .claude/skills/"
        fi
        exit 0
        ;;

    *)
        log_error "Unknown mode: $MODE"
        log_info "Usage: $0 [--check|--trae-to-claude|--claude-to-trae]"
        exit 2
        ;;
esac