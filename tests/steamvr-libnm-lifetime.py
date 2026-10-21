#!/usr/bin/env python3
"""Exercise libnm reloads with GLib retained; the negative control may crash."""
import argparse
import ctypes
import _ctypes
import hashlib
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, default=Path('/usr/lib64/libnm.so.0'))
    parser.add_argument('--nodelete', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('This regression requires native Linux and its system libraries')
    path = args.library.resolve(strict=True)
    glib = ctypes.CDLL('libglib-2.0.so.0', mode=os.RTLD_NOW | os.RTLD_GLOBAL)
    loader = ctypes.CDLL(None)
    loader.dlinfo.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    loader.dlinfo.restype = ctypes.c_int
    flags = os.RTLD_NOW | os.RTLD_LOCAL | (os.RTLD_NODELETE if args.nodelete else 0)
    print('LIBNM_INPUT', path, hashlib.sha256(path.read_bytes()).hexdigest(), flush=True)
    for index in range(16):
        print('LIBNM_OPEN', index, flush=True)
        library = ctypes.CDLL(str(path), mode=flags)
        namespace = ctypes.c_long()
        if loader.dlinfo(library._handle, 1, ctypes.byref(namespace)) != 0:
            raise RuntimeError('RTLD_DI_LMID query failed')
        print('LIBNM_CLOSE', index, 'LMID', namespace.value, flush=True)
        _ctypes.dlclose(library._handle)
    print('LIBNM_CYCLES_PASS', bool(glib._handle), flush=True)


if __name__ == '__main__':
    main()
