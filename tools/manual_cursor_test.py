#!/usr/bin/env python3
"""
Manual desktop check on REAL devices (never part of verify/check).
See docs/runbooks/manual-desktop-check.md.

DRY-RUN BY DEFAULT: prints the plan and touches nothing.
  --confirm  move the real cursor: after --lead seconds, draw two ellipses with
             the production absolute pointer (UInputBackend) around the centre
             of the monitor that has the cursor. The owner must watch.
  --keys     with --confirm: self-check without the owner -- toggle Caps Lock
             twice through a virtual keyboard and read the real keyboards' LEDs.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def cursor_circles(lead: float) -> None:
    import activity_imitator as core
    backend = core.UInputBackend()
    try:
        print(f"Watch the cursor: it starts in {lead:.0f} s ...", flush=True)
        time.sleep(lead)
        for i in range(240):
            a = 2 * math.pi * i / 120
            backend.move_to(0.5 + 0.15 * math.cos(a), 0.5 + 0.25 * math.sin(a))
            time.sleep(0.015)
        print("Done. Ask the owner what they saw only now (not before the test ended).")
    finally:
        backend.close()


def capslock_leds() -> int:
    import evdev
    from evdev import UInput, ecodes
    keyboards = [d for d in map(evdev.InputDevice, evdev.list_devices())
                 if ecodes.EV_LED in d.capabilities() and not d.name.startswith("Activity Imitator")]
    if not keyboards:
        print("No readable keyboards with LEDs (is the user in the 'input' group?)")
        return 1
    ui = UInput({ecodes.EV_KEY: [ecodes.KEY_CAPSLOCK]}, name="Activity Imitator virtual capslock-test")
    try:
        time.sleep(1.5)  # the compositor needs time to adopt a new uinput device

        def tap():
            for value in (1, 0):
                ui.write(ecodes.EV_KEY, ecodes.KEY_CAPSLOCK, value)
                ui.syn()
                time.sleep(0.05)
            time.sleep(0.4)
        before = [d.leds() for d in keyboards]
        tap()
        during = [d.leds() for d in keyboards]
        tap()
        after = [d.leds() for d in keyboards]
    finally:
        ui.close()
    ok = during != before and after == before
    print(f"LEDs before={before} during={during} after={after} -> "
          f"{'compositor accepts virtual keys' if ok else 'NO EFFECT: virtual keys ignored?'}")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--confirm", action="store_true", help="really move the cursor")
    ap.add_argument("--keys", action="store_true", help="Caps Lock LED self-check")
    ap.add_argument("--lead", type=float, default=8.0, help="seconds before the cursor moves")
    args = ap.parse_args(argv)
    if args.keys and args.confirm:
        return capslock_leds()
    if args.keys:
        print("DRY-RUN: would toggle Caps Lock twice via a virtual keyboard and compare the real "
              "keyboards' LEDs. Re-run with --confirm (make manual-keys-test CONFIRM=1).")
        return 0
    if not args.confirm:
        print(f"DRY-RUN: would wait {args.lead:.0f} s, then draw two ellipses with the real cursor "
              "on the active monitor. Re-run with --confirm (make manual-cursor-test CONFIRM=1) "
              "while the owner watches the screen.")
        return 0
    cursor_circles(args.lead)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
