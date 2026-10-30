#!/usr/bin/env bash
# kilo-nim-bulk2.sh — Bulk-2 agent: parallel bulk implementation on NIM Nemotron-3-Super.
# Thin wrapper: picks the model + agent name, then runs the shared runner.
export KILO_MODEL="nvidia-nim/nvidia/nemotron-3-super-120b-a12b"
export NIM_AGENT_NAME="bulk-2"
exec "$(dirname "${BASH_SOURCE[0]}")/kilo-runner.sh" "$@"
