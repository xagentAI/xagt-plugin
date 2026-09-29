import assert from 'node:assert/strict';
import fs from 'node:fs';

const openapi = fs.readFileSync(new URL('../openapi.yaml', import.meta.url), 'utf8');
const deployment = fs.readFileSync(new URL('../DEPLOYMENT.md', import.meta.url), 'utf8');
const readme = fs.readFileSync(new URL('../README.md', import.meta.url), 'utf8');
const reviewEnv = fs.readFileSync(
  new URL('../config/xagent-review.env.example', import.meta.url),
  'utf8'
);
const packageJson = JSON.parse(
  fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8')
);
const packageLock = JSON.parse(
  fs.readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8')
);

assert.match(openapi, /https:\/\/api\.leolabs\.me/);
assert.match(openapi, /\/\.well-known\/xagent-verification\.json:/);
assert.match(openapi, /\/xagent\/agent-delivery-acceptance-audit:/);
assert.doesNotMatch(openapi, /Not deployed as a public API/i);

for (const name of [
  'XAGENT_GIT_COMMIT',
  'XAGENT_PROJECT_SLUG',
  'XAGENT_REVIEW_ENABLED'
]) {
  assert.match(deployment, new RegExp(name));
}
assert.match(deployment, /https:\/\/api\.leolabs\.me\/health/);
assert.match(deployment, /not yet deployed/i);
assert.match(deployment, /--var XAGENT_GIT_COMMIT:/);
assert.match(deployment, /--var XAGENT_PROJECT_SLUG:runesleo-agent-acceptance-gate/);
assert.match(deployment, /--var XAGENT_REVIEW_ENABLED:true/);
assert.doesNotMatch(deployment, /No public API endpoint\./);
assert.doesNotMatch(readme, /No public endpoint exists\./);
assert.match(reviewEnv, /XAGENT_GIT_COMMIT=[0-9a-f]{40}/);
assert.match(reviewEnv, /XAGENT_PROJECT_SLUG=runesleo-agent-acceptance-gate/);
assert.match(reviewEnv, /XAGENT_REVIEW_ENABLED=false/);
assert.equal(packageJson.devDependencies.wrangler, '4.133.0');
assert.equal(packageLock.packages[''].devDependencies.wrangler, '4.133.0');

console.log('PASS X-Agent submission documentation contract');
