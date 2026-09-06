'use strict';
const fs = require('node:fs');
const source = '/Volumes/FORGEJOB/enrollment.json';
if (fs.statSync(source).size > 16384) throw new Error('Enrollment exceeds its size limit');
const enrollment = JSON.parse(fs.readFileSync(source, 'utf8'));
for (const field of ['uuid', 'token', 'handle']) {
  const value = enrollment[field];
  if (typeof value !== 'string' || !value.length || value.length > 4096 || /[\x00-\x20]/.test(value)) {
    throw new Error(`Invalid ephemeral field: ${field}`);
  }
}
const root = '/Users/forge-job/forge-job';
fs.mkdirSync(root, {mode: 0o700});
for (const field of ['uuid', 'token', 'handle']) {
  fs.writeFileSync(`${root}/${field}`, enrollment[field], {mode: 0o600, flag: 'wx'});
}
