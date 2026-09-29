/**
 * The tool surface, described the way a caller needs it: what goes in, what
 * comes back, how it fails, what it will not do, and what it costs to call.
 * Served at /v1/tools.json so the description and the implementation ship
 * together and cannot drift apart in separate documents.
 */
export const TOOLS = {
  schemaVersion: 1,
  service: "sumplus-model-desk",
  description:
    "Prices one job against every offer in a live model catalogue and returns the offers that can actually take it.",
  authentication: "None. Every tool is public and read-only.",
  sideEffects:
    "None. No credentials are held, nothing is written, no upstream call is billed to the caller.",
  transports: {
    rest: "Each tool has its own path under /v1, listed with the tool below.",
    jsonRpc: {
      path: "POST /mcp",
      protocol: "JSON-RPC 2.0",
      methods: ["initialize", "tools/list", "tools/call", "ping"],
      toolListSource:
        "tools/list is generated from this document, so the two cannot describe different tools.",
      dispatch:
        "tools/call runs the same operation as the matching REST route, so both doors return the same answer.",
      errors:
        "A malformed request comes back as a JSON-RPC error object. A tool that refuses comes back as a result carrying isError with the refusal inside, because the request was well formed and the refusal is the answer.",
      batching: "A batch of requests is answered with a batch. A notification is answered with nothing.",
    },
  },
  limits: {
    requestsPerMinutePerAddress: 60,
    maxRowsPerResponse: 50,
    maxTokensPerField: 2_000_000,
    catalogueRefreshSeconds: 300,
  },
  notes: {
    zeroPrices:
      "Some offers are listed at zero in the catalogue. Rows carrying listedAtZero report the catalogue's figure and nothing more.",
    notTokenPriced:
      "The catalogue also carries video and image models, which have no context window or output ceiling. A job measured in tokens cannot be placed on one, and they are refused by name rather than dropped.",
    preview:
      "Offers marked preview are excluded by default and reported as refused on availability. Pass includePreview to consider them.",
  },
  vocabulary: {
    offer:
      "One model id served on one line at that line's price. The unit everything here is grouped by.",
    modelId:
      "The name of a model. It is NOT a price: 16 of the 72 ids in this catalogue are sold on more than one line, at up to 15 times the price.",
    line: "The route an offer is served over. Different lines carry different prices for the same id.",
    staleSeconds:
      "How long ago the served catalogue was read from upstream. It travels with every answer.",
  },
  tools: [
    {
      name: "plan_call",
      transport: { method: "POST", path: "/v1/plan_call" },
      purpose:
        "Given one job, return every offer that can take it, priced and sorted, and every offer that cannot, with the reason.",
      input: {
        inputTokens: { type: "integer", required: true, min: 0, max: 2_000_000 },
        outputTokens: { type: "integer", required: true, min: 0, max: 2_000_000 },
        minContext: { type: "integer", required: false, note: "A floor on the context window." },
        minMaxOutput: { type: "integer", required: false, note: "A floor on the output ceiling." },
        requireLines: { type: "string[]", required: false },
        excludeLines: { type: "string[]", required: false },
        baselineModelId: {
          type: "string",
          required: false,
          note: "The id you were going to use. The answer then carries what you save against it.",
        },
        includePreview: {
          type: "boolean",
          required: false,
          default: false,
          note: "Offers marked preview rather than live are left out unless this is true.",
        },
        limit: { type: "integer", required: false, default: 50, max: 50 },
      },
      output: {
        eligible:
          "Offers that can take the job, cheapest first: modelId, line, lineCode, inputCost, outputCost, totalCost, context, maxOutput, availability.",
        rejected:
          "Offers that cannot, each with reason, bindingConstraint, requiredValue, actualValue. bindingConstraint is one of context, max_output, min_context, min_max_output, line, availability, not_token_priced.",
        listedAtZero:
          "Set on a row the catalogue prices at zero. It reports what the catalogue says and makes no claim that the call is free: a zero price and an unfilled price are the same value in that field.",
        truncated:
          "True when rows were cut by limit. eligibleCount is always the real total.",
        savingsVsBaseline:
          "Present when baselineModelId was given. Carries baselineIneligible when the id you had in mind cannot take this job.",
        snapshotId: "Content address of the catalogue these numbers came from.",
        pricedAt: "When that catalogue was read.",
        staleSeconds: "How old it is.",
      },
      errors: [
        { code: "invalid_token_counts", http: 422, when: "A token count is negative, fractional, or above 2,000,000." },
        { code: "unknown_model", http: 404, when: "baselineModelId is not in the catalogue. Carries closestIds." },
        { code: "no_offer_meets_requirements", http: 422, when: "Nothing can take the job. Carries rejected[] and what to relax, with numbers." },
        { code: "catalogue_unavailable", http: 503, when: "No catalogue has been read yet. Carries the last attempt and error." },
        { code: "rate_limited", http: 429, when: "Over 60 requests in a minute from one address." },
      ],
      rounding:
        "Costs round up, savings round down. A displayed figure is never below what would actually be charged.",
    },
    {
      name: "quote",
      transport: { method: "POST", path: "/v1/quote" },
      purpose: "Price one job on one named id, across every line that carries it.",
      input: {
        modelId: { type: "string", required: true },
        line: { type: "string", required: false, note: "Omit to see every line carrying this id." },
        inputTokens: { type: "integer", required: true },
        outputTokens: { type: "integer", required: true },
        cachedInputTokens: { type: "integer", required: false, note: "Priced at the cache-hit rate where a line publishes one." },
      },
      output: "quotes[], cheapest first, each with input, output, cached and total cost.",
      errors: [
        { code: "unknown_model", http: 404, when: "The id, or the id on that line, is not in the catalogue." },
        { code: "invalid_token_counts", http: 422, when: "As above." },
      ],
    },
    {
      name: "resolve",
      transport: { method: "GET", path: "/v1/resolve?modelId=<id>" },
      purpose:
        "Show every offer carrying one id, with the price spread between them. This is the tool that demonstrates an id is not a price.",
      input: {
        modelId: { type: "string", required: true, note: "Passed in the query string." },
      },
      output: "offers[] sorted by input price, plus spread as a multiple.",
      errors: [{ code: "unknown_model", http: 404, when: "No offer carries that id. Carries closestIds." }],
    },
    {
      name: "catalogue",
      transport: { method: "GET", path: "/v1/catalogue?line=&minContext=&limit=" },
      purpose: "Read the catalogue this desk is pricing against.",
      input: {
        line: { type: "string", required: false, note: "Only offers served on this line." },
        minContext: { type: "integer", required: false, note: "Only offers whose window is at least this size." },
        limit: { type: "integer", required: false, default: 50, max: 50 },
      },
      output: "offers[], totalOffers, uniqueModelIds, snapshotId, pricedAt, staleSeconds.",
      errors: [
        { code: "catalogue_unavailable", http: 503, when: "No catalogue has been read yet." },
        { code: "rate_limited", http: 429, when: "Over 60 requests in a minute from one address." },
      ],
    },
    {
      name: "catalogue_diff",
      transport: { method: "GET", path: "/v1/catalogue/diff" },
      purpose:
        "Compare today's catalogue with the one committed alongside this build, so a reviewer can see what moved since submission.",
      input: {},
      output: "added, removed, repriced, rewindowed, and counts.",
      errors: [
        { code: "catalogue_unavailable", http: 503, when: "No catalogue has been read yet." },
        { code: "rate_limited", http: 429, when: "Over 60 requests in a minute from one address." },
      ],
      honesty:
        "This shows the upstream catalogue is live and changing. It does not independently confirm any price is correct: both readings come from the same source.",
    },
  ],
  provenance: {
    catalogue: "https://router.sumplus.xyz/v1/models",
    howItIsRead:
      "This desk reads the catalogue on its own schedule and serves a cached copy, so reviewer traffic never reaches the upstream gateway and an upstream wobble does not take this service down.",
    gatewayAttestation: {
      what:
        "The gateway that publishes the catalogue runs in an AMD SEV-SNP confidential machine and posts its own build measurement to the Sigstore Rekor public transparency log.",
      boundary:
        "That attestation covers the gateway's build and its internal model configuration. The digest in it is NOT recomputable from the public catalogue, so it is background on where these prices come from and not a proof that any published price is correct.",
    },
  },
  scope:
    "Procurement and pricing for model calls. This service does not inspect wallets, transactions, contracts, or security posture.",
} as const;
