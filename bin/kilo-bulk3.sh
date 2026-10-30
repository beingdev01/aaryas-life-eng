#!/usr/bin/env bash
# kilo-bulk3.sh — Bulk-3 agent: bulk implementation on Kilo free lane (Poolside Laguna-S, code-specialized).
# Uses the anonymous Kilo gateway (:free suffix = no sign-in). No NIM key needed.
# Thin wrapper: picks the model + agent name, then runs the shared runner.
export KILO_MODEL="kilo/poolside/laguna-s-2.1:free"
export NIM_AGENT_NAME="bulk-3"
exec "$(dirname "${BASH_SOURCE[0]}")/kilo-runner.sh" "$@"
