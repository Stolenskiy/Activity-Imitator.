"""
Test-suite boundary (ADR 0008). Runs before any test module imports product code:

  * HOME points to a temporary directory, so settings never touch the real home;
  * Qt runs offscreen;
  * real input devices (/dev/uinput, /dev/input) and network sockets raise
    HardwareAccessError -- a BaseException, so product code's `except Exception`
    cannot swallow it. Use tests/fakes.py instead.
"""

import atexit
import os
import shutil
import socket
import tempfile

_HOME = tempfile.mkdtemp(prefix="ai-test-home-")
os.environ["HOME"] = _HOME
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("XDG_CONFIG_HOME", None)
atexit.register(shutil.rmtree, _HOME, True)


class HardwareAccessError(BaseException):
    """A test tried to use real devices or the network."""


def _forbidden(what):
    def _raise(*_args, **_kwargs):
        raise HardwareAccessError(f"tests must not use {what}; use tests/fakes.py")
    return _raise


import evdev  # noqa: E402  (patched before product modules import it)
import evdev.device  # noqa: E402
import evdev.uinput  # noqa: E402

evdev.UInput = evdev.uinput.UInput = _forbidden("/dev/uinput (evdev.UInput)")
evdev.InputDevice = evdev.device.InputDevice = _forbidden("/dev/input (evdev.InputDevice)")
evdev.list_devices = _forbidden("/dev/input (evdev.list_devices)")


class _NoNetworkSocket(socket.socket):
    def __init__(self, family=socket.AF_INET, *args, **kwargs):
        if family in (socket.AF_INET, socket.AF_INET6):
            raise HardwareAccessError("tests must not open network sockets")
        super().__init__(family, *args, **kwargs)


socket.socket = _NoNetworkSocket
