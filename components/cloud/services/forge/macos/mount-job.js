'use strict';
// Mount only the broker's optical enrollment volume, without a console login.
// No executable content is loaded from the volume by this privileged helper.
const fs = require('node:fs');
const {execFileSync} = require('node:child_process');
const target = '/Volumes/FORGEJOB';
if (fs.existsSync(`${target}/enrollment.json`)) process.exit(0);
function diskutil(...args) {
  const plist = execFileSync('/usr/sbin/diskutil', args, {timeout: 10000});
  return JSON.parse(execFileSync('/usr/bin/plutil', ['-convert', 'json', '-o', '-', '-'],
    {input: plist, timeout: 10000}));
}
for (const id of diskutil('list', '-plist').AllDisks) {
  if (!/^disk\d+(s\d+)*$/.test(id)) throw new Error('Invalid disk identifier');
  const info = diskutil('info', '-plist', id);
  if (info.VolumeName !== 'FORGEJOB' || info.FilesystemType !== 'cd9660') continue;
  fs.mkdirSync(target, {recursive: true, mode: 0o700});
  execFileSync('/usr/sbin/diskutil', ['mount', 'readOnly', '-mountPoint', target, id], {timeout: 30000});
  break;
}
