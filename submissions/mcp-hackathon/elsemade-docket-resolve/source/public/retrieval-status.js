export function retrievalMessage({ items = [], errors = [] } = {}) {
  if (errors.length === 0) return "Evidence retrieved and digest-verified.";
  if (items.length === 0) return "No evidence was retrieved. Review the failures.";
  return "Evidence was partially retrieved. Review the failures.";
}

export function retrievalTone({ errors = [] } = {}) {
  return errors.length > 0 ? "error" : "";
}
