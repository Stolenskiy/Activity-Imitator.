# 0008 — Tests never touch real devices, network or home

Status: Accepted (2026-11-23)

## Context
The product creates kernel input devices and reads `/dev/input`. A careless test could move
the owner's cursor, press keys or overwrite `~/.config` settings.

## Decision
`tests/__init__.py` runs before every test module: HOME becomes a temp dir, Qt runs offscreen,
and `evdev.UInput`, `evdev.InputDevice`, `evdev.list_devices` and network sockets raise
`HardwareAccessError` (a BaseException, so product `except Exception` cannot hide it).
`tests/fakes.py` provides FakeUInput, FakeInputDevice (pipe-backed), FakeSimulator,
FakeSafety and `fake_hardware()`.

## Consequences
- `make verify`/`make check` are safe to run anywhere, including CI.
- Real-device checks are manual and dry-run by default (`docs/runbooks/manual-desktop-check.md`).
