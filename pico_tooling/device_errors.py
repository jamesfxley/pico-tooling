# SPDX-License-Identifier: MIT
"""Exit statuses of the device command group and the refusal that carries one."""

OK = 0
FAILED = 1  # tried and did not succeed
CANNOT_TRY = 2  # nothing was attempted
AMBIGUOUS = 3  # several candidates and none named
INTERRUPTED = 130
TERMINATED = 143


class RefusalError(Exception):
    """A device command stops with a status and the message that explains it."""

    def __init__(self, status, message, *, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


class GoneError(RefusalError):
    """A port went away between being listed and being opened; try again."""

    def __init__(self, message):
        super().__init__(CANNOT_TRY, message, code="absent")
