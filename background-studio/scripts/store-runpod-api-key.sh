#!/bin/bash

set -euo pipefail

SERVICE="background-studio-runpod"
ACCOUNT="api-key"

if ! command -v security >/dev/null 2>&1; then
  echo "macOS Keychain command 'security' was not found." >&2
  exit 1
fi

read -r -s -p "Paste the restricted Runpod API key: " api_key
printf "\n"

if [[ -z "$api_key" ]]; then
  echo "No API key was entered." >&2
  exit 1
fi

security add-generic-password \
  -U \
  -s "$SERVICE" \
  -a "$ACCOUNT" \
  -w "$api_key" \
  >/dev/null

unset api_key
echo "Runpod API key stored in macOS Keychain."
