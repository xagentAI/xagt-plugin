const FIXTURE_HOST = "evidence.example.test";

const FIXTURES = new Map([
  [
    "https://evidence.example.test/ev-smoke.txt",
    "FIXTURE_SCORE: 100\nThe production smoke test passed twice.",
  ],
  [
    "https://evidence.example.test/ev-docs.txt",
    "FIXTURE_SCORE: 90\nThe documented call reproduced with one minor wording ambiguity.",
  ],
  [
    "https://evidence.example.test/ev-errors.txt",
    "FIXTURE_SCORE: 75\nMalformed requests fail safely; one optional boundary case is absent.",
  ],
]);

export const fixtureEvidenceAllowHosts = [FIXTURE_HOST];

export async function fixtureEvidenceResolver() {
  return [{ address: "93.184.216.34", family: 4 }];
}

export async function fixtureEvidenceFetcher(url) {
  const content = FIXTURES.get(url.toString());
  return new Response(content ?? "Not found", {
    status: content === undefined ? 404 : 200,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}

export function fixtureEvidenceContent(uri) {
  return FIXTURES.get(uri) ?? null;
}
