#!/bin/zsh
# Publishes a new version. Within a day, everyone's app and connector show a
# notification telling them to update.
#
#   ./release.sh 1.2.0
#
# Steps: run the tests, set the version, tag it, point the Homebrew formula at the
# new tag, and only then publish the GitHub release, which is what the update
# check looks at. That way nobody is told to update before `brew upgrade` works.
set -euo pipefail
cd "$(dirname "$0")"

V="${1:?usage: ./release.sh <version, e.g. 1.2.0>}"
REPO="dimitri-saha/human-typer"
TAP_REPO="dimitri-saha/homebrew-tap"

[[ -z "$(git status --porcelain)" ]] || { echo "Commit or stash your changes first." >&2; exit 1; }
[[ "$(git branch --show-current)" == main ]] || { echo "Release from the main branch." >&2; exit 1; }
git pull -q --ff-only
python3 -m unittest discover -s tests

sed -i '' "s/^VERSION = \".*\"/VERSION = \"$V\"/" human_typer/update.py
git diff --quiet || git commit -qam "Release v$V"
git tag "v$V"
git push -q origin main "v$V"

URL="https://github.com/$REPO/archive/refs/tags/v$V.tar.gz"
SHA="$(curl -fsSL "$URL" | shasum -a 256 | cut -d' ' -f1)"
TAP="$(mktemp -d)"
gh repo clone "$TAP_REPO" "$TAP" -- -q
sed -i '' -e "s|^  url .*|  url \"$URL\"|" -e "s|^  sha256 .*|  sha256 \"$SHA\"|" "$TAP/Formula/human-typer.rb"
git -C "$TAP" commit -qam "human-typer $V"
git -C "$TAP" push -q
rm -rf "$TAP"

gh release create "v$V" --repo "$REPO" --title "v$V" --generate-notes
echo "Released v$V. Users will be told to update within a day."
