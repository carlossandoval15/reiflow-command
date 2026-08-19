#!/bin/bash
# Nightly DealSauce -> ReiFlow Command pipeline. Run by launchd at 4:00 AM.
# 1. Playwright pulls the "preforeclosures w auction" saved search (reusing a
#    session you logged into once — never re-enters your password).
# 2. Parses + dedupes new CSV rows into reiflow_foreclosures.json.
# 3. Bakes the updated JSON into index.html.
# 4. Commits + pushes so GitHub Pages (reiflow-command) picks it up.
# 5. Telegrams you a summary either way.
set -uo pipefail

BIN_DIR="/Users/carlossandoval/reiflow-command/dealsauce-bin"
REPO_DIR="/Users/carlossandoval/reiflow-command"
NOTIFY="/Users/carlossandoval/surplus-command/bin/notify.sh"
LOG_FILE="$BIN_DIR/logs/nightly-pull-$(date +%Y-%m-%d).log"
NODE_BIN="/usr/local/bin/node"
PYTHON_BIN="/usr/bin/python3"

mkdir -p "$BIN_DIR/logs"
exec >> "$LOG_FILE" 2>&1

echo "===== $(date) ====="
cd "$BIN_DIR" || { "$NOTIFY" "🔴 ReiFlow nightly pull: could not cd to $BIN_DIR"; exit 1; }

echo "--- Step 1: DealSauce pull ---"
PULL_OUTPUT=$("$NODE_BIN" nightly-pull.js 2>&1)
PULL_EXIT=$?
echo "$PULL_OUTPUT"

if [ "$PULL_EXIT" -eq 2 ] || echo "$PULL_OUTPUT" | grep -q "^NEED_LOGIN"; then
  "$NOTIFY" "🟡 ReiFlow nightly pull: DealSauce session expired. Run 'node setup-login.js' in ~/reiflow-command/dealsauce-bin to log back in (no automation will touch your password)."
  exit 2
fi

PULL_SUMMARY=$(echo "$PULL_OUTPUT" | grep '^SUMMARY_JSON:' | sed 's/^SUMMARY_JSON://')
EXPORTED_FILES_COUNT=$(echo "$PULL_SUMMARY" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('exportedFiles',[])))" 2>/dev/null || echo 0)

if [ "$PULL_EXIT" -ne 0 ] && [ "$EXPORTED_FILES_COUNT" = "0" ]; then
  "$NOTIFY" "🔴 ReiFlow nightly pull: DealSauce export failed for every location tonight. Check $LOG_FILE on the Mac."
  exit 1
fi

echo "--- Step 2: Parse + dedupe ---"
PARSE_OUTPUT=$("$PYTHON_BIN" parse_import.py 2>&1)
PARSE_EXIT=$?
echo "$PARSE_OUTPUT"

if [ "$PARSE_EXIT" -ne 0 ]; then
  "$NOTIFY" "🔴 ReiFlow nightly pull: parsing step failed. Check $LOG_FILE on the Mac."
  exit 1
fi

PARSE_SUMMARY=$(echo "$PARSE_OUTPUT" | grep '^SUMMARY_JSON:' | sed 's/^SUMMARY_JSON://')
NEW_LEADS=$(echo "$PARSE_SUMMARY" | "$PYTHON_BIN" -c "import json,sys; print(json.load(sys.stdin).get('newLeadsAdded',0))" 2>/dev/null || echo 0)
TOTAL_LEADS=$(echo "$PARSE_SUMMARY" | "$PYTHON_BIN" -c "import json,sys; print(json.load(sys.stdin).get('totalForeclosureLeads',0))" 2>/dev/null || echo "?")
DUPES=$(echo "$PARSE_SUMMARY" | "$PYTHON_BIN" -c "import json,sys; print(json.load(sys.stdin).get('duplicatesSkipped',0))" 2>/dev/null || echo "?")

if [ "$NEW_LEADS" = "0" ]; then
  "$NOTIFY" "🟡 ReiFlow nightly pull: ran clean but found 0 new addresses tonight ($DUPES duplicates skipped). No update pushed."
  exit 0
fi

echo "--- Step 3: Bake into index.html ---"
BAKE_OUTPUT=$("$PYTHON_BIN" bake.py 2>&1)
BAKE_EXIT=$?
echo "$BAKE_OUTPUT"

if [ "$BAKE_EXIT" -ne 0 ]; then
  "$NOTIFY" "🔴 ReiFlow nightly pull: $NEW_LEADS new leads parsed but baking into index.html failed (data is safe in reiflow_foreclosures.json, just not published). Check $LOG_FILE on the Mac."
  exit 1
fi

echo "--- Step 4: Commit + push ---"
cd "$REPO_DIR" || exit 1
git add -A
git commit -m "Nightly DealSauce pull: +${NEW_LEADS} foreclosure leads ($(date +%Y-%m-%d))

🤖 Automated via dealsauce-bin/nightly-pull.sh" >> "$LOG_FILE" 2>&1
git push origin main >> "$LOG_FILE" 2>&1
PUSH_EXIT=$?

if [ "$PUSH_EXIT" -ne 0 ]; then
  "$NOTIFY" "🟡 ReiFlow nightly pull: +$NEW_LEADS new leads saved locally but git push failed — dashboard not updated yet. Check $LOG_FILE on the Mac."
  exit 1
fi

"$NOTIFY" "🟢 ReiFlow nightly pull: +$NEW_LEADS new pre-foreclosure leads ($DUPES dupes skipped, $TOTAL_LEADS total on the board). Live at https://carlossandoval15.github.io/reiflow-command/"
echo "Done."
