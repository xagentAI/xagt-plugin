import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { auditDelivery } from './auditor.mjs';
import { assessWorldCupSmartMoney } from './worldcup-smart-money.mjs';
import {
  assessOkxAiDataService,
  getOkxAiDataServiceByPath,
  listOkxAiDataServices
} from './okx-ai-data-services.mjs';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const demoDir = path.join(rootDir, 'demo');
const sampleDir = path.join(rootDir, 'sample-inputs');
const discoveryDir = path.join(rootDir, 'discovery');

export function createServer() {
  return http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, 'http://127.0.0.1');

      if (req.method === 'GET' && url.pathname === '/health') {
        return sendJson(res, 200, {
          ok: true,
          service: 'agent-acceptance-gate',
          mode: 'local_only'
        });
      }

      if (req.method === 'GET' && url.pathname === '/api/sample-audits') {
        const audits = readSampleAudits();
        return sendJson(res, 200, audits);
      }

      if (req.method === 'GET' && url.pathname === '/api/okx-ai-services') {
        return sendJson(res, 200, {
          schema_version: '0.1',
          mode: 'local_launch_pack',
          services: [
            {
              service_id: 'world_cup_smart_money_radar',
              path: '/world-cup-smart-money-radar',
              title: 'World Cup Smart Money Radar',
              category: 'world_cup',
              fee_usdt: '1',
              description: 'Tracks profitable World Cup prediction-market wallets and highlights position changes.',
              mode: 'public_safe_demo'
            },
            ...listOkxAiDataServices()
          ]
        });
      }

      if (req.method === 'GET' && url.pathname === '/.well-known/agent-service.json') {
        return sendFile(res, path.join(discoveryDir, 'agent-service.json'), 'application/json; charset=utf-8');
      }

      if (req.method === 'GET' && url.pathname === '/mcp-tool-manifest.json') {
        return sendFile(res, path.join(discoveryDir, 'mcp-tool-manifest.json'), 'application/json; charset=utf-8');
      }

      if (req.method === 'GET' && url.pathname === '/openapi.yaml') {
        return sendFile(res, path.join(rootDir, 'openapi.yaml'), 'text/yaml; charset=utf-8');
      }

      if (req.method === 'POST' && url.pathname === '/audit-agent-deliverable') {
        const payload = await readJsonBody(req);
        const audit = auditDelivery(payload);
        return sendJson(res, 200, audit);
      }

      if (req.method === 'POST' && url.pathname === '/world-cup-smart-money-radar') {
        const payload = await readJsonBody(req);
        const report = assessWorldCupSmartMoney(payload);
        return sendJson(res, 200, report);
      }

      if (req.method === 'POST') {
        const service = getOkxAiDataServiceByPath(url.pathname);
        if (service) {
          const payload = await readJsonBody(req);
          const report = assessOkxAiDataService(service, payload);
          return sendJson(res, 200, report);
        }
      }

      if (req.method === 'GET') {
        return serveStatic(url.pathname, res);
      }

      sendJson(res, 405, { error: 'method_not_allowed' });
    } catch (error) {
      sendJson(res, 400, {
        error: 'bad_request',
        message: error instanceof Error ? error.message : String(error)
      });
    }
  });
}

function readSampleAudits() {
  return fs.readdirSync(sampleDir)
    .filter((file) => file.endsWith('.json'))
    .sort()
    .flatMap((file) => {
      const input = JSON.parse(fs.readFileSync(path.join(sampleDir, file), 'utf8'));
      if (!input.task || !input.delivery) return [];
      return [{
        input_file: file,
        title: titleFromFile(file),
        audit: auditDelivery(input)
      }];
    });
}

function titleFromFile(file) {
  return file
    .replace(/^\d+-/, '')
    .replace(/\.json$/, '')
    .replaceAll('-', ' ');
}

function serveStatic(pathname, res) {
  const relativePath = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
  const filePath = path.resolve(demoDir, relativePath);

  if (!filePath.startsWith(demoDir)) {
    return sendText(res, 403, 'Forbidden');
  }

  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    return sendText(res, 404, 'Not found');
  }

  const ext = path.extname(filePath);
  const contentType = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8'
  }[ext] ?? 'text/plain; charset=utf-8';

  res.writeHead(200, { 'content-type': contentType });
  fs.createReadStream(filePath).pipe(res);
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) {
        req.destroy();
        reject(new Error('Request body too large'));
      }
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(body || '{}'));
      } catch (error) {
        reject(error);
      }
    });
    req.on('error', reject);
  });
}

function sendJson(res, status, payload) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' });
  res.end(`${JSON.stringify(payload, null, 2)}\n`);
}

function sendText(res, status, text) {
  res.writeHead(status, { 'content-type': 'text/plain; charset=utf-8' });
  res.end(text);
}

function sendFile(res, filePath, contentType) {
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    return sendText(res, 404, 'Not found');
  }

  res.writeHead(200, { 'content-type': contentType });
  fs.createReadStream(filePath).pipe(res);
}
