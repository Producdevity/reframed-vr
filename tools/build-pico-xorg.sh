#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
engine="${CONTAINER_ENGINE:-docker}"
out="${1:?Usage: build-pico-xorg.sh NEW_OUTPUT_DIRECTORY [SOURCE_ARCHIVE]}"
archive="${2:-output/downloads/xorg-server-21.1.24.tar.xz}"
expected=1a4eb36ca65cc3b1b936566d677a9786e13c11cd5806e951ac55f3f5ce3984af
[[ ! -e "$out" ]] || { echo "Choose a new output directory" >&2; exit 1; }
if [[ ! -e "$archive" ]]; then
    mkdir -p "$(dirname "$archive")"
    curl --fail --location --max-time 120 \
        https://www.x.org/releases/individual/xserver/xorg-server-21.1.24.tar.xz \
        --output "$archive"
fi
python3 - "$archive" "$expected" <<'PY'
import hashlib,sys
from pathlib import Path
p=Path(sys.argv[1])
assert p.is_file() and not p.is_symlink()
assert hashlib.sha256(p.read_bytes()).hexdigest() == sys.argv[2], 'Source archive hash differs'
PY
image=$("$engine" image inspect --format '{{.Id}}' localhost/reframed-vr:pico-xorg-tools)
[[ $("$engine" image inspect --format '{{.Architecture}}' "$image") == arm64 ]]
archive=$(cd "$(dirname "$archive")" && pwd)/$(basename "$archive")
mkdir -p "$out"
out=$(cd "$out" && pwd)
"$engine" run --rm --platform linux/arm64 --network none \
    --memory 2g --memory-swap 2g --cpus 2 --pids-limit 128 \
    -v "$archive:/archive.tar.xz:ro" -v "$PWD/patches/xorg:/patches:ro" \
    -v "$out:/output" --entrypoint bash "$image" -c '
set -euo pipefail
mkdir /tmp/source
tar -xf /archive.tar.xz -C /tmp/source --strip-components=1
cd /tmp/source
for patch in /patches/*.patch; do
    patch --batch --fuzz=0 --forward -p1 -i "$patch"
done
meson setup /tmp/build /tmp/source --buildtype=release --wrap-mode=nodownload \
    -Dxorg=true -Dxnest=false -Dxvfb=false -Dxwin=false -Dxquartz=false \
    -Dglamor=false -Dglx=false -Ddri3=false -Ddri2=false -Ddri1=false \
    -Dxselinux=false -Ddocs=false -Ddevel-docs=false
ninja -C /tmp/build -j2 hw/xfree86/drivers/modesetting/modesetting_drv.so
install -m 0755 /tmp/build/hw/xfree86/drivers/modesetting/modesetting_drv.so /output/modesetting_drv.so
rpm -qa | sort > /output/packages.txt
readelf -h /output/modesetting_drv.so
' > "$out/build.log" 2>&1
python3 - "$out" "$image" "$expected" <<'PY'
import hashlib,json,struct,sys
from pathlib import Path
out=Path(sys.argv[1]); module=(out/'modesetting_drv.so').read_bytes()
assert module[:5] == b'\x7fELF\x02' and struct.unpack_from('<H',module,18)[0] == 183
files={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
       for p in (out/'modesetting_drv.so',out/'packages.txt',out/'build.log')}
sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(Path('patches/xorg').glob('*.patch'))}
report={'status':'compiled','source_version':'21.1.24','source_archive_sha256':sys.argv[3],
        'build_image':sys.argv[2],'patches':sources,'artifacts':files,
        'desktop_acceleration':'CPU shadow framebuffer','physical_boot_verified':False,
        'flash_ready':False}
(out/'build.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
PY
