import { verificationPayload } from "../lib/runtime.mjs";
import { methodGate, sendJson } from "../lib/http.mjs";

export default function handler(req, res) {
  if (!methodGate(req, res)) return;
  sendJson(res, 200, verificationPayload(), "public, max-age=30");
}
