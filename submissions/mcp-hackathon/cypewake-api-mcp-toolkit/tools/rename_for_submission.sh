#!/usr/bin/env bash
#
# rename_for_submission.sh · rename the submission directory to the official required name
#
# Official path: submissions/mcp-hackathon/<team-or-builder>-<project-slug>/
# This submission's name should be: <your GitHub username>-api-mcp-toolkit
#
# Usage:
#   bash tools/rename_for_submission.sh <your GitHub username>
#
# By default it runs a dry run (prints the actions only). Add --apply to actually execute:
#   bash tools/rename_for_submission.sh <username> --apply
#
set -euo pipefail

USERNAME="${1:-}"
MODE="${2:-}"

if [[ -z "$USERNAME" ]]; then
  echo "Usage: bash tools/rename_for_submission.sh <your GitHub username> [--apply]" >&2
  echo "Example: bash tools/rename_for_submission.sh octocat --apply" >&2
  exit 2
fi

# GitHub username rules: alphanumeric and hyphens, cannot start/end with a hyphen, max 39 chars
if [[ ! "$USERNAME" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?$ ]]; then
  echo "Error: '$USERNAME' is not a valid GitHub username (alphanumeric and hyphens only, cannot start or end with a hyphen)" >&2
  exit 2
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname "$PROJECT_DIR")"
TARGET_NAME="${USERNAME}-api-mcp-toolkit"
TARGET_DIR="${PARENT}/${TARGET_NAME}"

echo "Project directory : $PROJECT_DIR"
echo "Target directory  : $TARGET_DIR"
echo

if [[ "$PROJECT_DIR" == "$TARGET_DIR" ]]; then
  echo "Directory name is already ${TARGET_NAME}, no rename needed."
  exit 0
fi

if [[ -e "$TARGET_DIR" ]]; then
  echo "Error: target directory already exists, please handle first: $TARGET_DIR" >&2
  exit 1
fi

if [[ "$MODE" != "--apply" ]]; then
  echo "[dry-run mode] will execute:"
  echo "  mv \"$PROJECT_DIR\" \"$TARGET_DIR\""
  echo
  echo "Re-run with --apply to confirm."
  exit 0
fi

mv "$PROJECT_DIR" "$TARGET_DIR"
echo "Renamed -> $TARGET_DIR"
echo
echo "Next steps:"
echo "  1) cd \"$TARGET_DIR\""
echo "  2) Fork https://github.com/xagentAI/xagt-plugin and clone it locally"
echo "  3) Copy this directory into <fork>/submissions/mcp-hackathon/${TARGET_NAME}/"
echo "  4) git add -A && git add -f verification-evidence.md docs/ && git commit -m \"feat: ${TARGET_NAME} · Open Innovation\""
echo "  5) After push, open a PR in the official repo (title must include project name + Open Innovation)"
