# SPDX-License-Identifier: MIT
"""Report infrastructure release adoption; unreadable tags are unavailable (AR-3)."""

import os

from house.api import Result

from .metadata import NOT_A_LIBRARY, InputError, is_library, load
from .releases import ChannelError, releases
from .render import infra_revision


def verdict(pin, found):
    tag, commit = found[max(found)]
    if pin == commit:
        return Result.ok(f"infra pin is the current release {tag}")
    pinned = next((name for name, sha in found.values() if sha == pin), None)
    described = pinned or f"unreleased commit {pin[:12]}"
    message = (
        f"infra pin {described} is behind the current release {tag}; adopt it"
    )
    if os.environ.get("GITHUB_ACTIONS") == "true":
        message = f"::warning title=family-freshness::{message}\n{message}"
    return Result.ok(message)


class Freshness:
    name = "family-freshness"
    group = "online"
    rules = ("AR-3",)

    def applies(self, repo):
        return True if is_library(repo.root) else NOT_A_LIBRARY

    def run(self, repo, argv):
        if argv:
            return Result.cannot_run("family-freshness accepts no arguments")
        try:
            data = load(repo.root)
            pin = infra_revision(repo.root)
            found = releases(data["infra"]["repository"])
        except (InputError, ChannelError) as error:
            return Result.cannot_run(str(error))
        if not found:
            return Result.cannot_run(
                f"no vX.Y.Z release tags at {data['infra']['repository']}",
            )
        return verdict(pin, found)


GATE = Freshness()
