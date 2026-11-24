#!/usr/bin/env bash
set -Eeuo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
compose=(docker compose --profile miniapp)

# Recreate only the tunnel so its logs always contain the current URL.
"${compose[@]}" up -d --build --wait --wait-timeout 75 miniapp-api
"${compose[@]}" up -d --no-deps --force-recreate miniapp-tunnel

for ((attempt = 0; attempt < 30; attempt++)); do
    logs=$("${compose[@]}" logs --no-color miniapp-tunnel)
    if [[ "$logs" =~ https://[a-z0-9-]+\.trycloudflare\.com ]]; then
        origin="${BASH_REMATCH[0]}"
        if curl -fsS --max-time 3 "$origin/miniapp/" >/dev/null; then
            status=$(curl -sS --max-time 3 -o /dev/null -w '%{http_code}' \
                "$origin/search?q=preview-check") || status=""
            if [[ "$status" == "401" ]]; then
                CRYCON_MINIAPP_URL="$origin/miniapp/" "${compose[@]}" up -d --build --no-deps bot
                printf 'Crycon: %s/miniapp/\nSend /start to the bot and choose Open Crycon.\n' "$origin"
                exit 0
            fi
            if [[ "$status" == "200" ]]; then
                "${compose[@]}" stop miniapp-tunnel
                printf 'The API unexpectedly accepted an unauthenticated request. Tunnel stopped.\n' >&2
                exit 1
            fi
        fi
    fi
    sleep 2
done

"${compose[@]}" stop miniapp-tunnel
printf 'The HTTPS preview did not become ready. Check docker compose logs miniapp-tunnel.\n' >&2
exit 1
