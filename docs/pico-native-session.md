# Running an attended native Pico session

This runs the verified native Linux VR stack on the Neo3 Pro Eye long enough to
wear it: head tracking, both controllers (input, analog, haptics and optical
pose publication), Valve's SteamVR compositor with the Steam VR UI, and Wi-Fi.
Linux boots from RAM with its root served over USB from the Mac; nothing is
flashed, and a reboot always returns to the unchanged stock Android boot.

The tooling is the evidence harness used for the 2026-11-01 runs. It lives in
the ignored `output/` directory, so it depends on that directory's retained
kernel, root image, payloads and stock-recovery helpers.

## Before starting

- The Pico is on stock Android, visible to `adb` as `PA7J50PGG7300041W`, with
  stock Wi-Fi off and the USB cable connected to the Mac.
- Nothing else is using the device or a previous harness's `host-session.py`.
- Keep the controllers awake (press the Home button) and hold them within arm's
  reach in front of the headset; the controller SDK only initializes an optical
  pose within about 0.8 m and while the controller moves.

## Build and launch

Build a session payload with a hold of up to 50 minutes (1200 s shown):

```sh
python3 -B output/pico-attended-session-20261101-v1/prepare.py \
  output/pico-vr-cef-gpu-native-20261101-v1/native-software-v4 \
  --hold 1200 --name my-session
```

Options:

- `--predict-velocity` enables the opt-in head-velocity prediction for an A/B
  comparison.
- `--refresh N` (30–120, default 90) sets the nested Steam UI compositor rate.
- `--wifi` brings up Wi-Fi in the session. It is off by default: one Wi-Fi stop
  has hung on a wedged kernel bus-scaling lock (see
  [wireless evidence](pico-native-wireless.md#wi-fi-inside-the-native-vr-session-2026-11-01)).
- `--monitor-quit` is a shutdown experiment; leave it off for normal use.

Each name can be used once. Launch:

```sh
python3 -B output/pico-attended-session-20261101-v1/my-session/auto-run.py \
  | tee output/pico-attended-session-20261101-v1/my-session/auto-run.log
```

The Pico reboots into the bootloader, RAM-boots Linux, runs about two minutes of
setup and starts the VR workload. When the log prints a state with
`"ready": true`, the Steam VR UI is up. The hold starts a few minutes later,
after the harness's own measurement windows, and keeps tracking, controllers,
SteamVR and the UI running for the requested time.

## Stop and recovery

To end the hold early:

```sh
python3 -B output/pico-attended-session-20261101-v1/my-session/stop.py
```

It shares a lock with the harness, so it never interleaves with a console
command in flight.

After the hold the harness stops SteamVR, the controller and camera owners and
Wi-Fi, releases the DSPs and MCU reference, exports the session logs to
`my-session/export/`, reboots, verifies quiet offline stock and ends the USB
helper. The export includes `run/hold-power.json`: battery state, every thermal
zone and the CPU and GPU clocks, sampled every 10 seconds during the hold, plus
the CPU and GPU trip points.

Every reboot of the live image is forced: its console service's stop action
calls `systemctl --force --force reboot`, which skips stopping services and
enters the kernel's restart directly. That path still runs the drivers'
shutdown callbacks, and on 2026-11-01 it never completed after a kernel
bus-scaling lock wedged. A SysRq `b` emergency restart skips those callbacks.

The session therefore has three ways back to stock:

- The harness's normal finish reboots after export. Just before that, it arms a
  three-minute SysRq guard in case the reboot itself hangs.
- If stopping NetworkManager times out, the harness records a blocked-task dump,
  skips the DSP quiesce, exports what it can and restarts through SysRq at once.
- Independently of the Mac, the bootstrap arms an orderly reboot 25 minutes plus
  the hold after boot, and a resident SysRq guard five minutes after that. The
  guard is a process that holds `/proc/sysrq-trigger` open from the start, so
  firing needs no new process or file; it runs outside the shutdown
  transaction, and its `@` name exempts it from systemd's final kill.

On 2026-11-02 a guard armed for 45 s on an otherwise idle live session reset the
headset 43 s after it was armed; stock `adb` returned and the quiet-offline stock
check passed. That verifies the emergency restart and its return to normal stock
boot. The original deadlock has not been reproduced, so the guard firing during
a hung kernel restart is inferred from the restart path, not observed. After any
failure, `my-session/verify-stock-return.py` checks the result.

If the headset still shows up as `Reframed VR Pico diagnostic` on USB with no
console and no `adb` more than five minutes past the guard's deadline, hold the
power button until it switches off, then start it normally; it boots the
unchanged stock image.

## Verified behaviour

A 120-second hold on 2026-11-01 ran to completion with the camera owner and
vendor SLAM consumer alive throughout (6,434 of 6,434 camera sets consumed),
then exported, returned to stock and passed the stock-return check. During a
second 120-second hold, on USB power with a full battery, the hottest CPU
sensor read about 88 °C at the start and 95 °C at the end. SteamVR is stopped
by bounded service termination; an in-runtime graceful quit is not yet
available (see [SteamVR verification](pico-steamvr-verification.md#shutdown-diagnostics-2026-10-30)).
