#!/bin/bash
# MindLens auto-recovery wrapper
# Restarts on crash, cleans stale lockfile, logs to /tmp/mindlens.log

LOCKFILE="/tmp/mindlens.pid"
LOGFILE="/tmp/mindlens.log"
MAX_RESTARTS=50
RESTART_DELAY=10
restarts=0

cd /Users/kevin/projects/mindlens || exit 1
export MINDLENS_VAULT_PATH="/Users/kevin/Library/CloudStorage/ProtonDrive-kevjac91@proton.me-folder/mindlens"

cleanup() {
    rm -f "$LOCKFILE"
    exit 0
}
trap cleanup SIGTERM SIGINT

while [ $restarts -lt $MAX_RESTARTS ]; do
    # Prevent duplicate: check if mindlens is already running
    existing_pid=$(pgrep -f "\.venv/bin/mindlens" | head -1)
    if [ -n "$existing_pid" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] MindLens already running (PID=$existing_pid). Waiting..." >> "$LOGFILE"
        sleep 30
        continue
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] Starting MindLens (attempt $((restarts+1)))" >> "$LOGFILE"
    .venv/bin/mindlens >> "$LOGFILE" 2>&1
    exit_code=$?
    echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] MindLens exited (code=$exit_code). Restarting in ${RESTART_DELAY}s..." >> "$LOGFILE"
    rm -f "$LOCKFILE"
    restarts=$((restarts + 1))
    sleep $RESTART_DELAY
done

echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] Max restarts ($MAX_RESTARTS) reached. Giving up." >> "$LOGFILE"
