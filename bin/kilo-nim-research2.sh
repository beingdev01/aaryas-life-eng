#!/usr/bin/env bash
# kilo-nim-research2.sh — Research-2 agent: deep research on NIM Nemotron-3-Ultra.
# Thin wrapper: picks the model + agent name, then runs the shared runner.
export KILO_MODEL="nvidia-nim/nvidia/nemotron-3-ultra-550b-a55b"
export NIM_AGENT_NAME="research-2"
exec "$(dirname "${BASH_SOURCE[0]}")/kilo-runner.sh" "$@"
