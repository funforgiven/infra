#!/usr/bin/env python3
from pathlib import Path
import hashlib
import os
import struct

path=Path('/data/server/valheim_server_Data/Managed/assembly_valheim.dll')
data=path.read_bytes()
digest=hashlib.sha256(data).hexdigest()
if digest == '074c6cc01a4459bc542600f0898b81298d1c002f8ece0315517c50e8853a43d8':
    print('Steam app ID compatibility patch already present.')
elif digest == '1231fc2ffdbe6038ba622b8646c2084980d06962e5f8521ae5a0b886be0f1c61':
    modified=bytearray(data)
    modified[615976:615980]=struct.pack('<I',480)
    assert hashlib.sha256(modified).hexdigest() == '074c6cc01a4459bc542600f0898b81298d1c002f8ece0315517c50e8853a43d8'
    temporary=path.with_suffix('.dll.app480-tmp')
    temporary.write_bytes(modified)
    temporary.chmod(path.stat().st_mode & 0o777)
    os.replace(temporary,path)
    print('Added Steam app ID 480 to the server startup allowlist.')
else:
    raise SystemExit('App ID compatibility patch requires revalidation for this game build.')
