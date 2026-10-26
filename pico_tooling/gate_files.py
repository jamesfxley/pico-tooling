# SPDX-License-Identifier: MIT
"""Gate: the generated CMake bootstrap match the pinned generator (AR-2)."""

from house.api import Finding, Result

from .metadata import NOT_A_LIBRARY, InputError, is_library
from .sync import findings


class FamilyFiles:
    name = "family-files"
    group = "standards"
    rules = ("AR-2",)

    def applies(self, repo):
        # A library, even one missing its input, is checked.
        return True if is_library(repo.root) else NOT_A_LIBRARY

    def run(self, repo, argv):
        if argv:
            return Result.cannot_run("family-files accepts no arguments")
        try:
            found = findings(repo.root, set(repo.tracked()))
        except InputError as error:
            return Result.cannot_run(f"family inputs unavailable: {error}")
        if found:
            return Result.fail(
                *(Finding(path, 0, "AR-2", message) for path, message in found),
            )
        return Result.ok("family-owned files match the pinned generator")


GATE = FamilyFiles()
