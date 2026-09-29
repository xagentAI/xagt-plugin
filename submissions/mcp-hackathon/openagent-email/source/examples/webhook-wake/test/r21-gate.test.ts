/**
 * #177 hardening：marker symlink / timer 上限 / alert scheme /
 * .dirsync wake 前可移除性 / 非 loopback opt-in —— 正负控。
 */

import { afterEach, describe, expect, test } from 'bun:test';
import { constants, existsSync, mkdirSync, readFileSync, symlinkSync, unlinkSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  MAX_ALERT_HOOK_TIMEOUT_MS,
  MAX_REQUEST_TIMEOUT_MS,
  MAX_SEND_TIMEOUT_MS,
  REQUEST_SEND_HEADROOM_MS,
  parseFileConfig,
  type FileConfig,
} from '../src/config.ts';
import { DedupError, DedupStore, buildNofollowOpenFlags, inspectDedupFile } from '../src/dedup.ts';
import { isLoopbackHost } from '../src/ids.ts';
import { canReplaceDedupTarget, inspectStateWritable } from '../src/readiness.ts';
import {
  FIXTURE_SECRET,
  mailBody,
  postHook,
  startReceiver,
  tempDir,
  testConfig,
  writeSecretFile,
} from './helpers.ts';
import { createReceiver, listenReceiver, type Receiver } from '../src/server.ts';

const receivers: Receiver[] = [];
afterEach(async () => {
  while (receivers.length) await receivers.pop()!.close();
});

function fileBase(dir: string): FileConfig {
  const secret = writeSecretFile(dir, 'ok.whs', FIXTURE_SECRET);
  return {
    routes: {
      canary: {
        subscriptionId: 'whk_4a1b8c2d-5e6f-4a7b-8c9d-0e1f2a3b4c5d',
        domain: 'openagent.email',
        mailbox: 'alice@openagent.email',
        secretFile: secret,
        terminal: 'term_examplecanary0001',
      },
    },
  };
}

describe('R21 marker symlink-safe persistUnacked', () => {
  test('正控：常规 commit 仍持久化并清除 .unacked', async () => {
    const dir = tempDir();
    const path = join(dir, 'dedup.json');
    const store = new DedupStore({
      path,
      retentionMs: 7 * 24 * 60 * 60 * 1000,
      maxRecords: 8,
    });
    await store.commit(
      {
        key: 'whk_4a1b8c2d-5e6f-4a7b-8c9d-0e1f2a3b4c5d:evt_11111111-2222-3333-4444-555555555555',
        status: 'success',
        storedAtMs: 1,
        expiresAtMs: 9_999_999_999_999,
      },
      1,
    );
    expect(existsSync(path)).toBe(true);
    expect(existsSync(store.unackedPath())).toBe(false);
  });

  test('负控：.unacked 为指向敏感文件的 symlink 时必须拒绝写入', async () => {
    const dir = tempDir();
    const path = join(dir, 'dedup.json');
    const victim = join(dir, 'victim-secret.txt');
    writeFileSync(victim, 'KEEP_ME\n', { mode: 0o600 });

    // 预置 symlink：inspect/requireDurable 必须 fail-closed（不跟随）
    symlinkSync(victim, `${path}.unacked`);
    expect(inspectDedupFile(path)).toEqual({ ok: false, reason: 'state_unacked' });
    const early = new DedupStore({
      path,
      retentionMs: 7 * 24 * 60 * 60 * 1000,
      maxRecords: 8,
    });
    await expect(
      early.commit(
        {
          key: 'whk_4a1b8c2d-5e6f-4a7b-8c9d-0e1f2a3b4c5d:evt_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
          status: 'success',
          storedAtMs: 2,
          expiresAtMs: 9_999_999_999_999,
        },
        2,
      ),
    ).rejects.toMatchObject({ message: 'dedup_unacked_not_file' });
    expect(readFileSync(victim, 'utf8')).toBe('KEEP_ME\n');

    // 在 persistUnacked 前瞬间植入 symlink，咬 O_NOFOLLOW（mutation 去掉后会写穿 victim）
    unlinkSync(`${path}.unacked`);
    const store = new DedupStore(
      { path, retentionMs: 7 * 24 * 60 * 60 * 1000, maxRecords: 8 },
      {
        onDirFsync: () => {
          if (!existsSync(store.unackedPath())) {
            symlinkSync(victim, store.unackedPath());
          }
        },
      },
    );
    await expect(
      store.commit(
        {
          key: 'whk_4a1b8c2d-5e6f-4a7b-8c9d-0e1f2a3b4c5d:evt_bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
          status: 'success',
          storedAtMs: 3,
          expiresAtMs: 9_999_999_999_999,
        },
        3,
      ),
    ).rejects.toMatchObject({ message: 'dedup_unacked_symlink' });
    expect(readFileSync(victim, 'utf8')).toBe('KEEP_ME\n');
  });
});

describe('R21 timer load-time caps', () => {
  test('正控：推荐区间内接受；负控：超上沿与 >2^31-1 拒载', () => {
    const dir = tempDir();
    const base = fileBase(dir);
    expect(parseFileConfig({ ...base, requestTimeoutMs: MAX_REQUEST_TIMEOUT_MS }).requestTimeoutMs).toBe(
      MAX_REQUEST_TIMEOUT_MS,
    );
    // send 顶满 30s 时 request 默认 10s 不满足 headroom；合法上沿 = request−2s
    expect(
      parseFileConfig({
        ...base,
        requestTimeoutMs: MAX_REQUEST_TIMEOUT_MS,
        sendTimeoutMs: MAX_REQUEST_TIMEOUT_MS - REQUEST_SEND_HEADROOM_MS,
      }).sendTimeoutMs,
    ).toBe(MAX_REQUEST_TIMEOUT_MS - REQUEST_SEND_HEADROOM_MS);
    expect(
      parseFileConfig({ ...base, alertHook: { timeoutMs: MAX_ALERT_HOOK_TIMEOUT_MS } }).alertHook.timeoutMs,
    ).toBe(MAX_ALERT_HOOK_TIMEOUT_MS);

    expect(() => parseFileConfig({ ...base, requestTimeoutMs: MAX_REQUEST_TIMEOUT_MS + 1 })).toThrow(
      'config_invalid:requestTimeoutMs',
    );
    expect(() => parseFileConfig({ ...base, sendTimeoutMs: MAX_SEND_TIMEOUT_MS + 1 })).toThrow(
      'config_invalid:sendTimeoutMs',
    );
    expect(() =>
      parseFileConfig({ ...base, alertHook: { timeoutMs: MAX_ALERT_HOOK_TIMEOUT_MS + 1 } }),
    ).toThrow('config_invalid:alertHook.timeoutMs');
    // 溢出场景：超过有符号 32-bit 毫秒上沿
    expect(() => parseFileConfig({ ...base, requestTimeoutMs: 2_147_483_648 })).toThrow(
      'config_invalid:requestTimeoutMs',
    );
    expect(() => parseFileConfig({ ...base, sendTimeoutMs: 2_147_483_648 })).toThrow(
      'config_invalid:sendTimeoutMs',
    );
    expect(() => parseFileConfig({ ...base, alertHook: { timeoutMs: 2_147_483_648 } })).toThrow(
      'config_invalid:alertHook.timeoutMs',
    );
  });
});

describe('R21 alertHook.url scheme', () => {
  test('正控：http/https 与 null；负控：其余 scheme / 畸形 URL', () => {
    const dir = tempDir();
    const base = fileBase(dir);
    expect(parseFileConfig({ ...base, alertHook: { url: null } }).alertHook.url).toBeNull();
    expect(parseFileConfig({ ...base, alertHook: { url: 'https://hooks.example/a' } }).alertHook.url).toBe(
      'https://hooks.example/a',
    );
    expect(parseFileConfig({ ...base, alertHook: { url: 'http://127.0.0.1:9/x' } }).alertHook.url).toBe(
      'http://127.0.0.1:9/x',
    );
    expect(() => parseFileConfig({ ...base, alertHook: { url: 'ftp://evil.example/x' } })).toThrow(
      'config_invalid:alertHook.url',
    );
    expect(() => parseFileConfig({ ...base, alertHook: { url: 'file:///etc/passwd' } })).toThrow(
      'config_invalid:alertHook.url',
    );
    expect(() => parseFileConfig({ ...base, alertHook: { url: 'not-a-url' } })).toThrow(
      'config_invalid:alertHook.url',
    );
  });
});

describe('R21 .dirsync pre-wake removiability', () => {
  test('正控：自有 sticky .dirsync 可替换（writable）', () => {
    const root = tempDir();
    const sticky = join(root, 'sticky');
    mkdirSync(sticky, { mode: 0o1777 });
    expect(spawnSync('chmod', ['1777', sticky]).status).toBe(0);
    const path = join(sticky, 'dedup.json');
    writeFileSync(path, `${JSON.stringify({ records: {} })}\n`, { mode: 0o600 });
    writeFileSync(`${path}.dirsync`, `${sticky}\n`, { mode: 0o600 });
    expect(canReplaceDedupTarget(`${path}.dirsync`)).toBe(true);
    expect(inspectStateWritable(path)).toBe(true);
    expect(inspectDedupFile(path)).toEqual({ ok: false, reason: 'state_dirsync' });
  });

  test('负控：非 root 外属 sticky .dirsync 在 wake 前拒（有 root/sudo 才执行）', () => {
    const helper = fileURLToPath(new URL('./r21-dirsync-sticky.mjs', import.meta.url));
    const cwd = fileURLToPath(new URL('..', import.meta.url));
    const run = (cmd: string, args: string[]) =>
      spawnSync(cmd, args, { cwd, encoding: 'utf8', timeout: 20_000 });

    let ran = run(process.execPath, [helper]);
    if (ran.status === 77 && `${ran.stdout}${ran.stderr}`.includes('SKIPPED:not_root')) {
      const sudoOk = run('sudo', ['-n', 'true']);
      if (sudoOk.status === 0) {
        ran = run('sudo', ['-n', process.execPath, helper]);
      }
    }
    const text = `${ran.stdout}${ran.stderr}`;
    if (ran.status === 77) {
      expect(text).toContain('SKIPPED:');
      return;
    }
    expect(ran.status).toBe(0);
    expect(text).toContain('PROOF:dirsync_irreplaceable');
    expect(text).toContain('PROOF:zero_wake_before_dirsync');
    expect(text).toContain('EXECUTED:uid=');
  });
});

describe('R21 non-loopback opt-in', () => {
  test('负控：非 loopback 无 opt-in 拒载；正控：显式 allowNonLoopback 可载并可听', async () => {
    const dir = tempDir();
    const base = fileBase(dir);
    expect(() => parseFileConfig({ ...base, listen: { host: '0.0.0.0', port: 0 } })).toThrow(
      'config_invalid:listen.allowNonLoopback',
    );
    const ok = parseFileConfig({
      ...base,
      listen: { host: '0.0.0.0', port: 0, allowNonLoopback: true },
    });
    expect(ok.listen).toEqual({ host: '0.0.0.0', port: 0, allowNonLoopback: true });

    const receiver = await startReceiver(
      testConfig({ listen: { host: '127.0.0.1', port: 0, allowNonLoopback: false } }, dir),
    );
    receivers.push(receiver);
    expect(receiver.url().startsWith('http://127.0.0.1:')).toBe(true);

    const open = await startReceiver(
      testConfig({ listen: { host: '0.0.0.0', port: 0, allowNonLoopback: true } }, dir),
    );
    receivers.push(open);
    expect(open.url()).toMatch(/^http:\/\/0\.0\.0\.0:\d+/);
  });
});


describe('R1 O_NOFOLLOW fail-closed flag builder', () => {
  test('负控：O_NOFOLLOW 缺失（undefined/非 number）即抛 dedup_unacked_symlink', () => {
    expect(() => buildNofollowOpenFlags(constants.O_WRONLY | constants.O_CREAT | constants.O_TRUNC, undefined)).toThrow(
      DedupError,
    );
    try {
      buildNofollowOpenFlags(0, undefined);
      throw new Error('expected throw');
    } catch (err) {
      expect(err).toBeInstanceOf(DedupError);
      expect((err as DedupError).code).toBe('dedup_dir_fsync_failed');
      expect((err as DedupError).message).toBe('dedup_unacked_symlink');
    }
    expect(() => buildNofollowOpenFlags(0, 'nofollow' as unknown)).toThrow(DedupError);
    expect(() => buildNofollowOpenFlags(0, null)).toThrow(DedupError);
  });

  test('正控：注入合法 nofollow 数值时 flags 含该位', () => {
    const fake = 0x20000;
    expect(buildNofollowOpenFlags(0o1, fake)).toBe(0o1 | fake);
    // 生产默认 constants.O_NOFOLLOW 必须可用（本 CI/Linux）
    expect(typeof constants.O_NOFOLLOW).toBe('number');
    expect(buildNofollowOpenFlags(constants.O_WRONLY) & constants.O_NOFOLLOW).toBe(constants.O_NOFOLLOW);
  });
});

describe('R1 listenReceiver library non-loopback guard', () => {
  test('负控：库调用绕过 parseFileConfig 时非 loopback 无 opt-in 仍拒绝 listen', async () => {
    const dir = tempDir();
    // 故意构造 programmatic config，跳过 parseFileConfig
    const bypassed = testConfig(
      { listen: { host: '0.0.0.0', port: 0, allowNonLoopback: false } },
      dir,
    );
    const receiver = createReceiver(bypassed);
    await expect(listenReceiver(receiver)).rejects.toThrow('config_invalid:listen.allowNonLoopback');
    // 省略字段（undefined）同样视为 false；listen 未成功则勿 close（server 未 listen）
    const omitted = testConfig({ listen: { host: '0.0.0.0', port: 0 } }, dir);
    delete (omitted.listen as { allowNonLoopback?: boolean }).allowNonLoopback;
    const r2 = createReceiver(omitted);
    await expect(listenReceiver(r2)).rejects.toThrow('config_invalid:listen.allowNonLoopback');
  });

  test('正控：loopback 无 opt-in 可听；非 loopback + allowNonLoopback:true 可听', async () => {
    const dir = tempDir();
    const loop = createReceiver(testConfig({ listen: { host: '127.0.0.1', port: 0 } }, dir));
    receivers.push(loop);
    const url = await listenReceiver(loop);
    expect(url.startsWith('http://127.0.0.1:')).toBe(true);

    const open = createReceiver(
      testConfig({ listen: { host: '0.0.0.0', port: 0, allowNonLoopback: true } }, dir),
    );
    receivers.push(open);
    const openUrl = await listenReceiver(open);
    expect(openUrl).toMatch(/^http:\/\/0\.0\.0\.0:\d+/);
  });
});

describe('R2 IPv4 loopback 127.0.0.0/8', () => {
  test('正控：127.0.0.2 无 opt-in 可载并可听；::1/localhost/127.0.0.1 仍认', async () => {
    expect(isLoopbackHost('127.0.0.1')).toBe(true);
    expect(isLoopbackHost('127.0.0.2')).toBe(true);
    expect(isLoopbackHost('127.255.255.255')).toBe(true);
    expect(isLoopbackHost('::1')).toBe(true);
    expect(isLoopbackHost('localhost')).toBe(true);

    const dir = tempDir();
    const cfg = parseFileConfig({
      ...fileBase(dir),
      listen: { host: '127.0.0.2', port: 0 },
    });
    expect(cfg.listen.host).toBe('127.0.0.2');
    expect(cfg.listen.allowNonLoopback).toBe(false);

    const receiver = await startReceiver(
      testConfig({ listen: { host: '127.0.0.2', port: 0, allowNonLoopback: false } }, dir),
    );
    receivers.push(receiver);
    expect(receiver.url()).toMatch(/^http:\/\/127\.0\.0\.2:\d+/);
  });

  test('负控：127.256.0.1 畸形非 loopback；8.8.8.8 无 opt-in 仍拒（不回归）', () => {
    expect(isLoopbackHost('127.256.0.1')).toBe(false);
    expect(isLoopbackHost('127.0.0.256')).toBe(false);
    expect(isLoopbackHost('8.8.8.8')).toBe(false);

    const dir = tempDir();
    const base = fileBase(dir);
    expect(() => parseFileConfig({ ...base, listen: { host: '127.256.0.1', port: 0 } })).toThrow(
      'config_invalid:listen.allowNonLoopback',
    );
    expect(() => parseFileConfig({ ...base, listen: { host: '8.8.8.8', port: 0 } })).toThrow(
      'config_invalid:listen.allowNonLoopback',
    );
  });
});

describe('R3 request/send headroom', () => {
  test('负控：requestTimeoutMs == sendTimeoutMs 拒载；正控：request == send + 2000 通过；默认 10s/8s 不回归', () => {
    const dir = tempDir();
    const base = fileBase(dir);
    // 默认 10000/8000 满足 10000 >= 8000+2000
    const defaults = parseFileConfig(base);
    expect(defaults.requestTimeoutMs).toBe(10_000);
    expect(defaults.sendTimeoutMs).toBe(8_000);

    expect(() =>
      parseFileConfig({ ...base, requestTimeoutMs: 8_000, sendTimeoutMs: 8_000 }),
    ).toThrow('config_invalid:requestTimeoutMs.headroom');
    expect(() =>
      parseFileConfig({ ...base, requestTimeoutMs: 30_000, sendTimeoutMs: 30_000 }),
    ).toThrow('config_invalid:requestTimeoutMs.headroom');

    const ok = parseFileConfig({
      ...base,
      requestTimeoutMs: 10_000,
      sendTimeoutMs: 8_000, // == request − 2000
    });
    expect(ok.requestTimeoutMs).toBe(10_000);
    expect(ok.sendTimeoutMs).toBe(8_000);

    const okMax = parseFileConfig({
      ...base,
      requestTimeoutMs: MAX_REQUEST_TIMEOUT_MS,
      sendTimeoutMs: MAX_REQUEST_TIMEOUT_MS - REQUEST_SEND_HEADROOM_MS,
    });
    expect(okMax.sendTimeoutMs).toBe(28_000);
  });
});
