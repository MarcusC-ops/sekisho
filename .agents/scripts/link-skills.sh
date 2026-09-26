#!/usr/bin/env bash
# Link skills from .agents/ to where each agent looks for them.
#
#   .agents/scripts/link-skills.sh         create, repair and prune the symlinks
#   .agents/scripts/link-skills.sh check   change nothing; exit 1 if a shared skill's link is
#                                          missing, wrong, dangling or not staged (pre-commit)
#
# Cursor and Codex read .agents/skills/ natively. Claude Code only reads .claude/skills/, so
# each shared skill gets a committed symlink there. No agent reads .agents/skills-local/, so
# each private skill gets machine-local symlinks in .agents/skills/ and .claude/skills/, kept
# out of git through .git/info/exclude. Written for bash 3.2, the macOS default: no
# associative arrays.
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$AGENTS_DIR/.." && pwd)"
TARGETS=(".claude/skills") # skill dirs of agents that don't read .agents/skills/ themselves
MODE="${1:-apply}"
case "$MODE" in
    apply | check) ;;
    *) echo "usage: $0 [check]" >&2; exit 2 ;;
esac

IN_GIT=false
git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 && IN_GIT=true
problems=0

problem() {
    echo "link-skills: $1" >&2
    problems=$((problems + 1))
}

exclude_locally() {
    $IN_GIT || return 0
    local exclude
    exclude="$(git -C "$REPO_ROOT" rev-parse --git-path info/exclude)"
    case "$exclude" in /*) ;; *) exclude="$REPO_ROOT/$exclude" ;; esac
    mkdir -p "$(dirname "$exclude")"
    grep -qxF "/$1" "$exclude" 2>/dev/null || echo "/$1" >>"$exclude"
}

# link <path from repo root> <symlink target> <shared|private>
link() {
    local rel="$1" target="$2" kind="$3" path="$REPO_ROOT/$1"
    if [ -L "$path" ] && [ "$(readlink "$path")" = "$target" ]; then
        if [ "$MODE" = check ] && [ "$kind" = shared ] && $IN_GIT &&
            ! git -C "$REPO_ROOT" ls-files --error-unmatch "$rel" >/dev/null 2>&1; then
            problem "$rel is not staged (git add $rel)"
        fi
        return 0
    fi
    if [ -e "$path" ] && [ ! -L "$path" ]; then
        echo "link-skills: $rel exists but is not a symlink; move it into .agents/" >&2
        exit 1
    fi
    if [ "$MODE" = check ]; then
        # Private skills are machine-local, so a missing link is not a repo problem.
        [ "$kind" = shared ] && problem "$rel is missing or points elsewhere (run .agents/scripts/link-skills.sh)"
        return 0
    fi
    mkdir -p "$(dirname "$path")"
    ln -sfn "$target" "$path"
    [ "$kind" = private ] && exclude_locally "$rel"
    echo "Linked: $rel -> $target"
}

# prune <dir>: remove links into .agents/ whose skill is gone. No trailing slash on the
# glob, so dangling links (which are not directories) still match.
prune() {
    local dir="$1" path target rel
    for path in "$REPO_ROOT/$dir"/*; do
        [ -L "$path" ] || continue
        target="$(readlink "$path")"
        case "$target" in ../../.agents/skills/* | ../../.agents/skills-local/* | ../skills-local/*) ;; *) continue ;; esac
        [ -d "$path" ] && continue
        rel="$dir/$(basename "$path")"
        if [ "$MODE" = check ]; then
            case "$target" in
                ../../.agents/skills/*) problem "$rel points to a deleted skill (run .agents/scripts/link-skills.sh)" ;;
            esac
        else
            rm "$path"
            echo "Pruned: $rel"
        fi
    done
}

for dir in "$AGENTS_DIR"/skills-local/*/; do
    [ -d "$dir" ] || continue
    name="$(basename "$dir")"
    if [ -d "$AGENTS_DIR/skills/$name" ] && [ ! -L "$AGENTS_DIR/skills/$name" ]; then
        echo "link-skills: '$name' is in both skills/ and skills-local/; rename one" >&2
        exit 1
    fi
done

for dir in "$AGENTS_DIR"/skills/*/; do
    name="$(basename "$dir")"
    # Symlinks in skills/ are the private links made below, not shared skills.
    [ -d "$dir" ] && [ ! -L "${dir%/}" ] || continue
    for target_dir in "${TARGETS[@]}"; do
        link "$target_dir/$name" "../../.agents/skills/$name" shared
    done
done

for dir in "$AGENTS_DIR"/skills-local/*/; do
    [ -d "$dir" ] || continue
    name="$(basename "$dir")"
    link ".agents/skills/$name" "../skills-local/$name" private
    for target_dir in "${TARGETS[@]}"; do
        link "$target_dir/$name" "../../.agents/skills-local/$name" private
    done
done

for target_dir in "${TARGETS[@]}"; do
    prune "$target_dir"
done
prune ".agents/skills"

[ "$problems" -eq 0 ]
