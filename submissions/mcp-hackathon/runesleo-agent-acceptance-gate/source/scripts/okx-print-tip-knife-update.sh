#!/usr/bin/env bash
# Print-only: tip-knife agent description update for #3977.
# Do NOT run while "Listing under review" unless Leo says 改简介/上.
set -euo pipefail
DESC=$(cat "$(dirname "$0")/../research/2026-07-24-tip-knife-agent-description.txt")
echo "# Proposed command (print-only):"
echo "onchainos agent update --agent-id 3977 --description $(printf %q "$DESC")"
echo
echo "# After update, typically:"
echo "# onchainos agent activate --agent-id 3977"
echo "# Then: onchainos agent get --agent-ids 3977"
