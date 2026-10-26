#!/usr/bin/env bash
set -euo pipefail
client="$HOME/.local/share/Steam"
mkdir -p "$HOME/.steam" "$HOME/.local/state/reframed-vr"
ln -sfn "$client" "$HOME/.steam/root"
ln -sfn "$client" "$HOME/.steam/steam"
ln -sfn "$client/linux32" "$HOME/.steam/sdk32"
ln -sfn "$client/linux64" "$HOME/.steam/sdk64"
ln -sfn "$client/linuxarm64" "$HOME/.steam/sdkarm64"
ln -sfn "$client/ubuntu12_32" "$HOME/.steam/bin"
ln -sfn "$client/ubuntu12_32" "$HOME/.steam/bin32"
ln -sfn "$client/ubuntu12_64" "$HOME/.steam/bin64"
cd "$client"
export LD_LIBRARY_PATH="$client/steamrtarm64:$client/steamrtarm64/libs"
export PATH="$client/steam-runtime-steamrt-arm64/bin:$PATH"
# The public x86-64 package cannot serve an ARM64 client; a native override can.
runtime="${VR_OVERRIDE:-$client/steamapps/common/SteamVR}"
if [[ -f "$runtime/bin/linux64/vrclient.so" &&
      ! -f "$runtime/bin/linuxarm64/vrclient.so" ]]; then
    set -- -vrdisable "$@"
fi
exec ./steamrtarm64/steam -nobootstrapupdate -skipinitialbootstrap -publicbeta \
    "$@" \
    >> "$HOME/.local/state/reframed-vr/steam.log" 2>&1
