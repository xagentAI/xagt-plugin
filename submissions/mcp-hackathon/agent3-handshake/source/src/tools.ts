/**
 * Tool declarations. This is the single source of truth for the tool set:
 * the MCP door lists these, the REST door routes from these, and the shipped
 * tools.json is generated from these rather than written by hand.
 */

export interface ToolSpec {
  name: string;
  title: string;
  description: string;
  /** Property name -> description. Empty object means the tool takes no input. */
  input: Record<string, { type: string; required: boolean; description: string }>;
  errors: string[];
  restPath: string;
  restMethod: "GET" | "POST";
}

export const TOOLS: ToolSpec[] = [
  {
    name: "registry_audit",
    title: "Audit every entry for callability",
    description:
      "Walks the whole Agent3 registry and reports, per entry, whether a caller can construct a request from what is published — and when not, which field is missing or unusable. Takes no input.",
    input: {},
    errors: [
      "upstream_unavailable: the registry could not be read; the response says so instead of returning a partial audit",
    ],
    restPath: "/v1/audit",
    restMethod: "GET",
  },
  {
    name: "entry_describe",
    title: "Describe one entry, normalized",
    description:
      "Everything the registry publishes about one entry, with the payment field resolved across both spellings and the operation list flattened to id, method and path.",
    input: {
      entry: {
        type: "string",
        required: true,
        description: "resource id or exact entry name",
      },
    },
    errors: [
      "entry_not_found: no entry matches; the response lists the ids that do exist",
      "upstream_unavailable: the registry could not be read",
    ],
    restPath: "/v1/entry",
    restMethod: "GET",
  },
  {
    name: "call_plan",
    title: "Build the request, or name what blocks it",
    description:
      "Turns one entry plus one operation into the exact request to send: absolute URL, method, headers, the published body schema and its required fields, and whether payment is required. When the entry does not support a call, it refuses and names every blocking field rather than guessing a value.",
    input: {
      entry: { type: "string", required: true, description: "resource id or exact entry name" },
      operation: { type: "string", required: true, description: "operation id as published" },
    },
    errors: [
      "entry_not_found: no entry matches; the response lists the ids that do exist",
      "not_callable: the entry was found but publishes no usable call; every blocker is named with its field",
      "upstream_unavailable: the registry could not be read",
    ],
    restPath: "/v1/plan",
    restMethod: "GET",
  },
  {
    name: "payment_readings",
    title: "Read the payment field both ways",
    description:
      "The registry states the payment kind under two different keys. This reports, per entry, what a reader of each key alone would see, and how many entries each reader silently misses.",
    input: {},
    errors: ["upstream_unavailable: the registry could not be read"],
    restPath: "/v1/payments",
    restMethod: "GET",
  },
  {
    name: "registry_snapshot",
    title: "Pin what was read",
    description:
      "Source URL, read time, entry count, entry ids and a sha256 digest over the canonical payload, so a reviewer can pin an answer to the exact registry state it came from.",
    input: {},
    errors: ["upstream_unavailable: the registry could not be read"],
    restPath: "/v1/snapshot",
    restMethod: "GET",
  },
];

export function toolByName(name: string): ToolSpec | undefined {
  return TOOLS.find((tool) => tool.name === name);
}

/** JSON Schema for one tool's input, derived from the declaration above. */
export function inputSchema(tool: ToolSpec) {
  const properties: Record<string, { type: string; description: string }> = {};
  const required: string[] = [];
  for (const [key, spec] of Object.entries(tool.input)) {
    properties[key] = { type: spec.type, description: spec.description };
    if (spec.required) required.push(key);
  }
  return { type: "object", properties, required, additionalProperties: false };
}
