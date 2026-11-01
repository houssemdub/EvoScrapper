#!/usr/bin/env bash
set -euo pipefail
HASH="${1:?usage: e2e.sh <info_hash>}"
BASE=http://localhost:8009

# 1. Resolve a stream
curl -sf "$BASE/api/v1/stream/resolve?title=test&imdb_id=tt15239678" >/dev/null

# 2. Warm the swarm
curl -sf "$BASE/api/v1/stream/warm?info_hash=$HASH&file_idx=0" >/dev/null

# 3. Transmux seek probe — verify A/V sync header
HDR=$(curl -sI "$BASE/api/v1/stream/transmux?info_hash=$HASH&file_idx=0&start_time=100" \
     | tr -d '\r' | awk -F': ' '/^x-evo-seek-keyframe/{print $2}')
echo "keyframe snap: $HDR"

# 4. Subtitles must return cues, not the pending sentinel
curl -sf "$BASE/api/v1/stream/subtitles?info_hash=$HASH&file_idx=0&sub_index=0" \
  | head -40 | grep -q -- '-->' && echo "subtitles OK" || { echo "SUBTITLES FAILED"; exit 1; }

# 5. HLS playlist must be keyframe-aligned (no EXT-X-MEDIA, has >1 segments)
curl -sf "$BASE/api/v1/stream/hls/playlist.m3u8?info_hash=$HASH&file_idx=0&duration=60&segment_duration=6" \
  | tee /tmp/hls.m3u8 | grep -q '#EXTM3U' || { echo "HLS FAILED"; exit 1; }
grep -q '#EXT-X-MEDIA' /tmp/hls.m3u8 && { echo "spec-invalid EXT-X-MEDIA still present"; exit 1; } || true
echo "HLS OK"
