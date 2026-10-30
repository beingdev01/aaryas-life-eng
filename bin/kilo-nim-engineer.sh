#!/usr/bin/env bash
# kilo-nim-engineer.sh — Engineer agent: planning + hard reasoning on NIM Nemotron-3-Ultra.
# Migrated 14 Oct 2026 off the flaky anonymous Kilo lane to keyed NIM (same model family).
# Thin wrapper: picks the model + agent name, then runs the shared runner.
export KILO_MODEL="nvidia-nim/nvidia/nemotron-3-ultra-550b-a55b"
# Nemotron-3-Ultra is a heavy reasoner: planning tasks need well beyond
# the default budget. 40 min prevents the timeout-kill failures of 16 Oct 2026.
export KILO_TIMEOUT="2400"
export NIM_AGENT_NAME="Engineer"
exec "$(dirname "${BASH_SOURCE[0]}")/kilo-runner.sh" "$@"
