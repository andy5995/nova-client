# instance_lock.py
"""One sync at a time per config file.

The daemon and a hand-run client.py read the same outbound and inbound
directories. Run together, one deletes a packet the other is still uploading,
or writes inbound packets while dosemu is reading them. Both take this lock.

The lock file sits beside the config, not in the temp directory: on Windows a
scheduled task running as SYSTEM and a sysop at a prompt have different temp
directories, and would never see each other's lock.
"""

import sys
from pathlib import Path


class InstanceLock:
    def __init__(self, config_path: str):
        self.path = Path(f"{Path(config_path).resolve()}.lock")
        self._file = None

    def acquire(self) -> bool:
        """Take the lock if it is free. False if another process holds it.

        Raises OSError if the lock file can neither be created nor opened.
        """
        try:
            handle = open(self.path, "a+")
        except PermissionError:
            # Created by the account the daemon runs as. A read handle is
            # enough to lock it.
            handle = open(self.path, "r")
        try:
            if sys.platform == "win32":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._file = handle
        return True

    def release(self) -> None:
        if self._file is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._file.close()
            self._file = None
