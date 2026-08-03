import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

export interface SubmitInput {
  name?: string;
  slug?: string;
  intro?: string;
  repo?: string;
  api?: string;
  health?: string;
  commit?: string;
}

export interface SubmitPayload {
  name: string;
  slug: string;
  intro: string;
  repo: string;
  api: string;
  health: string;
  commit: string;
}

export interface SubmitOptions {
  cliVersion: string;
  input: SubmitInput;
  submissionRepo?: string;
  outputDir?: string;
}

export interface SubmitResult {
  slug: string;
  filename: string;
  manifestFilename: string;
  rightsFilename: string;
  forkUrl: string;
  repoUrl: string;
  localPath: string;
  localManifestPath: string;
  localRightsPath: string;
  markdown: string;
  manifest: string;
  rights: string;
}

const DEFAULT_REPO = "xagentAI/xagt-plugin";

export async function runSubmit(options: SubmitOptions): Promise<SubmitResult> {
  const payload = await collectPayload(options.input);
  validatePayload(payload);

  const repo = options.submissionRepo ?? DEFAULT_REPO;
  const filename = `submissions/${payload.slug}/SUBMISSION.md`;
  const manifestFilename = `submissions/${payload.slug}/submission.json`;
  const rightsFilename = `submissions/${payload.slug}/RIGHTS.md`;
  const markdown = renderMarkdown(payload, options.cliVersion);
  const manifest = renderManifest(payload, options.cliVersion);
  const rights = renderRightsDeclaration(payload);
  const repoUrl = `https://github.com/${repo}`;
  const forkUrl = `${repoUrl}/fork`;

  const outDir = options.outputDir ?? process.cwd();
  const localPath = resolve(outDir, `submission-${payload.slug}.md`);
  const localManifestPath = resolve(outDir, `submission-${payload.slug}.json`);
  const localRightsPath = resolve(outDir, `submission-${payload.slug}-RIGHTS.md`);
  await writeFile(localPath, markdown, "utf8");
  await writeFile(localManifestPath, manifest, "utf8");
  await writeFile(localRightsPath, rights, "utf8");

  return {
    slug: payload.slug,
    filename,
    manifestFilename,
    rightsFilename,
    forkUrl,
    repoUrl,
    localPath,
    localManifestPath,
    localRightsPath,
    markdown,
    manifest,
    rights
  };
}

async function collectPayload(seed: SubmitInput): Promise<SubmitPayload> {
  if (!needsPrompt(seed)) {
    return normalizePayload({
      name: seed.name!,
      slug: seed.slug!,
      intro: seed.intro!,
      repo: seed.repo!,
      api: seed.api!,
      health: seed.health!,
      commit: seed.commit!
    });
  }

  const rl = createInterface({ input, output });
  const askRequired = async (label: string, seeded?: string): Promise<string> => {
    if (seeded?.trim()) return seeded.trim();
    while (true) {
      const value = (await rl.question(`  ${label}: `)).trim();
      if (value) return value;
      output.write(`  (${label} is required)\n`);
    }
  };

  try {
    return normalizePayload({
      name: await askRequired("Project name", seed.name),
      slug: await askRequired("Submission slug (for example, team-name-project-name)", seed.slug),
      intro: await askRequired("One-line description", seed.intro),
      repo: await askRequired("GitHub repo URL", seed.repo),
      api: await askRequired("Deployed API base URL", seed.api),
      health: await askRequired("Health-check URL", seed.health),
      commit: await askRequired("40-character review commit", seed.commit)
    });
  } finally {
    rl.close();
  }
}

function needsPrompt(seed: SubmitInput): boolean {
  return !seed.name || !seed.slug || !seed.intro || !seed.repo || !seed.api || !seed.health || !seed.commit;
}

function normalizePayload(payload: SubmitPayload): SubmitPayload {
  return {
    name: payload.name.trim(),
    slug: payload.slug.trim(),
    intro: payload.intro.trim(),
    repo: normalizeUrl(payload.repo),
    api: normalizeUrl(payload.api),
    health: normalizeUrl(payload.health),
    commit: payload.commit.trim()
  };
}

function validatePayload(payload: SubmitPayload): void {
  if (!payload.name) throw new Error("project name is required");
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(payload.slug)) {
    throw new Error("submission slug must use lowercase letters, numbers, and hyphens");
  }
  if (!payload.intro) throw new Error("description is required");
  assertHttpUrl(payload.repo, "GitHub repo URL");
  assertHttpUrl(payload.api, "deployed API URL");
  assertHttpUrl(payload.health, "health-check URL");
  if (!/^[a-f0-9]{40}$/i.test(payload.commit)) {
    throw new Error("review commit must be a 40-character Git commit SHA");
  }
}

function normalizeUrl(raw: string): string {
  const trimmed = raw.trim();
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed.replace(/^\/+/, "")}`;
}

function assertHttpUrl(raw: string, label: string): void {
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error("unsupported protocol");
  } catch {
    throw new Error(`${label} must be a valid http(s) URL`);
  }
}

export function renderMarkdown(payload: SubmitPayload, cliVersion: string): string {
  const submittedAt = new Date().toISOString();
  return `# ${payload.name}

**Submitted via:** \`xagt-plugin@${cliVersion}\`
**Submitted at:** ${submittedAt}

## Capability

- **One-line description:** ${payload.intro}
- **Capability boundary:** _Describe what this service does and does not do._

## Live API

- **API base URL:** ${payload.api}
- **Health-check URL:** ${payload.health}
- **Deployment proof URL:** ${new URL("/.well-known/xagent-verification.json", payload.api).toString()}
- **Authentication:** _State how reviewers receive short-lived access without committing a secret._
- **Rate limits / known limits:** _State limits, timeouts, and material restrictions._

## Source and reproducibility

- **Source repository:** ${payload.repo}
- **Review commit:** \`${payload.commit}\`
- **Source submitted in this PR:** \`source/\`
- **Run tests:** _Add the exact command._
- **Run locally:** _Add the exact command._
- **Deploy:** _Add the exact command or documented steps._
- **Version binding:** _Explain how the running API identifies this commit or build._

## Verification

- Add reproducible API evidence to \`verification/README.md\`.
- Include a health-check call, one real capability call, expected output, and one safe error case.

## Security and data handling

- **Data collected:** _Fields or none._
- **Purpose and retention:** _Why and for how long._
- **Third parties / outbound network calls:** _Services or none._
- **Known risks / restrictions:** _Anything reviewers or downstream agents must know._

## Support

- **Team / builder:** _Name_
- **Contact:** _Preferred contact channel_
- **License / rights:** _Confirm you can authorize review and deployment._
`;
}

export function renderManifest(payload: SubmitPayload, cliVersion: string): string {
  const proofUrl = new URL("/.well-known/xagent-verification.json", payload.api).toString();
  return `${JSON.stringify({
    schemaVersion: 1,
    name: payload.name,
    slug: payload.slug,
    sourceRepository: payload.repo,
    reviewCommit: payload.commit,
    apiBaseUrl: payload.api,
    healthCheckUrl: payload.health,
    deploymentProofUrl: proofUrl,
    generatedBy: `xagt-plugin@${cliVersion}`
  }, null, 2)}\n`;
}

export function renderRightsDeclaration(payload: SubmitPayload): string {
  return `# Submission rights declaration

Project: ${payload.name}
Submission slug: ${payload.slug}
Submitter: _Legal person or entity_
Date: _YYYY-MM-DD_

The submitter confirms that they own, or have sufficient authorization for, the source code, dependencies, service, data, branding, and other materials submitted in this pull request.

Subject to the official program terms, the submitter authorizes X-Agent to retain, reproduce, audit, test, archive, and publish the submitted program artifact for judging, fraud prevention, dispute handling, ecosystem submission, and post-award accountability. Closing the pull request, deleting a fork, or deleting an external repository does not revoke the official archive rights attached to an accepted and rewarded entry.

Third-party components and their licenses: _List or link_
Exceptions or restrictions: _None or explain_

This declaration must be completed before review. It is not a substitute for event terms reviewed by qualified counsel.
`;
}
