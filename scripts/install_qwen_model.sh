#!/usr/bin/env bash
# Run on hive; the public model is downloaded without user content or credentials.
set -Eeuo pipefail
umask 027
readonly MODEL_DIR=/apps/focus-hive-site-babelfish/qwen
readonly MODEL_FILE="${MODEL_DIR}/Qwen3-4B-Q4_K_M.gguf"
readonly MODEL_SHA256=7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5
readonly MODEL_URL=https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf

install -d -m 0750 -o 10001 -g 10001 "${MODEL_DIR}"
if [[ -f "${MODEL_FILE}" ]] && echo "${MODEL_SHA256}  ${MODEL_FILE}" | sha256sum --check --status; then
  echo 'Qwen3-4B Q4_K_M is already installed and verified'
  exit 0
fi

echo 'Downloading Qwen3-4B Q4_K_M (2.5 GB)...'
curl --fail --location --retry 3 --no-progress-meter \
  --output "${MODEL_FILE}.part" "${MODEL_URL}"
echo "${MODEL_SHA256}  ${MODEL_FILE}.part" | sha256sum --check
chown 10001:10001 "${MODEL_FILE}.part"
chmod 0640 "${MODEL_FILE}.part"
mv -- "${MODEL_FILE}.part" "${MODEL_FILE}"
echo 'Qwen3-4B Q4_K_M installed and verified'
