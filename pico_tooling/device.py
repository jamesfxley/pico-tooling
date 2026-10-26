# SPDX-License-Identifier: MIT
"""Device sequencing and console capture through the Windows host proxy (AR-12).

The host owns the allow-list. Python owns one lock per board, the reset, load,
reconnect and console policy. Commands never build and never choose a board.
"""

import argparse
import codecs
import contextlib
import fcntl
import json
import math
import os
import re
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from .device_errors import (
    AMBIGUOUS,
    CANNOT_TRY,
    FAILED,
    INTERRUPTED,
    OK,
    TERMINATED,
    GoneError,
    RefusalError,
)
from .device_images import check_credentials, resolve_uf2
from .device_proxy import Proxy, find_connection

TOUCH_BAUD = 1200  # PICO_USB_RESET_MAGIC_BAUD_RATE
CONSOLE_BAUD = 115200
BOOT_WAIT = 30  # seconds the bootloader has to appear after the reset
REBOOT_WAIT = 30  # seconds the board has to leave the bootloader after the load
HOLD = 0.2  # seconds the port stays open at the reset baud rate
TAIL = 65536  # characters of console output a pattern is matched against
SETUP = (
    "run host/setup-device-proxy.ps1 -Workspace <host-workspace-folder> once "
    "in Windows PowerShell, then run the installed start-device-proxy.ps1 "
    "before opening the container; see guides/device.md, One-time setup"
)


def standard_input():
    try:
        return sys.stdin.fileno()
    except (AttributeError, ValueError, OSError):
        return None


@dataclass
class Host:
    """Replaceable process inputs; no direct device access."""

    cwd: Path = field(default_factory=Path.cwd)
    environ: Mapping = field(default_factory=lambda: dict(os.environ))
    sleep: Callable = time.sleep
    clock: Callable = time.monotonic
    out: object = field(default_factory=lambda: sys.stdout)
    err: object = field(default_factory=lambda: sys.stderr)
    data: Callable = field(default_factory=lambda: write_output)
    stdin: int | None = field(default_factory=standard_input)

    def say(self, text):
        print(text, file=self.out, flush=True)

    def warn(self, text):
        print(text, file=self.err, flush=True)


def write_output(chunk):
    sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()


@contextlib.contextmanager
def locked(serial, environ):
    """Hold the existing per-user advisory lock for the whole board operation."""
    base = Path(environ.get("XDG_RUNTIME_DIR", ""))
    if not base.is_absolute():
        base = Path(tempfile.gettempdir()) / f"pico-{os.getuid()}"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if base.stat().st_uid != os.getuid():
        raise RefusalError(CANNOT_TRY, f"{base} is not owned by this user")
    path = base / f"device-{quote(serial, safe='')}.lock"
    with path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            lock.seek(0)
            holder = lock.read(32).decode(errors="replace").strip()
            raise RefusalError(
                FAILED,
                f"{serial} is in use by process {holder or 'unknown'}",
            ) from error
        lock.seek(0)
        lock.truncate()
        lock.write(f"{os.getpid()}\n".encode())
        lock.flush()
        yield


class TerminationError(Exception):
    """The process was asked to terminate."""


# -- choosing the backend ------------------------------------------------------


def choose(host):
    """Use the host proxy at use time, or explain the one-time setup."""
    found = find_connection(host.cwd)
    if found is None:
        raise RefusalError(CANNOT_TRY, f"no device proxy connection file: {SETUP}")
    proxy = Proxy(host, *found)
    proxy.list()
    return proxy


# -- finding the board ---------------------------------------------------------


def board_of(backend, serial):
    return next((board for board in backend.list() if board.serial == serial), None)


def attached(backend, serial):
    """Return the named board, or refuse if it is not attached."""
    board = board_of(backend, serial)
    if board is None:
        raise RefusalError(CANNOT_TRY, f"{serial} is listed but not attached")
    return board


def pick_port(serial, ports, wanted):
    """Return the one port to open; several are listed, never guessed."""
    if not ports:
        return None
    if wanted is not None:
        if wanted not in ports:
            raise RefusalError(
                CANNOT_TRY,
                f"{wanted} is not a port of {serial}; its ports: {ports}",
            )
        return wanted
    if len(ports) > 1:
        listing = "".join(f"\n  {port}" for port in ports)
        raise RefusalError(
            AMBIGUOUS,
            f"several ports could be {serial}; name one:{listing}",
        )
    return ports[0] if ports else None


def wait_for(host, seconds, probe):
    """Poll `probe` once a second; return its first truthy answer or None."""
    end = host.clock() + seconds
    while host.clock() < end:
        answer = probe()
        if answer:
            return answer
        host.sleep(min(1, max(0, end - host.clock())))
    return None


# -- list ----------------------------------------------------------------------


def command_list(host, args):
    """Print the boards; this reads and authorizes nothing."""
    rows = choose(host).list()
    if args.json:
        host.say(json.dumps([vars(row) for row in rows], indent=2))
    mark = {True: "listed", False: "not listed", None: "list unreadable"}
    for row in () if args.json else rows:
        place = " ".join(row.ports)
        if row.bootloader:
            place = f"bootloader {row.drive or ''}".strip()
        host.say(
            f"{row.serial or '(no serial)'}\t{row.product}\t{place}\t"
            f"{mark[row.listed]}",
        )
    if not rows and not args.json:
        host.say("no Raspberry Pi board found")
    return OK


# -- bootsel and flash ---------------------------------------------------------


def reset_into_bootsel(host, backend, serial, wanted):
    """Open the port at the reset baud rate and wait for the bootloader.

    The SDK resets a board that sees this baud rate on its USB serial port, only
    in firmware using its USB stdio without driving TinyUSB directly
    (pico_usb_reset/include/pico/usb_reset_config.h:10-17, usb_reset.c:145-148).
    """
    port = pick_port(serial, attached(backend, serial).ports, wanted)
    if port is None:
        raise RefusalError(
            CANNOT_TRY,
            f"{serial} shows no serial port, so it cannot be reset. Hold BOOTSEL while"
            "\n       plugging it in, then use --no-touch.",
        )
    host.say("==> Rebooting the running firmware into BOOTSEL...")
    vanished = None
    try:
        with backend.open_serial(serial, TOUCH_BAUD, port):
            host.sleep(HOLD)
    except RefusalError as error:
        if error.code not in {"failed", "absent", "closed"}:
            raise
        vanished = error
    if not wait_for(host, BOOT_WAIT, lambda: in_bootloader(backend, serial)):
        raise RefusalError(
            CANNOT_TRY if vanished else FAILED,
            (f"{vanished}\n" if vanished else "")
            + f"{serial} did not appear in BOOTSEL within {BOOT_WAIT}s. Its firmware"
            "\n       may not serve the reset; hold BOOTSEL while plugging it in,"
            " then use --no-touch.",
        )
    if vanished:
        host.say("==> The port vanished during the reset as expected.")


def in_bootloader(backend, serial):
    board = board_of(backend, serial)
    return board is not None and board.bootloader


def command_bootsel(host, args):
    backend = choose(host)
    backend.allowed(args.serial)
    with locked(args.serial, host.environ):
        if not in_bootloader(backend, args.serial):
            reset_into_bootsel(host, backend, args.serial, args.port)
    host.say("==> The board is in BOOTSEL.")
    return OK


def repository_root(host):
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=host.cwd,
            capture_output=True,
            text=True,
            check=False,
            env=dict(host.environ),
        )
    except OSError:
        return None
    return Path(done.stdout.strip()) if done.returncode == 0 else None


def find_image(host, args):
    """Return the .uf2 to flash and its warning; never builds."""
    want = args.image
    if want and (host.cwd / want).is_file():
        want = str((host.cwd / want).resolve())
    root = repository_root(host)
    if root is None and not (want and Path(want).is_file()):
        raise RefusalError(
            CANNOT_TRY,
            "give a .uf2 path, or run it inside the repository whose image it flashes",
        )
    base = root or host.cwd
    if args.build_dir:
        tree = base / args.build_dir
    else:
        firmware = base / "build-firmware"
        tree = firmware if firmware.is_dir() else base / "build"
    uf2 = resolve_uf2(tree, want)
    if uf2 is None:
        raise RefusalError(
            CANNOT_TRY,
            f"no .uf2 for '{want or 'the default image'}' under {tree}/;"
            " build it first with python3 dev.py build",
        )
    return uf2, check_credentials(uf2)


def flash(host, backend, args, uf2):
    """Reset into the bootloader unless already there, load, and wait for the reboot."""
    serial = args.serial
    if not in_bootloader(backend, serial):
        if args.no_touch:
            raise RefusalError(
                CANNOT_TRY,
                f"{serial} is not in BOOTSEL, and --no-touch needs it there",
            )
        reset_into_bootsel(host, backend, serial, args.port)
    host.say(f"==> Loading {uf2} through the host proxy...")
    backend.load(serial, uf2)
    if not wait_for(host, REBOOT_WAIT, lambda: board_ports(backend, serial)):
        raise RefusalError(
            FAILED,
            f"{serial} did not reconnect within {REBOOT_WAIT}s after the load",
        )
    host.say("==> Flashed. The board has reconnected.")


def command_flash(host, args):
    backend = choose(host)
    backend.allowed(args.serial)
    check_watch(args)
    uf2, warning = find_image(host, args)
    backend.image_path(uf2)
    if warning:
        host.warn(f"==> warning: {warning}")
    if args.dry_run:
        host.say(
            f"would reset {args.serial} into BOOTSEL unless it is there, then load "
            f"{uf2} through the host proxy",
        )
        return OK
    with locked(args.serial, host.environ), terminating():
        flash(host, backend, args, uf2)
        if args.console:
            return console(host, backend, args, forward_of(host, args), started=True)
        host.say("==> Run `device console --serial ...` to watch its console.")
    return OK


# -- console -------------------------------------------------------------------


@contextlib.contextmanager
def terminating():
    """Turn SIGTERM into TerminationError for the duration of a console."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def handler(_signal, _frame):
        raise TerminationError

    previous = signal.signal(signal.SIGTERM, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def check_watch(args):
    """Refuse agent-mode options that cannot run; return the pattern or None."""
    if args.timeout is not None and (
        not math.isfinite(args.timeout) or args.timeout <= 0
    ):
        raise RefusalError(CANNOT_TRY, "--timeout must be finite and positive")
    if (args.until is None) != (args.timeout is None):
        raise RefusalError(CANNOT_TRY, "--until and --timeout go together")
    try:
        return re.compile(args.until) if args.until is not None else None
    except re.error as error:
        raise RefusalError(CANNOT_TRY, f"--until is not a pattern: {error}") from error


class Watch:
    """The agent mode's state: a pattern, a deadline and a log of the output."""

    def __init__(self, host, args, log):
        self.pattern = check_watch(args)
        self.deadline = None if args.timeout is None else host.clock() + args.timeout
        self.log = log
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.text = ""

    def left(self, host):
        return None if self.deadline is None else max(0.0, self.deadline - host.clock())

    def feed(self, chunk):
        """Return True once the pattern matches the output so far."""
        if self.log:
            self.log.write(chunk)
            self.log.flush()
        self.text = (self.text + self.decoder.decode(chunk))[-TAIL:]
        return self.pattern is not None and self.pattern.search(self.text) is not None


def copy_until_lost(host, stream, watch, forward):
    """Copy the port to the output and `forward` to the port; say why it ended.

    Returns "lost" when the port goes away, "match" or "timeout".
    """
    while True:
        left = watch.left(host)
        if left == 0.0:
            return "timeout"
        ready, _, _ = select.select(
            [stream] + ([forward] if forward is not None else []),
            [],
            [],
            0.2 if left is None else min(0.2, left),
        )
        for source in ready:
            if source is not stream:
                typed = os.read(source, 4096)
                if typed:
                    stream.sendall(typed)
                else:
                    forward = None
                continue
            try:
                chunk = stream.recv(4096)
            except (ConnectionResetError, ConnectionAbortedError):
                return "lost"
            if chunk == b"":
                return "lost"
            if chunk:
                host.data(chunk)
                if watch.feed(chunk):
                    return "match"


def board_ports(backend, serial):
    board = board_of(backend, serial)
    return board.ports if board else ()


def timed_out(host, args):
    host.warn(f"error: no match for {args.until!r} within {args.timeout}s")
    return FAILED


def console(host, backend, args, forward=None, started=False):
    """Hold a console on the named board across reboots; return a status."""
    with contextlib.ExitStack() as stack:
        log = stack.enter_context(Path(args.log).open("ab")) if args.log else None
        watch = Watch(host, args, log)
        backend.deadline = watch.deadline
        if not started:
            attached(backend, args.serial)
        while True:
            left = watch.left(host)
            if left == 0.0:
                return timed_out(host, args)
            port = wait_for(
                host,
                10**9 if left is None else left,
                lambda: pick_port(
                    args.serial,
                    board_ports(backend, args.serial),
                    args.port,
                ),
            )
            if port is None:
                return timed_out(host, args)
            host.warn(f"==> Connected on {port}")
            try:
                stream = backend.open_serial(args.serial, CONSOLE_BAUD, port)
            except GoneError:
                host.sleep(1)
                continue
            try:
                why = copy_until_lost(host, stream, watch, forward)
            finally:
                stream.close()
            if why == "match":
                host.warn("==> Matched.")
                return OK
            if why == "timeout":
                return timed_out(host, args)
            host.warn(f"==> Lost connection to {port}; waiting for it to come back...")
            remaining = watch.left(host)
            host.sleep(1 if remaining is None else min(1, remaining))


def forward_of(host, args):
    """Return what to send to the board: standard input, but not in agent mode."""
    return None if args.until is not None else host.stdin


def command_console(host, args):
    backend = choose(host)
    backend.allowed(args.serial)
    check_watch(args)
    with locked(args.serial, host.environ), terminating():
        host.warn("==> Holding a serial console session open (Ctrl+C to quit).")
        return console(host, backend, args, forward_of(host, args))


# -- the command line ----------------------------------------------------------


def add_to(commands):
    """Add the `device` group to a parent parser's subcommands."""
    group = commands.add_parser(
        "device",
        help="list, reboot, flash and watch a board",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    actions = group.add_subparsers(dest="action", required=True)
    common = argparse.ArgumentParser(add_help=False)
    selected = argparse.ArgumentParser(add_help=False, parents=[common])
    selected.add_argument("--serial", required=True, help="USB serial number")
    selected.add_argument("--port", metavar="P", help="one of the board's ports")
    watching = argparse.ArgumentParser(add_help=False)
    watching.add_argument(
        "--until",
        metavar="REGEX",
        help="exit 0 when the output matches",
    )
    watching.add_argument(
        "--timeout",
        metavar="S",
        type=float,
        help="exit 1 after S seconds",
    )
    watching.add_argument("--log", metavar="FILE", help="append the board's output")
    listed = actions.add_parser("list", parents=[common], help="print the boards")
    listed.add_argument("--json", action="store_true")
    actions.add_parser("bootsel", parents=[selected], help="reboot into BOOTSEL")
    flashed = actions.add_parser(
        "flash",
        parents=[selected, watching],
        help="load an image",
    )
    flashed.add_argument("--build-dir", metavar="D")
    flashed.add_argument("--no-touch", action="store_true", help="already in BOOTSEL")
    flashed.add_argument(
        "--console",
        action="store_true",
        help="then watch the console",
    )
    flashed.add_argument("--dry-run", action="store_true")
    flashed.add_argument("image", nargs="?", help="image name or path.uf2")
    actions.add_parser(
        "console",
        parents=[selected, watching],
        help="watch the console",
    )


COMMANDS = {
    "list": command_list,
    "bootsel": command_bootsel,
    "flash": command_flash,
    "console": command_console,
}


def run(args, host=None):
    """Run the parsed command and return its exit status."""
    host = host or Host()
    try:
        return COMMANDS[args.action](host, args)
    except RefusalError as refusal:
        host.warn(f"error: {refusal}")
        return refusal.status
    except BrokenPipeError:
        host.warn("error: standard output was closed")
        return FAILED
    except OSError as error:
        host.warn(f"error: cannot run device command: {error}")
        return CANNOT_TRY
    except KeyboardInterrupt:
        return INTERRUPTED
    except TerminationError:
        return TERMINATED
