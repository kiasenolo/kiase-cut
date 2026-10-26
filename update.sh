#!/usr/bin/env bash
# Update KiaseCut on Linux: pull the latest version from GitHub into this folder. Only a
# fast-forward is done, so local changes are never merged over; the next
# ./start_kiasecut.sh installs any missing packages.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

if ! command -v git >/dev/null 2>&1; then
    echo "git not found. Install it, e.g.: sudo apt install git"
    exit 1
fi
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "This folder is not a git checkout. Get KiaseCut with:"
    echo "  git clone https://github.com/kiasenolo/kiase-cut"
    exit 1
fi

before=$(git rev-parse HEAD)
if ! git pull --ff-only; then
    echo "Update failed (see above). Changes made in this folder can block it: git status lists them."
    exit 1
fi
if [ "$(git rev-parse HEAD)" != "$before" ]; then
    echo "New in this update:"
    git log --oneline "$before..HEAD"
fi
