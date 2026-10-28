"""Pre-start free-space floor and writeability check, without opening a stream.

This is not a duration/bitrate prediction or a filesystem quota reservation.
Other processes, live buffers and active recordings may consume space afterwards.
"""
import os
import shutil
import tempfile

from i18n import gettext as _

MIB = 1024 * 1024
DEFAULT_RESERVE_MIB = 256
MAX_RESERVE_MIB = 65536


class StorageError(RuntimeError):
    pass


def normalize_reserve(value):
    if type(value) is int and 0 <= value <= MAX_RESERVE_MIB:
        return value
    return DEFAULT_RESERVE_MIB


def check_destination(directory, reserve_mib=DEFAULT_RESERVE_MIB):
    reserve = normalize_reserve(reserve_mib)
    try:
        target = os.path.abspath(os.fspath(directory))
        os.makedirs(target, exist_ok=True)
        if not os.path.isdir(target):
            raise OSError('not a directory')
        # Test an actual tiny write on the destination, not only access bits.
        # Only this temporary file is removed; user files are never deleted.
        with tempfile.TemporaryFile(dir=target, prefix='.iptv-storage-check-') as probe:
            probe.write(b'\0')
            probe.flush()
            os.fsync(probe.fileno())
    except (OSError, ValueError, TypeError) as error:
        raise StorageError(_("The recording folder is unavailable or not writable:\n{error}").format(error=error)) from error
    try:
        free = shutil.disk_usage(target).free
        if type(free) is not int or free < 0:
            raise OSError('invalid free-space response')
    except (OSError, ValueError) as error:
        raise StorageError(_("Free space could not be determined:\n{error}").format(error=error)) from error
    if free < reserve * MIB:
        raise StorageError(_("Not enough free space to start recording: {free} MiB available; "
                            "at least {reserve} MiB required.").format(free=free // MIB, reserve=reserve))
    return {'path': target, 'free': free, 'reserve_mib': reserve}
