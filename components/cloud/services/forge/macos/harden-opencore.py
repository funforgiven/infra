#!/usr/bin/env python3
"""Restore macOS integrity protections in the pinned Quickemu boot config.

Use on the dedicated builder's copied config.plist, then verify csrutil and
boot-args after a reboot before sealing. The host hashes this modified firmware
as part of the final golden manifest; jobs cannot write the source image.
"""
import argparse
from pathlib import Path
import plistlib

GUID = '7C436110-AB2A-4BBB-A880-FE41995C9F82'


def harden(path):
    config = plistlib.loads(path.read_bytes())
    nvram = config['NVRAM']['Add'][GUID]
    # Upstream enables these compatibility bypasses even on an AVX2 Intel host.
    nvram['boot-args'] = ' '.join(arg for arg in nvram['boot-args'].split()
        if not arg.startswith(('amfi_get_out_of_my_way=', 'amfi=', 'cs_enforcement_disable=')))
    nvram['csr-active-config'] = bytes(4)
    delete = config['NVRAM']['Delete'].setdefault(GUID, [])
    for key in ('boot-args', 'csr-active-config'):
        if key not in delete:
            delete.append(key)
    config['Misc']['Security']['DmgLoading'] = 'Signed'
    path.write_bytes(plistlib.dumps(config,sort_keys=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path)
    harden(parser.parse_args().config)
