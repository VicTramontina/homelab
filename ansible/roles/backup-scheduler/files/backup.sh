#!/usr/bin/env bash
# Backs up a single game's volume to Cloudflare R2 via rclone, keeping only
# the most recent N backups for that game (pruned here, not via a bucket
# lifecycle rule, so the "keep last 3" count is exact regardless of upload
# frequency). Called by game-manager before stop_game/shutdown_pc, or
# on-demand via backup_game. Never runs on a schedule of its own.
set -euo pipefail

GAME="${1:?Usage: backup.sh <game>}"
CONFIG=/opt/homelab/config.json
REMOTE=r2

HOMELAB_DIR=$(jq -r '.homelab_dir' "$CONFIG")
BUCKET=$(jq -r '.r2_bucket' "$CONFIG")
KEEP=$(jq -r '.backups_to_keep' "$CONFIG")
VOLUME_PATH=$(jq -r --arg g "$GAME" '.games[$g].volume_path // empty' "$CONFIG")

if [ -z "$VOLUME_PATH" ]; then
  echo "backup.sh: unknown game '${GAME}' (not present in ${CONFIG})" >&2
  exit 1
fi

if [ ! -d "$VOLUME_PATH" ]; then
  echo "backup.sh: volume path '${VOLUME_PATH}' does not exist, nothing to back up" >&2
  exit 1
fi

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE_NAME="${GAME}-${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="${HOMELAB_DIR}/server/backups/${ARCHIVE_NAME}"

mkdir -p "$(dirname "$ARCHIVE_PATH")"
tar -czf "$ARCHIVE_PATH" -C "$(dirname "$VOLUME_PATH")" "$(basename "$VOLUME_PATH")"

echo "backup.sh: uploading ${ARCHIVE_NAME} to ${REMOTE}:${BUCKET}/${GAME}/"
rclone copy "$ARCHIVE_PATH" "${REMOTE}:${BUCKET}/${GAME}/"
rm -f "$ARCHIVE_PATH"

# Prune to keep only the $KEEP most recent backups for this game. Archive
# names sort lexically == chronologically because of the timestamp format.
mapfile -t EXISTING < <(rclone lsf "${REMOTE}:${BUCKET}/${GAME}/" | sort)
COUNT=${#EXISTING[@]}
if [ "$COUNT" -gt "$KEEP" ]; then
  TO_DELETE=$((COUNT - KEEP))
  for i in $(seq 0 $((TO_DELETE - 1))); do
    echo "backup.sh: pruning old backup ${EXISTING[$i]}"
    rclone deletefile "${REMOTE}:${BUCKET}/${GAME}/${EXISTING[$i]}"
  done
fi

date -u +%Y-%m-%dT%H:%M:%SZ > "${HOMELAB_DIR}/last_backup_${GAME}.txt"
echo "backup.sh: done, ${GAME} last_backup timestamp updated"
