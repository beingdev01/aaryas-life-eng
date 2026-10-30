#!/usr/bin/env bash
# unblock-engineer-when-free.sh — AAR-80 (Engineer plan) was parked as blocked
# due to runner.lock contention with AAR-79 (qoder-1). This waits for AAR-79
# to complete, then unblocks AAR-80 by setting it back to in_progress.
# Created 17 Oct 2026.
set -u
export PATH="/home/ubuntu/.local/bin:/usr/bin:/bin"

QODER_ISSUE="609dfd14-6862-40e7-903e-c22600f198c5"
ENGINEER_ISSUE="ebbe8d34-9870-425e-a822-49acacebe09f"
MAX_WAIT=3600  # 1 hour max
POLL=60

echo "Waiting for AAR-79 ($QODER_ISSUE) to complete..."
elapsed=0
while [ $elapsed -lt $MAX_WAIT ]; do
  STATUS=$(paperclipai issue get "$QODER_ISSUE" --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null)
  echo "$(date -u +%H:%M:%S) AAR-79 status=$STATUS"
  if [ "$STATUS" = "done" ]; then
    echo "AAR-79 done. Unblocking AAR-80..."
    paperclipai issue update "$ENGINEER_ISSUE" --status in_progress --comment "Auto-unblock: AAR-79 completed, runner lock should be free. Retrying Engineer plan." 2>&1 | head -5
    echo "Unblock attempted."
    exit 0
  fi
  if [ "$STATUS" = "blocked" ] || [ "$STATUS" = "failed" ]; then
    echo "AAR-79 is $STATUS — NOT unblocking AAR-80, needs CEO review."
    exit 1
  fi
  sleep $POLL
  elapsed=$((elapsed + POLL))
done
echo "Timeout waiting for AAR-79. AAR-80 remains blocked."
exit 1
