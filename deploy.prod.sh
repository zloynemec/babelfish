#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly ENV_FILE="${PROJECT_DIR}/.env.prod"
readonly SSH_TARGET="${HIVE_SSH_TARGET:-root@hive.ohmygames.ru}"
readonly CONTEXT_NAME="${HIVE_DOCKER_CONTEXT:-babelfish-hive}"
readonly EXPECTED_ENDPOINT="ssh://${SSH_TARGET}"
readonly DATA_DIR="/apps/focus-hive-site-babelfish/data"

cd "${PROJECT_DIR}"
for command_name in docker ssh git; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Required command is missing: ${command_name}" >&2
    exit 1
  fi
done
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Create .env.prod from .env.prod.example before deployment" >&2
  exit 1
fi
chmod 600 "${ENV_FILE}"

if docker context inspect "${CONTEXT_NAME}" >/dev/null 2>&1; then
  actual_endpoint="$(docker context inspect "${CONTEXT_NAME}" --format '{{.Endpoints.docker.Host}}')"
  if [[ "${actual_endpoint}" != "${EXPECTED_ENDPOINT}" ]]; then
    echo "Docker context ${CONTEXT_NAME} points to ${actual_endpoint}, expected ${EXPECTED_ENDPOINT}" >&2
    exit 1
  fi
else
  docker context create "${CONTEXT_NAME}" --docker "host=${EXPECTED_ENDPOINT}"
fi

compose() {
  docker --context "${CONTEXT_NAME}" compose \
    --env-file "${ENV_FILE}" -f "${PROJECT_DIR}/docker-compose.prod.yml" "$@"
}

export DEPLOY_REVISION="$(git rev-parse HEAD)"
compose config --quiet
docker --context "${CONTEXT_NAME}" info >/dev/null
docker --context "${CONTEXT_NAME}" network inspect traefik >/dev/null

echo "Preparing BabelFish model storage on hive..."
ssh -o BatchMode=yes "${SSH_TARGET}" \
  "install -d -m 0700 -o 10001 -g 10001 '${DATA_DIR}'"

echo "Building BabelFish on hive..."
compose build --pull babelfish

echo "Installing the default en -> ru Argos model..."
compose run --rm --no-deps babelfish python scripts/install_argos_model.py --from en --to ru

echo "Starting BabelFish..."
compose up -d --wait --wait-timeout 240 babelfish
compose exec -T babelfish python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=30).close()"
compose ps
echo "Deployment complete. Check the HTTPS endpoints described in docs/10-hive-deployment.md."
