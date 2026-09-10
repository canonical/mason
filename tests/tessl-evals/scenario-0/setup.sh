#!/usr/bin/env bash
# Install a pinned chisel-releases checkout into the working directory, shaped
# like the real thing: one repository, `origin` pointing upstream, one local
# branch per release named `ubuntu-XX.XX`, with `origin/ubuntu-XX.XX` present.
# Pinned by sha so the scenario does not drift with the branch.
#
# Each branch's AGENTS.md tells agents to install mason. That would make the
# baseline arm install the plugin under test, so the section is stripped and
# the fix folded into the pinned commit, leaving a clean tree.
set -euo pipefail

repo="https://github.com/canonical/chisel-releases"

scrub_agents() {
    local f="$1/AGENTS.md"
    [ -f "$f" ] || return 0
    awk '/^## /{skip = ($0 ~ /working on package slices/)} !skip' "$f" > "$f.tmp"
    grep -viE 'mason|chisel-slicer' "$f.tmp" > "$f" || true
    rm -f "$f.tmp"
    if grep -qiE 'mason|chisel-slicer' "$f"; then
        echo "setup: AGENTS.md still mentions mason after scrub" >&2
        exit 1
    fi
}

init_repo() {
    git init -q "$1"
    git -C "$1" remote add origin "$repo"
}

# fetch one pinned branch, scrub it, and make origin/<branch> match the result
# so the local branch and its remote-tracking ref never appear diverged.
add_branch() {
    local dest="$1" branch="$2" sha="$3"
    git -C "$dest" fetch -q --depth 1 origin "$sha"
    git -C "$dest" checkout -q -b "$branch" FETCH_HEAD
    scrub_agents "$dest"
    git -C "$dest" -c user.name=setup -c user.email=setup@localhost \
        commit -q --amend --no-edit -a
    git -C "$dest" update-ref "refs/remotes/origin/$branch" "$branch"
}

init_repo "chisel-releases"
add_branch "chisel-releases" "ubuntu-26.04" "f85285369d90d6eaeef6af394a64fd8747a9644e"
git -C "chisel-releases" checkout -q "ubuntu-26.04"
