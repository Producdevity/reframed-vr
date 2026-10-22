# gamescope shared-memory uploads

This opt-in patch targets Valve's gamescope 3.16.29, commit
`8f212644c46460549035971ab914421180f61a7c`. The pinned source package,
Fedora patches, input/output source hashes, build options and measured ARM64
binary hashes are in [`profiles/gamescope.json`](../../profiles/gamescope.json).
The accompanying `LICENSE` preserves upstream's copyright and license notices.
Valve's gamescope is the original work; the upload change is local to Reframed.

`import_commit()` memoizes a Vulkan texture by `wlr_buffer`. DMA-BUF imports
refer to shared storage, but the shared-memory path uploads a pixel snapshot.
Xwayland reuses its `wl_shm` buffers with new contents. Reusing the memoized
snapshot therefore presents stale pixels. The patch memoizes only DMA-BUF
imports and creates a fresh upload for each shared-memory commit. It does not
overwrite a texture still referenced by another commit.

The hardware comparison uses the Fedora 44 source RPM from the profile, its
three listed distribution patches and its supplied reshade/vkroots sources.
Prepare that source with the RPM spec's `%prep` stage on ARM64 Fedora with its
build dependencies. Verify `src/steamcompmgr.cpp` against `before_sha256`, then
apply the local patch from that source directory:

```sh
patch --dry-run -p1 < /path/to/reframed-vr/patches/gamescope/0001-refresh-shared-memory-uploads.patch
patch -p1 < /path/to/reframed-vr/patches/gamescope/0001-refresh-shared-memory-uploads.patch
```

Verify the result against `after_sha256`. Configure a new Meson build directory
with the profile's `meson_options`, then run `ninja -C BUILD -j4 src/gamescope`.
The diagnostic build used the distribution's system wlroots, stb and glm.
Dependency/toolchain changes may change binary hashes; retain a build manifest.
This recipe does not install or enable the binary. Keep the control binary and
run the candidate from a private session path for comparison.

The unmodified rebuild retained Steam's initial loading logo while the client
had reached login. The patched rebuild rendered the login form into the Pico's
stereo scanout. See the [hardware record](../../docs/pico-steamvr-verification.md)
for evidence and remaining tracking, interaction and timing limits. This is a
software browser-upload compatibility path, not evidence that wl_shm is the
desired final high-performance rendering path.
