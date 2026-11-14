#!/usr/bin/env bash
# Checks for the dashboard's JavaScript (plain ES modules with JSDoc types; there is no build step).
#
#   1. Syntax: every module must parse. Needs only Node.
#   2. Types:  `tsc --checkJs` over the JSDoc annotations. Runs when a TypeScript compiler is
#              available: `tsc` on PATH, or TSC=/path/to/tsc.js, or `--fetch` to let npx download
#              TypeScript 5.9.3. Skipped with a message otherwise; it is never silently passed.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
files=(src/rootcause_app/static/js/*.js)

for f in "${files[@]}"; do
  node --input-type=module --check < "$f"
done
echo "syntax: ${#files[@]} modules parse"

flags=(--allowJs --checkJs --noEmit --target es2022 --module esnext --moduleResolution bundler
       --lib es2022,dom,dom.iterable --strict --noImplicitAny false --skipLibCheck)
if [[ -n "${TSC:-}" ]]; then
  node "$TSC" "${flags[@]}" "${files[@]}"
elif command -v tsc >/dev/null 2>&1; then
  tsc "${flags[@]}" "${files[@]}"
elif [[ "${1:-}" == "--fetch" ]]; then
  npx --yes --package typescript@5.9.3 tsc "${flags[@]}" "${files[@]}"
else
  echo "types: SKIPPED (no TypeScript compiler found; install one, set TSC, or pass --fetch)"
  exit 0
fi
echo "types: ok"
