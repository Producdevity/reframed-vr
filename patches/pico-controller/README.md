# Native controller-consumer integration

The first patch targets Reframed's Bionic consumer harness, not the proprietary PICO
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

`0002-paired-recorder-arm-boundary.patch` targets the optional paired diagnostic's
`paired-capture.c`, shared by the camera producer and Bionic consumer. Its header
pins both source hashes. Apply with the same zero-fuzz command in a fresh copy
of the diagnostic source directory, then rebuild both binaries and refresh all
source, binary and runtime pins. It does not patch the tracking SDK.

A camera callback may have cached its observation time before the recorder
arms. The patch omits that callback only while still ARMED. An atomic state
check prevents a concurrent recording start from silently dropping an input;
the same callback after start fails the diagnostic. Existing failed recordings
remain rejected. See the protocol's recorder-boundary evidence and retained
sanitized regression fixtures before using this diagnostic.
