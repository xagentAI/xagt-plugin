import { methodGate, sendJson } from "../lib/http.mjs";
import { listWindows, temporalSummary } from "../lib/windows.mjs";

export default function handler(req, res) {
  if (!methodGate(req, res)) return;
  const now = new Date();
  sendJson(res, 200, { ...temporalSummary(now), windows: listWindows(now) }, "public, max-age=30");
}
