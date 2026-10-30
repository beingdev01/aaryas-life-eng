#!/usr/bin/env bash
# kilo-research1.sh — research-1 agent: research on Kilo anonymous free lane.
# Thin wrapper: sets the agent name for charter/role injection, then runs the shared runner.
export NIM_AGENT_NAME="research-1"
exec "$(dirname "${BASH_SOURCE[0]}")/kilo-runner.sh" "$@"
