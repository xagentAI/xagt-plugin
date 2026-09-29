#!/usr/bin/env bash
# Batch OKX listing helper — prints onchainos commands for unlisted SKUs.
# Hard gate: run only after Agent #3977 is listed and Leo approves.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
node --input-type=module -e "
import { SERVICE_CATALOG, PENDING_OKX_LISTING_COPY, LISTED_SERVICE_PATHS } from './worker/service-catalog.mjs';

const base = 'https://api.leolabs.me';
const pending = Object.entries(SERVICE_CATALOG)
  .filter(([path]) => !LISTED_SERVICE_PATHS.has(path))
  .filter(([, meta]) => meta.mode === 'live_unlisted');

console.log('# OKX batch create draft — review before running');
console.log('# Agent ID: 3977 · ASP: Leo Labs');
console.log('');

for (const [path, meta] of pending) {
  const copy = PENDING_OKX_LISTING_COPY[meta.service_id];
  if (!copy) {
    console.log('# SKIP no copy:', path);
    continue;
  }
  console.log('# ---', copy.serviceName, '---');
  console.log('onchainos agent validate-listing \\\\');
  console.log('  --service-name', JSON.stringify(copy.serviceName), '\\\\');
  console.log('  --service-description', JSON.stringify(copy.serviceDescription), '\\\\');
  console.log('  --fee', meta.fee_usdt, '\\\\');
  console.log('  --endpoint', base + path);
  console.log('');
  console.log('# onchainos agent create ... && onchainos agent activate ...');
  console.log('');
}
"
