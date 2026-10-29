# Native controller-consumer integration

This patch targets Reframed's Bionic consumer harness, not the proprietary PICO
tracking library. The baseline is `consumer-controller-owned.c` in the validated
117-file Android consumer source closure. The patch header pins its input and
result hashes. Firmware, SDK libraries, calibration and recordings stay outside
Git.

Extract that verified source closure into a new build directory, verify the
input hash, then apply the patch in the harness file's directory:

```sh
patch --batch --fuzz=0 -p1 -i /absolute/path/to/0001-fresh-hand-subset-epoch.patch
```

Verify the result hash and rebuild with the recorded NDK27 command, including
the matching maintained controller channel/consumer sources. Preserve the full
source closure, compiler identity and output ELF hash. A rebuilt consumer must
also replace its exact binary pins in the runtime and tracking-selection helper;
changing those pins must retain the mapping/identity checks.

The worker and session select this protocol explicitly with
`motion_subset=True`. Default legacy sessions remain available. See
[protocol and recovery contracts](../../docs/pico-controller-protocol.md).
