import { methodGate, sendJson } from "../lib/http.mjs";
import { getWindow } from "../lib/windows.mjs";

export default function handler(req, res) {
  if (!methodGate(req, res)) return;
  const url = new URL(req.url || "/", "http://localhost");
  const id = String(url.searchParams.get("id") || "");
  const record = getWindow(id, new Date());
  if (!record) return sendJson(res, 404, { error: "WINDOW_NOT_FOUND", supported: ["SEP_10_2026", "SEP_17_2026"] });
  sendJson(res, 200, record, "public, max-age=30");
}
