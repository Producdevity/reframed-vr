#!/usr/bin/env bash
set -euo pipefail

export VR_OVERRIDE="${VR_OVERRIDE:-/opt/reframed-vr/steamvr}"
if [[ ! -f "$VR_OVERRIDE/bin/linuxarm64/vrclient.so" ]]; then
    echo 'An ARM64 SteamVR runtime is required for the VR Gamepad UI.' >&2
    exit 1
fi

launcher_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${REFRAMED_GAMESCOPE_BIN:-gamescope}" \
    --backend openvr --force-composition --steam \
    --vr-session-manager --virtual-connector-strategy PerAppId \
    --xwayland-count 2 \
    -W 1600 -H 1000 -w 1600 -h 1000 -r 90 \
    --vr-overlay-key valve.steam.gamepadui.fallback \
    --vr-app-overlay-key valve.steam.desktopgame \
    --vr-overlay-show-immediately --vr-overlay-physical-width 1.8 \
    -- "$launcher_dir/desktop-steam.sh" -gamepadui -vrgamepadui "$@"
