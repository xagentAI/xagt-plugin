export const LIMITS = Object.freeze({
  bodyBytes: 32768, rows: 100, fields: 20, nameChars: 64,
  cellChars: 2048, outputBytes: 65536, errorDetails: 40,
});

const forbiddenNames = new Set(['__proto__', 'prototype', 'constructor']);
const types = new Set(['string', 'integer', 'number', 'boolean']);
const encoder = new TextEncoder();
const has = (object, key) => Object.hasOwn(object, key);
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const validName = value => typeof value === 'string' && value.length > 0 &&
  value.length <= LIMITS.nameChars && !forbiddenNames.has(value);

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function fail(status, code, message, details) {
  throw new ApiError(status, code, message, details);
}

function validateSchema(schema) {
  if (!Array.isArray(schema) || schema.length < 1 || schema.length > LIMITS.fields) {
    fail(400, 'INVALID_SCHEMA', 'schema must contain between 1 and 20 field mappings.');
  }
  const targets = new Set();
  const allowed = new Set(['source', 'target', 'type', 'required', 'nullable', 'trim']);
  return schema.map((field, index) => {
    if (!record(field) || Object.keys(field).some(key => !allowed.has(key)) ||
      !validName(field.source) || !validName(field.target) || !types.has(field.type) ||
      ['required', 'nullable', 'trim'].some(key => has(field, key) && typeof field[key] !== 'boolean')) {
      fail(400, 'INVALID_SCHEMA', 'Invalid field mapping or unsupported option.', [{ schemaIndex: index }]);
    }
    if (targets.has(field.target)) fail(400, 'DUPLICATE_TARGET', 'Schema targets must be unique.', [{ schemaIndex: index }]);
    targets.add(field.target);
    return { required: true, nullable: false, trim: false, ...field };
  });
}

function parseCsv(text) {
  if (typeof text !== 'string' || text.length === 0) fail(400, 'INVALID_CSV', 'CSV must be a non-empty string with a header.');
  if (text.startsWith('\uFEFF')) text = text.slice(1);
  if (!text.length) fail(400, 'INVALID_CSV', 'CSV must include a header.');
  const table = [];
  let row = [], field = '', mode = 'start', endedOnRow = false;
  const cell = () => {
    row.push(field);
    field = '';
    mode = 'start';
    if (row.length > LIMITS.fields) fail(413, 'FIELD_LIMIT', 'CSV exceeds 20 columns.');
  };
  const line = () => {
    cell();
    table.push(row);
    row = [];
    if (table.length > LIMITS.rows + 1) fail(413, 'ROW_LIMIT', 'Input exceeds 100 records.');
  };
  const append = character => {
    field += character;
    if (field.length > LIMITS.cellChars) fail(413, 'CELL_LIMIT', 'A cell exceeds 2048 UTF-16 code units.');
  };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    endedOnRow = false;
    if (mode === 'quoted') {
      if (ch === '"') {
        if (text[i + 1] === '"') { append('"'); i++; }
        else mode = 'afterQuote';
      } else append(ch);
      continue;
    }
    if (ch === ',') { cell(); continue; }
    if (ch === '\n' || ch === '\r') {
      if (ch === '\r') {
        if (text[i + 1] !== '\n') fail(400, 'INVALID_CSV', 'Outside quoted cells, use LF or CRLF line endings.');
        i++;
      }
      line();
      endedOnRow = true;
      continue;
    }
    if (mode === 'afterQuote') fail(400, 'INVALID_CSV', 'Unexpected character after a closing quote.');
    if (ch === '"') {
      if (mode !== 'start') fail(400, 'INVALID_CSV', 'Quotes must start at the beginning of a cell.');
      mode = 'quoted';
    } else { append(ch); mode = 'plain'; }
  }
  if (mode === 'quoted') fail(400, 'INVALID_CSV', 'Unterminated quoted cell.');
  if (!endedOnRow) line();
  const headers = table.shift();
  if (!headers.every(validName) || new Set(headers).size !== headers.length) {
    fail(400, 'INVALID_CSV_HEADER', 'Headers must be non-empty, unique, safe names of at most 64 code units.');
  }
  return table.map((values, index) => {
    if (values.length !== headers.length) fail(400, 'CSV_COLUMN_COUNT', 'CSV record width differs from the header.', [{ row: index }]);
    const output = Object.create(null);
    headers.forEach((name, column) => { output[name] = values[column]; });
    return output;
  });
}

function convert(value, type) {
  if (type === 'string') {
    if (['string', 'number', 'boolean'].includes(typeof value)) return String(value);
  } else if (type === 'boolean') {
    if (typeof value === 'boolean') return value;
    if (value === 'true' || value === 'false') return value === 'true';
  } else if (type === 'integer') {
    if (typeof value === 'number' && Number.isSafeInteger(value)) return value;
    if (typeof value === 'string' && /^-?(?:0|[1-9]\d*)$/.test(value)) {
      const result = Number(value);
      if (Number.isSafeInteger(result)) return result;
    }
  } else if (type === 'number') {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(value)) {
      const result = Number(value);
      if (Number.isFinite(result)) return result;
    }
  }
  return undefined;
}

export function transform(payload) {
  if (!record(payload) || Object.keys(payload).some(key => !['format', 'data', 'schema'].includes(key)) ||
    !has(payload, 'data') || !['json', 'csv'].includes(payload.format)) {
    fail(400, 'INVALID_REQUEST', 'Use only format, data and schema; format must be json or csv.');
  }
  const schema = validateSchema(payload.schema);
  const input = payload.format === 'csv' ? parseCsv(payload.data) : payload.data;
  if (!Array.isArray(input)) fail(400, 'INVALID_DATA', 'JSON data must be an array of flat records.');
  if (input.length > LIMITS.rows) fail(413, 'ROW_LIMIT', 'Input exceeds 100 records.');
  const data = [];
  const details = [];
  let totalErrors = 0, convertedCells = 0, dataBytes = 2;
  const issue = detail => {
    totalErrors++;
    if (details.length < LIMITS.errorDetails) details.push(detail);
  };
  input.forEach((row, index) => {
    if (!record(row)) fail(400, 'INVALID_ROW', 'Each input record must be a flat object.', [{ row: index }]);
    const keys = Object.keys(row);
    if (keys.length > LIMITS.fields) fail(413, 'FIELD_LIMIT', 'An input record exceeds 20 fields.', [{ row: index }]);
    for (const key of keys) {
      if (!validName(key)) fail(400, 'INVALID_FIELD_NAME', 'Input field name is invalid.', [{ row: index }]);
      const value = row[key];
      if (value !== null && !['string', 'number', 'boolean'].includes(typeof value)) {
        fail(400, 'NESTED_VALUE', 'Input cells must be strings, finite numbers, booleans or null.', [{ row: index, source: key }]);
      }
      if (typeof value === 'number' && !Number.isFinite(value)) fail(400, 'NONFINITE_NUMBER', 'Input numbers must be finite.', [{ row: index, source: key }]);
      if (typeof value === 'string' && value.length > LIMITS.cellChars) fail(413, 'CELL_LIMIT', 'A cell exceeds 2048 UTF-16 code units.', [{ row: index, source: key }]);
    }
    const output = Object.create(null);
    for (const field of schema) {
      const location = { row: index, source: field.source, target: field.target, expected: field.type };
      if (!has(row, field.source)) {
        if (field.required) issue({ ...location, code: 'MISSING_FIELD' });
        continue;
      }
      const original = row[field.source];
      if (original === null) {
        if (field.nullable) output[field.target] = null;
        else issue({ ...location, code: 'NULL_NOT_ALLOWED' });
        continue;
      }
      const value = field.trim && typeof original === 'string' ? original.trim() : original;
      const result = convert(value, field.type);
      if (result === undefined) issue({ ...location, code: 'TYPE_MISMATCH' });
      else {
        output[field.target] = result;
        if (!Object.is(original, result)) convertedCells++;
      }
    }
    dataBytes += encoder.encode(JSON.stringify(output)).byteLength + (index > 0 ? 1 : 0);
    // Leave fixed headroom for the success envelope; final response is checked again.
    if (dataBytes > LIMITS.outputBytes - 256) fail(413, 'OUTPUT_LIMIT', 'Transformed output exceeds the response budget.');
    data.push(output);
  });
  if (totalErrors) {
    fail(422, 'VALIDATION_FAILED', 'Some fields could not be converted. No records were returned.', {
      totalErrors, truncated: totalErrors > details.length, fields: details,
    });
  }
  return { ok: true, data, summary: { inputRows: input.length, outputRows: data.length, mappedFields: schema.length, convertedCells } };
}
