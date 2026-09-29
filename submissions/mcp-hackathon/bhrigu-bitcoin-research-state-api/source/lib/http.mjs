export function sendJson(res, status, payload, cache = "no-store") {
  res.statusCode = status;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.setHeader("cache-control", cache);
  res.setHeader("access-control-allow-origin", "*");
  res.setHeader("x-content-type-options", "nosniff");
  res.end(JSON.stringify(payload));
}

export function methodGate(req, res) {
  if (req.method === "GET") return true;
  sendJson(res, 405, { error: "METHOD_NOT_ALLOWED", allowed: ["GET"] });
  return false;
}
