# SPDX-License-Identifier: MIT
"""Read the infrastructure release channel: annotated vX.Y.Z tags (AR-3).

A release is an annotated tag, so ls-remote lists its peeled commit on a
`^{}` line. A lightweight tag has no such line and is not a release.
"""

import os
import subprocess

from .metadata import RELEASE


class ChannelError(Exception):
    """The release channel cannot be read."""


def releases(repository):
    """Map each release version tuple to (tag, commit) for annotated tags."""
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        done = subprocess.run(
            ["git", "ls-remote", "--tags", "--", repository],
            capture_output=True, text=True, env=environment, check=False,
        )
    except OSError as error:
        raise ChannelError(f"cannot run git: {error}") from error
    if done.returncode:
        raise ChannelError(
            f"cannot read release tags from {repository}: {done.stderr.strip()}",
        )
    peeled = {}
    for line in done.stdout.splitlines():
        commit, _, ref = line.partition("\t")
        if ref.endswith("^{}"):
            peeled[ref.removeprefix("refs/tags/").removesuffix("^{}")] = commit
    found = {}
    for name, commit in peeled.items():
        match = RELEASE.fullmatch(name)
        if match:
            found[tuple(int(part) for part in match.groups())] = (name, commit)
    return found
