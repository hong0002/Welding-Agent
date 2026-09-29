"""Windows-only flock subset for the external server's existing exclusive lock.

Injected only into owned simulator processes; no changes to the external repo.
Not a general fcntl replacement. Its byte lock coordinates Windows bridge runs,
not Linux/WSL flock clients. Only LOCK_EX[|LOCK_NB] and LOCK_UN are supported.
"""
import errno
import os
import msvcrt

LOCK_EX, LOCK_NB, LOCK_UN = 2, 4, 8


def flock(file, operation):
    fd = file if isinstance(file, int) else file.fileno()
    if operation not in (LOCK_EX, LOCK_EX | LOCK_NB, LOCK_UN):
        raise NotImplementedError("Only exclusive file locks are supported")
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        mode = {LOCK_EX: msvcrt.LK_LOCK, LOCK_EX | LOCK_NB: msvcrt.LK_NBLCK,
                LOCK_UN: msvcrt.LK_UNLCK}[operation]
        try:
            msvcrt.locking(fd, mode, 1)
        except OSError as exc:
            if operation == LOCK_EX | LOCK_NB and exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BlockingIOError(errno.EAGAIN, "Simulator queue is locked") from exc
            raise
    finally:
        os.lseek(fd, position, os.SEEK_SET)
