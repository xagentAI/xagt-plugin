/**
 * Generates tools.json from src/tools.ts, so the shipped file cannot drift
 * from the tool set the server actually serves. Never edit tools.json by hand.
 */
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { TOOLS, inputSchema } from "../src/tools.js";

const here = dirname(fileURLToPath(import.meta.url));
const doc = {
  generatedFrom: "src/tools.ts",
  tools: TOOLS.map((tool) => ({
    name: tool.name,
    title: tool.title,
    description: tool.description,
    input: inputSchema(tool),
    errors: tool.errors,
    rest: { method: tool.restMethod, path: tool.restPath },
  })),
};
writeFileSync(join(here, "..", "tools.json"), `${JSON.stringify(doc, null, 2)}\n`);
process.stdout.write(`wrote ${doc.tools.length} tools\n`);
