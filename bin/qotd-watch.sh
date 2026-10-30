#!/usr/bin/env bash
# qotd-watch.sh — automatic eye on the QOTD publish-state + build progress.
# Created 17 Oct 2026 per owner directive. Updated: only alert on FUTURE
# QOTDs with unpublished problems (historical ones are expected); AAR-80
# superseded by AAR-81 (opencode-1 doing solution-freeze directly).
set -u
export PATH="/home/ubuntu/.local/bin:/usr/bin:/bin"

ISSUES_OK=true
DBURL=$(grep "^DATABASE_URL=" /home/ubuntu/clubsite/api.env | cut -d= -f2- | tr -d "\"'" | cut -d? -f1)
SLUGS="'reverse-integer','pyramid-of-bricks','score-of-parentheses','minimum-add-to-make-parentheses-valid','valid-parenthesis-string','evaluate-reverse-polish-notation'"

# --- 1. Six problems must stay published ---
UNPUB=$(psql "$DBURL" -t -c "SELECT slug FROM problems WHERE slug IN ($SLUGS) AND is_published = false;" 2>/dev/null | grep -v '^$' | wc -l)
if [ "$UNPUB" -gt 0 ]; then
  echo "WATCH: $UNPUB of the 6 QOTD problems are UNPUBLISHED in DB"
  ISSUES_OK=false
fi

# --- 2. (REMOVED 17 Oct 2026) Future QOTDs with unpublished problems no longer
# alert — the publish gate was removed, so unpublished problems can be QOTDs.

# --- 3. AAR-81 (solution-freeze via opencode-1) status ---
AAR81_LINE=$(paperclipai issue list --company-id 469f7950-25cf-4366-8a82-1469c40e278f 2>/dev/null | grep "solution unlock with marks freeze" | grep "aa4e3944" | head -1)
echo "AAR-81 line: $AAR81_LINE" | cut -c1-120
AAR81_ID=$(echo "$AAR81_LINE" | sed 's/.*id=\([a-f0-9-]*\).*/\1/')
if [ -n "$AAR81_ID" ]; then
  S81=$(paperclipai issue get "$AAR81_ID" --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null)
  echo "AAR-81 status=$S81"
  if [ "$S81" = "blocked" ] || [ "$S81" = "failed" ]; then
    echo "WATCH: AAR-81 (solution-freeze) is $S81 — needs CEO attention"
    ISSUES_OK=false
  fi
fi

if [ "$ISSUES_OK" = true ]; then
  echo "OK: all QOTD watches green"
fi
