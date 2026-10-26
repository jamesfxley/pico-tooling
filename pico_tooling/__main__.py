# SPDX-License-Identifier: MIT
"""Family command line: sync, report, scaffold and device.

Exit codes follow House: 0 pass, 1 findings, 2 cannot run.
"""

import argparse
import sys
from pathlib import Path

try:
    from . import device
except ModuleNotFoundError as error:
    if error.name != "fcntl":
        raise
    device = None

from .metadata import InputError
from .report import report
from .scaffold import scaffold
from .sync import findings, indexed, sync


def parser():
    top = argparse.ArgumentParser(prog="pico_tooling", description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)
    synced = commands.add_parser("sync", help="write the family bootstrap")
    synced.add_argument("--check", action="store_true", help="compare only")
    reported = commands.add_parser("report", help="read-only family pin report")
    reported.add_argument("sources", nargs="+", metavar="name=repository[@ref]")
    created = commands.add_parser("scaffold", help="create a library checkout")
    created.add_argument("destination", type=Path)
    created.add_argument("--name", required=True)
    created.add_argument("--infra-repository", required=True)
    created.add_argument("--lang", action="append", default=[])
    if device is not None:
        device.add_to(commands)
    else:
        commands.add_parser(
            "device", help="requires dev-container locks", add_help=False,
        ).add_argument("rest", nargs=argparse.REMAINDER)
    return top


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "device" and device is None:
        print(
            "cannot run: device commands need a POSIX host for per-board locks; "
            "run in the dev container after host/setup-device-proxy.ps1 setup",
            file=sys.stderr,
        )
        return 2
    if args.command == "device":
        return device.run(args)
    root = Path.cwd()
    try:
        if args.command == "sync" and args.check:
            found = findings(root, indexed(root))
            for path, message in found:
                print(f"{path}: {message}")
            return 1 if found else 0
        if args.command == "sync":
            sync(root)
        elif args.command == "report":
            lines, problems = report(args.sources)
            print("\n".join(lines))
            return 1 if problems else 0
        else:
            scaffold(args.destination, args.name, args.infra_repository, args.lang)
    except InputError as error:
        print(f"cannot run: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
