#!/usr/bin/env bash
# Batch re-draft a list of job posting UUIDs against the running job-search-api pod.
# Edit JOB_IDS below to target a different set of applications.
#
# Usage: batch_redraft.sh [--model <model_id>]
#   --model   Bedrock model ID override (default: us.anthropic.claude-sonnet-5)
#             e.g. --model us.anthropic.claude-sonnet-4-6
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODEL="us.anthropic.claude-sonnet-5"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# Replace this list with any set of job posting UUIDs to re-draft.
JOB_IDS=(
  "34121b3b-ec28-4a7f-979a-83cc7773adfc"  # JPMorgan Chase
  "f54f8212-6ef4-4c82-bb62-00fe5421be6b"  # JPMorgan Chase
  "2f54c00f-4e7a-4022-9e1e-fddbc22faa4f"  # JPMorgan Chase
  "0f451de2-94df-4cb3-9312-995d5a9d315a"  # Capital Group
  "5d63f676-57c7-4313-8185-af5b496344b2"  # JPMorgan Chase
  "a09a1df9-2038-4b9b-a9ff-ea0bf4c11da0"  # Citi
  "49b9eb6f-79eb-47b3-9883-bf474ab1f057"  # Anthropic
  "fde73441-41fe-480c-aec2-48990f1b1643"  # Citi
  "48807321-bf92-4bcf-acde-f1a48050c5b6"  # Fidelity International
  "eb66ef2c-919f-478a-ac58-04c23341e6d2"  # Morgan Stanley
  "cf61c5f6-4940-40ea-85e7-58d9b31d6a33"  # AIG
  "6915f39e-a7c4-4e6c-877e-f1846f00cd6b"  # JPMorgan Chase
)

export KUBECONFIG="${KUBECONFIG:-/home/mccoole/.kube/config-oc-platform}"

NS=$(kubectl get pods -A --no-headers | grep job-search-api | grep Running | head -1 | awk '{print $1}')
POD=$(kubectl get pods -A --no-headers | grep job-search-api | grep Running | head -1 | awk '{print $2}')

if [[ -z "$POD" ]]; then
  echo "Error: no running job-search-api pod found" >&2
  exit 1
fi

echo "Pod:   $NS/$POD"
echo "Model: $MODEL"
echo "Jobs:  ${#JOB_IDS[@]}"
echo ""

kubectl exec -i -n "$NS" "$POD" -- python3 - --model "$MODEL" "${JOB_IDS[@]}" < "$SCRIPT_DIR/batch_redraft.py"
