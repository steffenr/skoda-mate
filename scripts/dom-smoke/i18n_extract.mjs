// Writes the frontend's keys into static/i18n/keys.json (scripts/i18n_backend.py writes the backend's).
//   node i18n_extract.mjs            rewrite the frontend section
//   node i18n_extract.mjs --check    exit 1 if it is stale
import fs from 'node:fs';
import { KEYS_FILE, readKeys, scan, serialise } from './i18n_lib.mjs';

const all = readKeys();
const fresh = scan();
if (process.argv.includes('--check')) {
  const added = Object.keys(fresh).filter((k) => !all.frontend[k]);
  const gone = Object.keys(all.frontend).filter((k) => !fresh[k]);
  const changed = Object.keys(fresh).filter((k) => all.frontend[k] && JSON.stringify(all.frontend[k]) !== JSON.stringify(fresh[k]));
  for (const [what, list] of [['new', added], ['gone', gone], ['changed', changed]]) for (const k of list) console.log(`${what}: ${k}`);
  const stale = added.length + gone.length + changed.length > 0;
  console.log(stale ? 'keys.json is stale: run node scripts/dom-smoke/i18n_extract.mjs' : `keys.json is current (${Object.keys(fresh).length} frontend keys)`);
  process.exit(stale ? 1 : 0);
}
fs.writeFileSync(KEYS_FILE, serialise({ ...all, frontend: fresh }));
console.log(`${Object.keys(fresh).length} frontend keys written`);
