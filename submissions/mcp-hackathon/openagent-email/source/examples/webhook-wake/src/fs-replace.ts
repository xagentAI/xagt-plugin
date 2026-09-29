/** Sticky 父目录下目标可替换性（与 readiness / dedup 共用）。 */

import { lstatSync, statSync } from 'node:fs';
import { dirname } from 'node:path';

/**
 * Sticky 父目录允许写目录，但可能拒绝替换其他 UID 的文件。
 * 目标缺失视为可写。非完整 TOCTOU 防御。
 */
export function canReplaceDedupTarget(path: string): boolean {
  let target;
  try {
    target = lstatSync(path);
  } catch (err) {
    return (err as NodeJS.ErrnoException).code === 'ENOENT';
  }
  let parent;
  try {
    parent = statSync(dirname(path));
  } catch {
    return false;
  }
  if ((parent.mode & 0o1000) === 0) return true;
  if (typeof process.getuid !== 'function') return true;
  const uid = process.getuid();
  if (uid === 0) return true;
  return target.uid === uid || parent.uid === uid;
}
