#!/usr/bin/env bash
# Run on hive; the public model is downloaded without user content or credentials.
set -Eeuo pipefail
umask 027
readonly MODEL_DIR=/apps/focus-hive-site-babelfish/qwen
readonly MODEL_FILE="${MODEL_DIR}/Qwen_Qwen3.5-4B-Q5_K_M.gguf"
readonly MODEL_SHA256=21c4643259ce62ffd979848e5819ce03823fd9e9902279ab54cc0d572d83d33e
readonly MODEL_URL=https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF/resolve/4168f45a16a1290d65a4ec0fa312ae917a4c15d6/Qwen_Qwen3.5-4B-Q5_K_M.gguf

install -d -m 0750 -o 10001 -g 10001 "${MODEL_DIR}"
if [[ -f "${MODEL_FILE}" ]] && echo "${MODEL_SHA256}  ${MODEL_FILE}" | sha256sum --check --status; then
  echo 'Qwen3.5-4B Q5_K_M is already installed and verified'
  exit 0
fi

echo 'Downloading Qwen3.5-4B Q5_K_M (3.44 GB)...'
curl --fail --location --retry 3 --no-progress-meter \
  --output "${MODEL_FILE}.part" "${MODEL_URL}"
echo "${MODEL_SHA256}  ${MODEL_FILE}.part" | sha256sum --check
chown 10001:10001 "${MODEL_FILE}.part"
chmod 0640 "${MODEL_FILE}.part"
mv -- "${MODEL_FILE}.part" "${MODEL_FILE}"
echo 'Qwen3.5-4B Q5_K_M installed and verified'
