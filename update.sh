#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_dir"

if [[ "${1:-}" != "--after-pull" ]]; then
    git pull --ff-only
    exec "$repo_dir/update.sh" --after-pull
fi

docker compose config --quiet
docker compose up -d --build api worker bot
docker compose ps

echo
echo "Crycon runtime is updated. Bot logs: docker compose logs -f bot"
