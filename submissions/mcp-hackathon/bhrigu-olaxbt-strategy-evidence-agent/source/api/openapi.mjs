import { methodGate, sendJson } from "../lib/http.mjs";
import { openapiPayload } from "../lib/openapi.mjs";

export default function handler(req, res) {
  if (!methodGate(req, res)) return;
  sendJson(res, 200, openapiPayload(), "public, max-age=300");
}
