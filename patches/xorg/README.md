# Pico modesetting compatibility

These patches apply to the X.Org server 21.1.24 release from
<https://www.x.org/releases/individual/xserver/xorg-server-21.1.24.tar.xz>.
The retained archive SHA-256 is
`1a4eb36ca65cc3b1b936566d677a9786e13c11cd5806e951ac55f3f5ce3984af`.
The source-matched test fixtures retain the upstream MIT license.

The vendor Neo3 kernel exposes bitmask properties such as `topology_control`.
Xorg allocates a property entry but no RandR atom table for these types. Its
setter iterates those entries during initialization of a later property and
dereferences the absent table. Patch 0001 skips entries without atoms, including
allocation failures, while preserving supported range, enum and CTM writes.

Xorg also reconstructs a KMS mode without its kernel-supplied `vrefresh` field.
The Pico DSI driver requires that field; its compressed-panel mode's pixel
clock does not describe the physical refresh through the usual formula.
Patch 0002 recovers the advertised refresh from a connector mode with identical
timings and flags. Changed modes keep the ordinary zero value; no refresh is
guessed from the mode name or hardcoded for the panel.

`tools/build-pico-xorg.sh` builds the patched ARM64 modesetting module against
the source release. Build its tools image with `Containerfile.pico-xorg` first.
The initial profile disables glamor/DRI in this module; it supports the CPU
shadow-framebuffer desktop used for first physical UI verification. It does not
establish hardware-accelerated desktop rendering or VR synchronization.

The October 18 physical test used the packaged Xorg 21.1.24-1.fc44 server and
ABI 25.2 with this module. Xorg and Openbox stayed active, the kernel accepted
the 120 Hz panel mode, and a captured framebuffer showed the native ARM64 Steam
gamepad welcome UI. This is a portrait desktop, not calibrated stereo output.
Evidence, build logs and the screenshot remain private under
`output/pico-recovery-bringup-20261018-v1/`.
