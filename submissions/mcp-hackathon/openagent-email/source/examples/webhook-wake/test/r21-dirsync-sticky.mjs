#!/usr/bin/env bun
/**
 * 非 root：sticky 下「自有 dedup.json + 外属 .dirsync」必须在 wake 前被拒。
 * 无 root/sudo 时 SKIPPED（exit 77）。
 */

import assert from 'node:assert/strict';
import {
  accessSync,
  chmodSync,
  constants,
  mkdirSync,
  mkdtempSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { inspectDedupFile } from '../src/dedup.ts';
import { canReplaceDedupTarget, inspectReadiness, inspectStateWritable } from '../src/readiness.ts';
import { recordingWake } from '../src/wake.ts';
import { mailBody, postHook, startReceiver, testConfig } from './helpers.ts';

const NOBODY_UID = 65534;
const NOBODY_GID = 65534;

if (typeof process.getuid !== 'function' || process.getuid() !== 0) {
  console.log('SKIPPED:not_root');
  process.exit(77);
}

const root = mkdtempSync(join(tmpdir(), 'webhook-wake-dirsync-sticky-'));
chmodSync(root, 0o755);
const sticky = join(root, 'sticky');
mkdirSync(sticky, { mode: 0o1777 });
const chmodded = spawnSync('chmod', ['1777', sticky], { encoding: 'utf8' });
if (chmodded.status !== 0) {
  console.log('SKIPPED:chmod_sticky');
  process.exit(77);
}

const path = join(sticky, 'dedup.json');
// 仅 .dirsync 外属：先以 root 写好，再降权后由 nobody 自建 dedup.json
writeFileSync(`${path}.dirsync`, `${sticky}\n`, { mode: 0o644 });

try {
  process.setgid(NOBODY_GID);
  process.setuid(NOBODY_UID);
} catch {
  console.log('SKIPPED:root_cannot_drop');
  process.exit(77);
}
if (process.getuid() === 0) {
  console.log('SKIPPED:still_root');
  process.exit(77);
}

accessSync(root, constants.R_OK | constants.X_OK);
accessSync(sticky, constants.R_OK | constants.W_OK | constants.X_OK);
writeFileSync(path, `${JSON.stringify({ records: {} })}\n`, { mode: 0o600 });
const dirsyncSt = statSync(`${path}.dirsync`);
const dedupSt = statSync(path);
assert.notEqual(dirsyncSt.uid, process.getuid());
assert.equal(dedupSt.uid, process.getuid());
assert.equal(canReplaceDedupTarget(path), true);
assert.equal(canReplaceDedupTarget(`${path}.dirsync`), false);
assert.equal(inspectStateWritable(path), false);
assert.equal(inspectDedupFile(path).ok, false);
assert.equal(inspectReadiness(testConfig({ dedup: { path } }, root)).stateWritable, false);
console.log('PROOF:dirsync_irreplaceable');

const wakes = [];
const receiver = await startReceiver(testConfig({ mode: 'canary', dedup: { path } }, root), {
  wake: recordingWake(wakes),
});
const refused = await postHook(receiver, { body: mailBody() });
await receiver.close();
assert.equal(refused.status, 503);
assert.equal(refused.json.reason, 'state_unwritable');
assert.equal(wakes.length, 0);
console.log('PROOF:zero_wake_before_dirsync');
console.log(`EXECUTED:uid=${process.getuid()}`);
console.log(`FIXTURE:${root}`);
