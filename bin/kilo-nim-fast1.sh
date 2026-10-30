#!/usr/bin/env bash
# kilo-nim-fast1.sh — Fast-1 agent: high-throughput small tasks on NIM Nemotron-3.5-Lightning.
# Thin wrapper: picks the model + agent name, then runs the shared runner.
export KILO_MODEL="nvidia-nim/nvidia/nemotron-3.5-lightning-30b-a3b"
export NIM_AGENT_NAME="fast-1"
exec "$(dirname "${BASH_SOURCE[0]}")/kilo-runner.sh" "$@"
