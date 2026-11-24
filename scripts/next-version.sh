#!/usr/bin/env bash
# Next release version for .github/workflows/release.yml. Usage: scripts/next-version.sh patch|minor|major
# Prints `next=X.Y.Z` and `tag=vX.Y.Z` (GITHUB_OUTPUT format). Run from the repo root with the tags fetched.
#
# Starts from the highest of pyproject.toml's version and every release tag (vX.Y.Z or X.Y.Z): a release made in the
# GitHub UI tags a version without bumping the files, and the next run must not try to create that version again.
set -euo pipefail

BUMP="${1:-}"
case "$BUMP" in patch | minor | major) ;; *) echo "usage: $0 patch|minor|major" >&2; exit 2 ;; esac

# -m1: the [project] version comes first; later `version =` keys belong to other tables
FROM_FILE=$(grep -m1 -E '^version = "[0-9]+\.[0-9]+\.[0-9]+"' pyproject.toml | cut -d'"' -f2 || true)
if [ -z "$FROM_FILE" ]; then
  echo "::error::No version found in pyproject.toml" >&2
  exit 1
fi
# Plain releases only: prerelease tags (v0.2.0-rc1) and other tags don't count.
FROM_TAGS=$(git tag -l | sed -nE 's/^v?([0-9]+\.[0-9]+\.[0-9]+)$/\1/p')
CURRENT=$(printf '%s\n' "$FROM_FILE" $FROM_TAGS | sort -t. -k1,1n -k2,2n -k3,3n | tail -n1)

IFS=. read -r MAJ MIN PAT <<< "$CURRENT"
case "$BUMP" in
  major) NEXT="$((MAJ + 1)).0.0" ;;
  minor) NEXT="${MAJ}.$((MIN + 1)).0" ;;
  patch) NEXT="${MAJ}.${MIN}.$((PAT + 1))" ;;
esac
for t in "v${NEXT}" "${NEXT}"; do
  if git rev-parse -q --verify "refs/tags/${t}" > /dev/null; then
    echo "::error::Tag ${t} already exists. Bump manually or choose a different increment." >&2
    exit 1
  fi
done
echo "Releasing ${CURRENT} -> ${NEXT} (pyproject.toml: ${FROM_FILE})" >&2
echo "next=${NEXT}"
echo "tag=v${NEXT}"
