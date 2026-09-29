(() => {
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __esm = (fn, res, err) => function __init() {
    if (err) throw err[0];
    try {
      return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
    } catch (e) {
      throw err = [e], e;
    }
  };
  var __commonJS = (cb, mod) => function __require() {
    try {
      return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
    } catch (e) {
      throw mod = 0, e;
    }
  };

  // node_modules/viem/_esm/utils/data/isHex.js
  function isHex(value, { strict = true } = {}) {
    if (!value)
      return false;
    if (typeof value !== "string")
      return false;
    return strict ? /^0x[0-9a-fA-F]*$/.test(value) : value.startsWith("0x");
  }
  var init_isHex = __esm({
    "node_modules/viem/_esm/utils/data/isHex.js"() {
    }
  });

  // node_modules/viem/_esm/utils/data/size.js
  function size(value) {
    if (isHex(value, { strict: false }))
      return Math.ceil((value.length - 2) / 2);
    return value.length;
  }
  var init_size = __esm({
    "node_modules/viem/_esm/utils/data/size.js"() {
      init_isHex();
    }
  });

  // node_modules/viem/_esm/errors/version.js
  var version;
  var init_version = __esm({
    "node_modules/viem/_esm/errors/version.js"() {
      version = "2.55.19";
    }
  });

  // node_modules/viem/_esm/errors/base.js
  function walk(err, fn) {
    if (fn?.(err))
      return err;
    if (err && typeof err === "object" && "cause" in err && err.cause !== void 0)
      return walk(err.cause, fn);
    return fn ? null : err;
  }
  var errorConfig, BaseError;
  var init_base = __esm({
    "node_modules/viem/_esm/errors/base.js"() {
      init_version();
      errorConfig = {
        getDocsUrl: ({ docsBaseUrl, docsPath = "", docsSlug }) => docsPath ? `${docsBaseUrl ?? "https://viem.sh"}${docsPath}${docsSlug ? `#${docsSlug}` : ""}` : void 0,
        version: `viem@${version}`
      };
      BaseError = class _BaseError extends Error {
        constructor(shortMessage, args = {}) {
          const details = (() => {
            if (args.cause instanceof _BaseError)
              return args.cause.details;
            if (args.cause?.message)
              return args.cause.message;
            return args.details;
          })();
          const docsPath = (() => {
            if (args.cause instanceof _BaseError)
              return args.cause.docsPath || args.docsPath;
            return args.docsPath;
          })();
          const docsUrl = errorConfig.getDocsUrl?.({ ...args, docsPath });
          const message = [
            shortMessage || "An error occurred.",
            "",
            ...args.metaMessages ? [...args.metaMessages, ""] : [],
            ...docsUrl ? [`Docs: ${docsUrl}`] : [],
            ...details ? [`Details: ${details}`] : [],
            ...errorConfig.version ? [`Version: ${errorConfig.version}`] : []
          ].join("\n");
          super(message, args.cause ? { cause: args.cause } : void 0);
          Object.defineProperty(this, "details", {
            enumerable: true,
            configurable: true,
            writable: true,
            value: void 0
          });
          Object.defineProperty(this, "docsPath", {
            enumerable: true,
            configurable: true,
            writable: true,
            value: void 0
          });
          Object.defineProperty(this, "metaMessages", {
            enumerable: true,
            configurable: true,
            writable: true,
            value: void 0
          });
          Object.defineProperty(this, "shortMessage", {
            enumerable: true,
            configurable: true,
            writable: true,
            value: void 0
          });
          Object.defineProperty(this, "version", {
            enumerable: true,
            configurable: true,
            writable: true,
            value: void 0
          });
          Object.defineProperty(this, "name", {
            enumerable: true,
            configurable: true,
            writable: true,
            value: "BaseError"
          });
          this.details = details;
          this.docsPath = docsPath;
          this.metaMessages = args.metaMessages;
          this.name = args.name ?? this.name;
          this.shortMessage = shortMessage;
          this.version = version;
        }
        walk(fn) {
          return walk(this, fn);
        }
      };
    }
  });

  // node_modules/viem/_esm/errors/abi.js
  var AbiEncodingArrayLengthMismatchError, AbiEncodingBytesSizeMismatchError, AbiEncodingLengthMismatchError, InvalidAbiEncodingTypeError, InvalidArrayError;
  var init_abi = __esm({
    "node_modules/viem/_esm/errors/abi.js"() {
      init_size();
      init_base();
      AbiEncodingArrayLengthMismatchError = class extends BaseError {
        constructor({ expectedLength, givenLength, type }) {
          super([
            `ABI encoding array length mismatch for type ${type}.`,
            `Expected length: ${expectedLength}`,
            `Given length: ${givenLength}`
          ].join("\n"), { name: "AbiEncodingArrayLengthMismatchError" });
        }
      };
      AbiEncodingBytesSizeMismatchError = class extends BaseError {
        constructor({ expectedSize, value }) {
          super(`Size of bytes "${value}" (bytes${size(value)}) does not match expected size (bytes${expectedSize}).`, { name: "AbiEncodingBytesSizeMismatchError" });
        }
      };
      AbiEncodingLengthMismatchError = class extends BaseError {
        constructor({ expectedLength, givenLength }) {
          super([
            "ABI encoding params/values length mismatch.",
            `Expected length (params): ${expectedLength}`,
            `Given length (values): ${givenLength}`
          ].join("\n"), { name: "AbiEncodingLengthMismatchError" });
        }
      };
      InvalidAbiEncodingTypeError = class extends BaseError {
        constructor(type, { docsPath }) {
          super([
            `Type "${type}" is not a valid encoding type.`,
            "Please provide a valid ABI type."
          ].join("\n"), { docsPath, name: "InvalidAbiEncodingType" });
        }
      };
      InvalidArrayError = class extends BaseError {
        constructor(value) {
          super([`Value "${value}" is not a valid array.`].join("\n"), {
            name: "InvalidArrayError"
          });
        }
      };
    }
  });

  // node_modules/viem/_esm/errors/data.js
  var SliceOffsetOutOfBoundsError, SizeExceedsPaddingSizeError;
  var init_data = __esm({
    "node_modules/viem/_esm/errors/data.js"() {
      init_base();
      SliceOffsetOutOfBoundsError = class extends BaseError {
        constructor({ offset, position, size: size2 }) {
          super(`Slice ${position === "start" ? "starting" : "ending"} at offset "${offset}" is out-of-bounds (size: ${size2}).`, { name: "SliceOffsetOutOfBoundsError" });
        }
      };
      SizeExceedsPaddingSizeError = class extends BaseError {
        constructor({ size: size2, targetSize, type }) {
          super(`${type.charAt(0).toUpperCase()}${type.slice(1).toLowerCase()} size (${size2}) exceeds padding size (${targetSize}).`, { name: "SizeExceedsPaddingSizeError" });
        }
      };
    }
  });

  // node_modules/viem/_esm/utils/data/pad.js
  function pad(hexOrBytes, { dir, size: size2 = 32 } = {}) {
    if (typeof hexOrBytes === "string")
      return padHex(hexOrBytes, { dir, size: size2 });
    return padBytes(hexOrBytes, { dir, size: size2 });
  }
  function padHex(hex_, { dir, size: size2 = 32 } = {}) {
    if (size2 === null)
      return hex_;
    const hex = hex_.replace("0x", "");
    if (hex.length > size2 * 2)
      throw new SizeExceedsPaddingSizeError({
        size: Math.ceil(hex.length / 2),
        targetSize: size2,
        type: "hex"
      });
    return `0x${hex[dir === "right" ? "padEnd" : "padStart"](size2 * 2, "0")}`;
  }
  function padBytes(bytes, { dir, size: size2 = 32 } = {}) {
    if (size2 === null)
      return bytes;
    if (bytes.length > size2)
      throw new SizeExceedsPaddingSizeError({
        size: bytes.length,
        targetSize: size2,
        type: "bytes"
      });
    const paddedBytes = new Uint8Array(size2);
    for (let i = 0; i < size2; i++) {
      const padEnd = dir === "right";
      paddedBytes[padEnd ? i : size2 - i - 1] = bytes[padEnd ? i : bytes.length - i - 1];
    }
    return paddedBytes;
  }
  var init_pad = __esm({
    "node_modules/viem/_esm/utils/data/pad.js"() {
      init_data();
    }
  });

  // node_modules/viem/_esm/errors/encoding.js
  var IntegerOutOfRangeError, SizeOverflowError;
  var init_encoding = __esm({
    "node_modules/viem/_esm/errors/encoding.js"() {
      init_base();
      IntegerOutOfRangeError = class extends BaseError {
        constructor({ max, min, signed, size: size2, value }) {
          super(`Number "${value}" is not in safe ${size2 ? `${size2 * 8}-bit ${signed ? "signed" : "unsigned"} ` : ""}integer range ${max ? `(${min} to ${max})` : `(above ${min})`}`, { name: "IntegerOutOfRangeError" });
        }
      };
      SizeOverflowError = class extends BaseError {
        constructor({ givenSize, maxSize }) {
          super(`Size cannot exceed ${maxSize} bytes. Given size: ${givenSize} bytes.`, { name: "SizeOverflowError" });
        }
      };
    }
  });

  // node_modules/viem/_esm/utils/encoding/fromHex.js
  function assertSize(hexOrBytes, { size: size2 }) {
    if (size(hexOrBytes) > size2)
      throw new SizeOverflowError({
        givenSize: size(hexOrBytes),
        maxSize: size2
      });
  }
  var init_fromHex = __esm({
    "node_modules/viem/_esm/utils/encoding/fromHex.js"() {
      init_encoding();
      init_size();
    }
  });

  // node_modules/viem/_esm/utils/encoding/toHex.js
  function toHex(value, opts = {}) {
    if (typeof value === "number" || typeof value === "bigint")
      return numberToHex(value, opts);
    if (typeof value === "string") {
      return stringToHex(value, opts);
    }
    if (typeof value === "boolean")
      return boolToHex(value, opts);
    return bytesToHex(value, opts);
  }
  function boolToHex(value, opts = {}) {
    const hex = `0x${Number(value)}`;
    if (typeof opts.size === "number") {
      assertSize(hex, { size: opts.size });
      return pad(hex, { size: opts.size });
    }
    return hex;
  }
  function bytesToHex(value, opts = {}) {
    let string = "";
    for (let i = 0; i < value.length; i++) {
      string += hexes[value[i]];
    }
    const hex = `0x${string}`;
    if (typeof opts.size === "number") {
      assertSize(hex, { size: opts.size });
      return pad(hex, { dir: "right", size: opts.size });
    }
    return hex;
  }
  function numberToHex(value_, opts = {}) {
    const { signed, size: size2 } = opts;
    const value = BigInt(value_);
    let maxValue;
    if (size2) {
      if (signed)
        maxValue = (1n << BigInt(size2) * 8n - 1n) - 1n;
      else
        maxValue = 2n ** (BigInt(size2) * 8n) - 1n;
    } else if (typeof value_ === "number") {
      maxValue = BigInt(Number.MAX_SAFE_INTEGER);
    }
    const minValue = typeof maxValue === "bigint" && signed ? -maxValue - 1n : 0;
    if (maxValue && value > maxValue || value < minValue) {
      const suffix = typeof value_ === "bigint" ? "n" : "";
      throw new IntegerOutOfRangeError({
        max: maxValue ? `${maxValue}${suffix}` : void 0,
        min: `${minValue}${suffix}`,
        signed,
        size: size2,
        value: `${value_}${suffix}`
      });
    }
    const hex = `0x${(signed && value < 0 ? (1n << BigInt(size2 * 8)) + BigInt(value) : value).toString(16)}`;
    if (size2)
      return pad(hex, { size: size2 });
    return hex;
  }
  function stringToHex(value_, opts = {}) {
    const value = encoder.encode(value_);
    return bytesToHex(value, opts);
  }
  var hexes, encoder;
  var init_toHex = __esm({
    "node_modules/viem/_esm/utils/encoding/toHex.js"() {
      init_encoding();
      init_pad();
      init_fromHex();
      hexes = /* @__PURE__ */ Array.from({ length: 256 }, (_v, i) => i.toString(16).padStart(2, "0"));
      encoder = /* @__PURE__ */ new TextEncoder();
    }
  });

  // node_modules/viem/_esm/utils/encoding/toBytes.js
  function toBytes(value, opts = {}) {
    if (typeof value === "number" || typeof value === "bigint")
      return numberToBytes(value, opts);
    if (typeof value === "boolean")
      return boolToBytes(value, opts);
    if (isHex(value))
      return hexToBytes(value, opts);
    return stringToBytes(value, opts);
  }
  function boolToBytes(value, opts = {}) {
    const bytes = new Uint8Array(1);
    bytes[0] = Number(value);
    if (typeof opts.size === "number") {
      assertSize(bytes, { size: opts.size });
      return pad(bytes, { size: opts.size });
    }
    return bytes;
  }
  function charCodeToBase16(char) {
    if (char >= charCodeMap.zero && char <= charCodeMap.nine)
      return char - charCodeMap.zero;
    if (char >= charCodeMap.A && char <= charCodeMap.F)
      return char - (charCodeMap.A - 10);
    if (char >= charCodeMap.a && char <= charCodeMap.f)
      return char - (charCodeMap.a - 10);
    return void 0;
  }
  function hexToBytes(hex_, opts = {}) {
    let hex = hex_;
    if (opts.size) {
      assertSize(hex, { size: opts.size });
      hex = pad(hex, { dir: "right", size: opts.size });
    }
    let hexString = hex.slice(2);
    if (hexString.length % 2)
      hexString = `0${hexString}`;
    const length = hexString.length / 2;
    const bytes = new Uint8Array(length);
    for (let index = 0, j = 0; index < length; index++) {
      const nibbleLeft = charCodeToBase16(hexString.charCodeAt(j++));
      const nibbleRight = charCodeToBase16(hexString.charCodeAt(j++));
      if (nibbleLeft === void 0 || nibbleRight === void 0) {
        throw new BaseError(`Invalid byte sequence ("${hexString[j - 2]}${hexString[j - 1]}" in "${hexString}").`);
      }
      bytes[index] = nibbleLeft * 16 + nibbleRight;
    }
    return bytes;
  }
  function numberToBytes(value, opts) {
    const hex = numberToHex(value, opts);
    return hexToBytes(hex);
  }
  function stringToBytes(value, opts = {}) {
    const bytes = encoder2.encode(value);
    if (typeof opts.size === "number") {
      assertSize(bytes, { size: opts.size });
      return pad(bytes, { dir: "right", size: opts.size });
    }
    return bytes;
  }
  var encoder2, charCodeMap;
  var init_toBytes = __esm({
    "node_modules/viem/_esm/utils/encoding/toBytes.js"() {
      init_base();
      init_isHex();
      init_pad();
      init_fromHex();
      init_toHex();
      encoder2 = /* @__PURE__ */ new TextEncoder();
      charCodeMap = {
        zero: 48,
        nine: 57,
        A: 65,
        F: 70,
        a: 97,
        f: 102
      };
    }
  });

  // node_modules/@noble/hashes/esm/_u64.js
  function fromBig(n, le = false) {
    if (le)
      return { h: Number(n & U32_MASK64), l: Number(n >> _32n & U32_MASK64) };
    return { h: Number(n >> _32n & U32_MASK64) | 0, l: Number(n & U32_MASK64) | 0 };
  }
  function split(lst, le = false) {
    const len = lst.length;
    let Ah = new Uint32Array(len);
    let Al = new Uint32Array(len);
    for (let i = 0; i < len; i++) {
      const { h, l } = fromBig(lst[i], le);
      [Ah[i], Al[i]] = [h, l];
    }
    return [Ah, Al];
  }
  var U32_MASK64, _32n, rotlSH, rotlSL, rotlBH, rotlBL;
  var init_u64 = __esm({
    "node_modules/@noble/hashes/esm/_u64.js"() {
      U32_MASK64 = /* @__PURE__ */ BigInt(2 ** 32 - 1);
      _32n = /* @__PURE__ */ BigInt(32);
      rotlSH = (h, l, s) => h << s | l >>> 32 - s;
      rotlSL = (h, l, s) => l << s | h >>> 32 - s;
      rotlBH = (h, l, s) => l << s - 32 | h >>> 64 - s;
      rotlBL = (h, l, s) => h << s - 32 | l >>> 64 - s;
    }
  });

  // node_modules/@noble/hashes/esm/utils.js
  function isBytes(a) {
    return a instanceof Uint8Array || ArrayBuffer.isView(a) && a.constructor.name === "Uint8Array";
  }
  function anumber(n) {
    if (!Number.isSafeInteger(n) || n < 0)
      throw new Error("positive integer expected, got " + n);
  }
  function abytes(b, ...lengths) {
    if (!isBytes(b))
      throw new Error("Uint8Array expected");
    if (lengths.length > 0 && !lengths.includes(b.length))
      throw new Error("Uint8Array expected of length " + lengths + ", got length=" + b.length);
  }
  function aexists(instance, checkFinished = true) {
    if (instance.destroyed)
      throw new Error("Hash instance has been destroyed");
    if (checkFinished && instance.finished)
      throw new Error("Hash#digest() has already been called");
  }
  function aoutput(out, instance) {
    abytes(out);
    const min = instance.outputLen;
    if (out.length < min) {
      throw new Error("digestInto() expects output buffer of length at least " + min);
    }
  }
  function u32(arr) {
    return new Uint32Array(arr.buffer, arr.byteOffset, Math.floor(arr.byteLength / 4));
  }
  function clean(...arrays) {
    for (let i = 0; i < arrays.length; i++) {
      arrays[i].fill(0);
    }
  }
  function byteSwap(word) {
    return word << 24 & 4278190080 | word << 8 & 16711680 | word >>> 8 & 65280 | word >>> 24 & 255;
  }
  function byteSwap32(arr) {
    for (let i = 0; i < arr.length; i++) {
      arr[i] = byteSwap(arr[i]);
    }
    return arr;
  }
  function utf8ToBytes(str) {
    if (typeof str !== "string")
      throw new Error("string expected");
    return new Uint8Array(new TextEncoder().encode(str));
  }
  function toBytes2(data) {
    if (typeof data === "string")
      data = utf8ToBytes(data);
    abytes(data);
    return data;
  }
  function createHasher(hashCons) {
    const hashC = (msg) => hashCons().update(toBytes2(msg)).digest();
    const tmp = hashCons();
    hashC.outputLen = tmp.outputLen;
    hashC.blockLen = tmp.blockLen;
    hashC.create = () => hashCons();
    return hashC;
  }
  var isLE, swap32IfBE, Hash;
  var init_utils = __esm({
    "node_modules/@noble/hashes/esm/utils.js"() {
      isLE = /* @__PURE__ */ (() => new Uint8Array(new Uint32Array([287454020]).buffer)[0] === 68)();
      swap32IfBE = isLE ? (u) => u : byteSwap32;
      Hash = class {
      };
    }
  });

  // node_modules/@noble/hashes/esm/sha3.js
  function keccakP(s, rounds = 24) {
    const B = new Uint32Array(5 * 2);
    for (let round = 24 - rounds; round < 24; round++) {
      for (let x = 0; x < 10; x++)
        B[x] = s[x] ^ s[x + 10] ^ s[x + 20] ^ s[x + 30] ^ s[x + 40];
      for (let x = 0; x < 10; x += 2) {
        const idx1 = (x + 8) % 10;
        const idx0 = (x + 2) % 10;
        const B0 = B[idx0];
        const B1 = B[idx0 + 1];
        const Th = rotlH(B0, B1, 1) ^ B[idx1];
        const Tl = rotlL(B0, B1, 1) ^ B[idx1 + 1];
        for (let y = 0; y < 50; y += 10) {
          s[x + y] ^= Th;
          s[x + y + 1] ^= Tl;
        }
      }
      let curH = s[2];
      let curL = s[3];
      for (let t = 0; t < 24; t++) {
        const shift = SHA3_ROTL[t];
        const Th = rotlH(curH, curL, shift);
        const Tl = rotlL(curH, curL, shift);
        const PI = SHA3_PI[t];
        curH = s[PI];
        curL = s[PI + 1];
        s[PI] = Th;
        s[PI + 1] = Tl;
      }
      for (let y = 0; y < 50; y += 10) {
        for (let x = 0; x < 10; x++)
          B[x] = s[y + x];
        for (let x = 0; x < 10; x++)
          s[y + x] ^= ~B[(x + 2) % 10] & B[(x + 4) % 10];
      }
      s[0] ^= SHA3_IOTA_H[round];
      s[1] ^= SHA3_IOTA_L[round];
    }
    clean(B);
  }
  var _0n, _1n, _2n, _7n, _256n, _0x71n, SHA3_PI, SHA3_ROTL, _SHA3_IOTA, IOTAS, SHA3_IOTA_H, SHA3_IOTA_L, rotlH, rotlL, Keccak, gen, keccak_256;
  var init_sha3 = __esm({
    "node_modules/@noble/hashes/esm/sha3.js"() {
      init_u64();
      init_utils();
      _0n = BigInt(0);
      _1n = BigInt(1);
      _2n = BigInt(2);
      _7n = BigInt(7);
      _256n = BigInt(256);
      _0x71n = BigInt(113);
      SHA3_PI = [];
      SHA3_ROTL = [];
      _SHA3_IOTA = [];
      for (let round = 0, R = _1n, x = 1, y = 0; round < 24; round++) {
        [x, y] = [y, (2 * x + 3 * y) % 5];
        SHA3_PI.push(2 * (5 * y + x));
        SHA3_ROTL.push((round + 1) * (round + 2) / 2 % 64);
        let t = _0n;
        for (let j = 0; j < 7; j++) {
          R = (R << _1n ^ (R >> _7n) * _0x71n) % _256n;
          if (R & _2n)
            t ^= _1n << (_1n << /* @__PURE__ */ BigInt(j)) - _1n;
        }
        _SHA3_IOTA.push(t);
      }
      IOTAS = split(_SHA3_IOTA, true);
      SHA3_IOTA_H = IOTAS[0];
      SHA3_IOTA_L = IOTAS[1];
      rotlH = (h, l, s) => s > 32 ? rotlBH(h, l, s) : rotlSH(h, l, s);
      rotlL = (h, l, s) => s > 32 ? rotlBL(h, l, s) : rotlSL(h, l, s);
      Keccak = class _Keccak extends Hash {
        // NOTE: we accept arguments in bytes instead of bits here.
        constructor(blockLen, suffix, outputLen, enableXOF = false, rounds = 24) {
          super();
          this.pos = 0;
          this.posOut = 0;
          this.finished = false;
          this.destroyed = false;
          this.enableXOF = false;
          this.blockLen = blockLen;
          this.suffix = suffix;
          this.outputLen = outputLen;
          this.enableXOF = enableXOF;
          this.rounds = rounds;
          anumber(outputLen);
          if (!(0 < blockLen && blockLen < 200))
            throw new Error("only keccak-f1600 function is supported");
          this.state = new Uint8Array(200);
          this.state32 = u32(this.state);
        }
        clone() {
          return this._cloneInto();
        }
        keccak() {
          swap32IfBE(this.state32);
          keccakP(this.state32, this.rounds);
          swap32IfBE(this.state32);
          this.posOut = 0;
          this.pos = 0;
        }
        update(data) {
          aexists(this);
          data = toBytes2(data);
          abytes(data);
          const { blockLen, state } = this;
          const len = data.length;
          for (let pos = 0; pos < len; ) {
            const take = Math.min(blockLen - this.pos, len - pos);
            for (let i = 0; i < take; i++)
              state[this.pos++] ^= data[pos++];
            if (this.pos === blockLen)
              this.keccak();
          }
          return this;
        }
        finish() {
          if (this.finished)
            return;
          this.finished = true;
          const { state, suffix, pos, blockLen } = this;
          state[pos] ^= suffix;
          if ((suffix & 128) !== 0 && pos === blockLen - 1)
            this.keccak();
          state[blockLen - 1] ^= 128;
          this.keccak();
        }
        writeInto(out) {
          aexists(this, false);
          abytes(out);
          this.finish();
          const bufferOut = this.state;
          const { blockLen } = this;
          for (let pos = 0, len = out.length; pos < len; ) {
            if (this.posOut >= blockLen)
              this.keccak();
            const take = Math.min(blockLen - this.posOut, len - pos);
            out.set(bufferOut.subarray(this.posOut, this.posOut + take), pos);
            this.posOut += take;
            pos += take;
          }
          return out;
        }
        xofInto(out) {
          if (!this.enableXOF)
            throw new Error("XOF is not possible for this instance");
          return this.writeInto(out);
        }
        xof(bytes) {
          anumber(bytes);
          return this.xofInto(new Uint8Array(bytes));
        }
        digestInto(out) {
          aoutput(out, this);
          if (this.finished)
            throw new Error("digest() was already called");
          this.writeInto(out);
          this.destroy();
          return out;
        }
        digest() {
          return this.digestInto(new Uint8Array(this.outputLen));
        }
        destroy() {
          this.destroyed = true;
          clean(this.state);
        }
        _cloneInto(to) {
          const { blockLen, suffix, outputLen, rounds, enableXOF } = this;
          to || (to = new _Keccak(blockLen, suffix, outputLen, enableXOF, rounds));
          to.state32.set(this.state32);
          to.pos = this.pos;
          to.posOut = this.posOut;
          to.finished = this.finished;
          to.rounds = rounds;
          to.suffix = suffix;
          to.outputLen = outputLen;
          to.enableXOF = enableXOF;
          to.destroyed = this.destroyed;
          return to;
        }
      };
      gen = (suffix, blockLen, outputLen) => createHasher(() => new Keccak(blockLen, suffix, outputLen));
      keccak_256 = /* @__PURE__ */ (() => gen(1, 136, 256 / 8))();
    }
  });

  // node_modules/viem/_esm/utils/hash/keccak256.js
  function keccak256(value, to_) {
    const to = to_ || "hex";
    const bytes = keccak_256(isHex(value, { strict: false }) ? toBytes(value) : value);
    if (to === "bytes")
      return bytes;
    return toHex(bytes);
  }
  var init_keccak256 = __esm({
    "node_modules/viem/_esm/utils/hash/keccak256.js"() {
      init_sha3();
      init_isHex();
      init_toBytes();
      init_toHex();
    }
  });

  // node_modules/viem/_esm/errors/address.js
  var InvalidAddressError;
  var init_address = __esm({
    "node_modules/viem/_esm/errors/address.js"() {
      init_base();
      InvalidAddressError = class extends BaseError {
        constructor({ address }) {
          super(`Address "${address}" is invalid.`, {
            metaMessages: [
              "- Address must be a hex value of 20 bytes (40 hex characters).",
              "- Address must match its checksum counterpart."
            ],
            name: "InvalidAddressError"
          });
        }
      };
    }
  });

  // node_modules/viem/_esm/utils/lru.js
  var LruMap;
  var init_lru = __esm({
    "node_modules/viem/_esm/utils/lru.js"() {
      LruMap = class extends Map {
        constructor(size2) {
          super();
          Object.defineProperty(this, "maxSize", {
            enumerable: true,
            configurable: true,
            writable: true,
            value: void 0
          });
          this.maxSize = size2;
        }
        get(key) {
          const value = super.get(key);
          if (super.has(key)) {
            super.delete(key);
            super.set(key, value);
          }
          return value;
        }
        set(key, value) {
          if (super.has(key))
            super.delete(key);
          super.set(key, value);
          if (this.maxSize && this.size > this.maxSize) {
            const firstKey = super.keys().next().value;
            if (firstKey !== void 0)
              super.delete(firstKey);
          }
          return this;
        }
      };
    }
  });

  // node_modules/viem/_esm/utils/address/getAddress.js
  function checksumAddress(address_, chainId) {
    if (checksumAddressCache.has(`${address_}.${chainId}`))
      return checksumAddressCache.get(`${address_}.${chainId}`);
    const hexAddress = chainId ? `${chainId}${address_.toLowerCase()}` : address_.substring(2).toLowerCase();
    const hash = keccak256(stringToBytes(hexAddress), "bytes");
    const address = (chainId ? hexAddress.substring(`${chainId}0x`.length) : hexAddress).split("");
    for (let i = 0; i < 40; i += 2) {
      if (hash[i >> 1] >> 4 >= 8 && address[i]) {
        address[i] = address[i].toUpperCase();
      }
      if ((hash[i >> 1] & 15) >= 8 && address[i + 1]) {
        address[i + 1] = address[i + 1].toUpperCase();
      }
    }
    const result = `0x${address.join("")}`;
    checksumAddressCache.set(`${address_}.${chainId}`, result);
    return result;
  }
  var checksumAddressCache;
  var init_getAddress = __esm({
    "node_modules/viem/_esm/utils/address/getAddress.js"() {
      init_toBytes();
      init_keccak256();
      init_lru();
      checksumAddressCache = /* @__PURE__ */ new LruMap(8192);
    }
  });

  // node_modules/viem/_esm/utils/address/isAddress.js
  function isAddress(address, options) {
    const { strict = true } = options ?? {};
    const cacheKey = `${address}.${strict}`;
    if (isAddressCache.has(cacheKey))
      return isAddressCache.get(cacheKey);
    const result = (() => {
      if (!addressRegex.test(address))
        return false;
      if (address.toLowerCase() === address)
        return true;
      if (strict)
        return checksumAddress(address) === address;
      return true;
    })();
    isAddressCache.set(cacheKey, result);
    return result;
  }
  var addressRegex, isAddressCache;
  var init_isAddress = __esm({
    "node_modules/viem/_esm/utils/address/isAddress.js"() {
      init_lru();
      init_getAddress();
      addressRegex = /^0x[a-fA-F0-9]{40}$/;
      isAddressCache = /* @__PURE__ */ new LruMap(8192);
    }
  });

  // node_modules/viem/_esm/utils/data/concat.js
  function concatHex(values) {
    return `0x${values.reduce((acc, x) => acc + x.replace("0x", ""), "")}`;
  }
  var init_concat = __esm({
    "node_modules/viem/_esm/utils/data/concat.js"() {
    }
  });

  // node_modules/viem/_esm/utils/data/slice.js
  function slice(value, start, end, { strict } = {}) {
    if (isHex(value, { strict: false }))
      return sliceHex(value, start, end, {
        strict
      });
    return sliceBytes(value, start, end, {
      strict
    });
  }
  function assertStartOffset(value, start) {
    if (typeof start === "number" && start > 0 && start > size(value) - 1)
      throw new SliceOffsetOutOfBoundsError({
        offset: start,
        position: "start",
        size: size(value)
      });
  }
  function assertEndOffset(value, start, end) {
    if (typeof start === "number" && typeof end === "number" && size(value) !== end - start) {
      throw new SliceOffsetOutOfBoundsError({
        offset: end,
        position: "end",
        size: size(value)
      });
    }
  }
  function sliceBytes(value_, start, end, { strict } = {}) {
    assertStartOffset(value_, start);
    const value = value_.slice(start, end);
    if (strict)
      assertEndOffset(value, start, end);
    return value;
  }
  function sliceHex(value_, start, end, { strict } = {}) {
    assertStartOffset(value_, start);
    const value = `0x${value_.replace("0x", "").slice((start ?? 0) * 2, (end ?? value_.length) * 2)}`;
    if (strict)
      assertEndOffset(value, start, end);
    return value;
  }
  var init_slice = __esm({
    "node_modules/viem/_esm/utils/data/slice.js"() {
      init_data();
      init_isHex();
      init_size();
    }
  });

  // node_modules/viem/_esm/utils/regex.js
  var integerRegex;
  var init_regex = __esm({
    "node_modules/viem/_esm/utils/regex.js"() {
      integerRegex = /^(u?int)(8|16|24|32|40|48|56|64|72|80|88|96|104|112|120|128|136|144|152|160|168|176|184|192|200|208|216|224|232|240|248|256)?$/;
    }
  });

  // node_modules/viem/_esm/utils/abi/encodeAbiParameters.js
  function encodeAbiParameters(params, values) {
    if (params.length !== values.length)
      throw new AbiEncodingLengthMismatchError({
        expectedLength: params.length,
        givenLength: values.length
      });
    const preparedParams = prepareParams({
      params,
      values
    });
    return encodeParams(preparedParams);
  }
  function prepareParams({ params, values }) {
    const preparedParams = [];
    for (let i = 0; i < params.length; i++) {
      preparedParams.push(prepareParam({ param: params[i], value: values[i] }));
    }
    return preparedParams;
  }
  function prepareParam({ param, value }) {
    const arrayComponents = getArrayComponents(param.type);
    if (arrayComponents) {
      const [length, type] = arrayComponents;
      return encodeArray(value, { length, param: { ...param, type } });
    }
    if (param.type === "tuple") {
      return encodeTuple(value, {
        param
      });
    }
    if (param.type === "address") {
      return encodeAddress(value);
    }
    if (param.type === "bool") {
      return encodeBool(value);
    }
    if (param.type.startsWith("uint") || param.type.startsWith("int")) {
      const signed = param.type.startsWith("int");
      const [, , size2 = "256"] = integerRegex.exec(param.type) ?? [];
      return encodeNumber(value, {
        signed,
        size: Number(size2)
      });
    }
    if (param.type.startsWith("bytes")) {
      return encodeBytes(value, { param });
    }
    if (param.type === "string") {
      return encodeString(value);
    }
    throw new InvalidAbiEncodingTypeError(param.type, {
      docsPath: "/docs/contract/encodeAbiParameters"
    });
  }
  function encodeParams(preparedParams) {
    let staticSize = 0;
    for (let i = 0; i < preparedParams.length; i++) {
      const { dynamic, encoded } = preparedParams[i];
      if (dynamic)
        staticSize += 32;
      else
        staticSize += size(encoded);
    }
    const staticParams = [];
    const dynamicParams = [];
    let dynamicSize = 0;
    for (let i = 0; i < preparedParams.length; i++) {
      const { dynamic, encoded } = preparedParams[i];
      if (dynamic) {
        staticParams.push(numberToHex(staticSize + dynamicSize, { size: 32 }));
        dynamicParams.push(encoded);
        dynamicSize += size(encoded);
      } else {
        staticParams.push(encoded);
      }
    }
    return concatHex([...staticParams, ...dynamicParams]);
  }
  function encodeAddress(value) {
    if (!isAddress(value))
      throw new InvalidAddressError({ address: value });
    return { dynamic: false, encoded: padHex(value.toLowerCase()) };
  }
  function encodeArray(value, { length, param }) {
    const dynamic = length === null;
    if (!Array.isArray(value))
      throw new InvalidArrayError(value);
    if (!dynamic && value.length !== length)
      throw new AbiEncodingArrayLengthMismatchError({
        expectedLength: length,
        givenLength: value.length,
        type: `${param.type}[${length}]`
      });
    let dynamicChild = value.length === 0 && isDynamicType(param);
    const preparedParams = [];
    for (let i = 0; i < value.length; i++) {
      const preparedParam = prepareParam({ param, value: value[i] });
      if (preparedParam.dynamic)
        dynamicChild = true;
      preparedParams.push(preparedParam);
    }
    if (dynamic || dynamicChild) {
      const data = encodeParams(preparedParams);
      if (dynamic) {
        const length2 = numberToHex(preparedParams.length, { size: 32 });
        return {
          dynamic: true,
          encoded: concatHex([length2, data])
        };
      }
      if (dynamicChild)
        return { dynamic: true, encoded: data };
    }
    return {
      dynamic: false,
      encoded: concatHex(preparedParams.map(({ encoded }) => encoded))
    };
  }
  function encodeBytes(value, { param }) {
    const [, paramSize] = param.type.split("bytes");
    const bytesSize = size(value);
    if (!paramSize) {
      let value_ = value;
      if (bytesSize % 32 !== 0)
        value_ = padHex(value_, {
          dir: "right",
          size: Math.ceil((value.length - 2) / 2 / 32) * 32
        });
      return {
        dynamic: true,
        encoded: concatHex([
          padHex(numberToHex(bytesSize, { size: 32 })),
          value_
        ])
      };
    }
    if (bytesSize !== Number.parseInt(paramSize, 10))
      throw new AbiEncodingBytesSizeMismatchError({
        expectedSize: Number.parseInt(paramSize, 10),
        value
      });
    return { dynamic: false, encoded: padHex(value, { dir: "right" }) };
  }
  function encodeBool(value) {
    if (typeof value !== "boolean")
      throw new BaseError(`Invalid boolean value: "${value}" (type: ${typeof value}). Expected: \`true\` or \`false\`.`);
    return { dynamic: false, encoded: padHex(boolToHex(value)) };
  }
  function encodeNumber(value, { signed, size: size2 = 256 }) {
    if (typeof size2 === "number") {
      const max = 2n ** (BigInt(size2) - (signed ? 1n : 0n)) - 1n;
      const min = signed ? -max - 1n : 0n;
      if (value > max || value < min)
        throw new IntegerOutOfRangeError({
          max: max.toString(),
          min: min.toString(),
          signed,
          size: size2 / 8,
          value: value.toString()
        });
    }
    return {
      dynamic: false,
      encoded: numberToHex(value, {
        size: 32,
        signed
      })
    };
  }
  function encodeString(value) {
    const hexValue = stringToHex(value);
    const partsLength = Math.ceil(size(hexValue) / 32);
    const parts = [];
    for (let i = 0; i < partsLength; i++) {
      parts.push(padHex(slice(hexValue, i * 32, (i + 1) * 32), {
        dir: "right"
      }));
    }
    return {
      dynamic: true,
      encoded: concatHex([
        padHex(numberToHex(size(hexValue), { size: 32 })),
        ...parts
      ])
    };
  }
  function encodeTuple(value, { param }) {
    let dynamic = false;
    const preparedParams = [];
    for (let i = 0; i < param.components.length; i++) {
      const param_ = param.components[i];
      const index = Array.isArray(value) ? i : param_.name;
      const preparedParam = prepareParam({
        param: param_,
        value: value[index]
      });
      preparedParams.push(preparedParam);
      if (preparedParam.dynamic)
        dynamic = true;
    }
    return {
      dynamic,
      encoded: dynamic ? encodeParams(preparedParams) : concatHex(preparedParams.map(({ encoded }) => encoded))
    };
  }
  function getArrayComponents(type) {
    const matches = type.match(/^(.*)\[(\d+)?\]$/);
    return matches ? (
      // Return `null` if the array is dynamic.
      [matches[2] ? Number(matches[2]) : null, matches[1]]
    ) : void 0;
  }
  function isDynamicType(param) {
    const { type } = param;
    if (type === "string")
      return true;
    if (type === "bytes")
      return true;
    if (type.endsWith("[]"))
      return true;
    if (type === "tuple")
      return param.components.some(isDynamicType);
    const arrayComponents = getArrayComponents(type);
    if (arrayComponents)
      return isDynamicType({ ...param, type: arrayComponents[1] });
    return false;
  }
  var init_encodeAbiParameters = __esm({
    "node_modules/viem/_esm/utils/abi/encodeAbiParameters.js"() {
      init_abi();
      init_address();
      init_base();
      init_encoding();
      init_isAddress();
      init_concat();
      init_pad();
      init_size();
      init_slice();
      init_toHex();
      init_regex();
    }
  });

  // node_modules/viem/_esm/utils/signature/hashTypedData.js
  function hashDomain({ domain, types }) {
    return hashStruct({
      data: domain,
      primaryType: "EIP712Domain",
      types
    });
  }
  function hashStruct({ data, primaryType, types }) {
    const encoded = encodeData({
      data,
      primaryType,
      types
    });
    return keccak256(encoded);
  }
  function encodeData({ data, primaryType, types }) {
    const encodedTypes = [{ type: "bytes32" }];
    const encodedValues = [hashType({ primaryType, types })];
    for (const field of types[primaryType]) {
      const [type, value] = encodeField({
        types,
        name: field.name,
        type: field.type,
        value: data[field.name]
      });
      encodedTypes.push(type);
      encodedValues.push(value);
    }
    return encodeAbiParameters(encodedTypes, encodedValues);
  }
  function hashType({ primaryType, types }) {
    const encodedHashType = toHex(encodeType({ primaryType, types }));
    return keccak256(encodedHashType);
  }
  function encodeType({ primaryType, types }) {
    let result = "";
    const unsortedDeps = findTypeDependencies({ primaryType, types });
    unsortedDeps.delete(primaryType);
    const deps = [primaryType, ...Array.from(unsortedDeps).sort()];
    for (const type of deps) {
      result += `${type}(${types[type].map(({ name, type: t }) => `${t} ${name}`).join(",")})`;
    }
    return result;
  }
  function findTypeDependencies({ primaryType: primaryType_, types }, results = /* @__PURE__ */ new Set()) {
    const match = primaryType_.match(/^\w*/u);
    const primaryType = match?.[0];
    if (results.has(primaryType) || types[primaryType] === void 0) {
      return results;
    }
    results.add(primaryType);
    for (const field of types[primaryType]) {
      findTypeDependencies({ primaryType: field.type, types }, results);
    }
    return results;
  }
  function encodeField({ types, name, type, value }) {
    if (types[type] !== void 0) {
      return [
        { type: "bytes32" },
        keccak256(encodeData({ data: value, primaryType: type, types }))
      ];
    }
    if (type === "bytes")
      return [{ type: "bytes32" }, keccak256(value)];
    if (type === "string")
      return [{ type: "bytes32" }, keccak256(toHex(value))];
    if (type.lastIndexOf("]") === type.length - 1) {
      const parsedType = type.slice(0, type.lastIndexOf("["));
      const typeValuePairs = value.map((item) => encodeField({
        name,
        type: parsedType,
        types,
        value: item
      }));
      return [
        { type: "bytes32" },
        keccak256(encodeAbiParameters(typeValuePairs.map(([t]) => t), typeValuePairs.map(([, v]) => v)))
      ];
    }
    return [{ type }, value];
  }
  var init_hashTypedData = __esm({
    "node_modules/viem/_esm/utils/signature/hashTypedData.js"() {
      init_encodeAbiParameters();
      init_toHex();
      init_keccak256();
    }
  });

  // node_modules/viem/_esm/index.js
  var init_esm = __esm({
    "node_modules/viem/_esm/index.js"() {
      init_hashTypedData();
    }
  });

  // src/order_signing.js
  var require_order_signing = __commonJS({
    "src/order_signing.js"(exports, module) {
      init_esm();
      var POLYGON_CHAIN_ID = "0x89";
      var SESSION_URL = "/execution/polymarket/browser-order-signing-session";
      var STATUS_URL = `${SESSION_URL}/status`;
      var COMPLETE_URL = `${SESSION_URL}/complete`;
      var STANDARD_EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B";
      var NEG_RISK_EXCHANGE = "0xe2222d279d744050d28e00520010520000310F59";
      var PUSD_COLLATERAL = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB";
      var ZERO_BYTES32 = `0x${"00".repeat(32)}`;
      var ORDER_TYPE_STRING = "Order(uint256 salt,address maker,address signer,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint8 side,uint8 signatureType,uint256 timestamp,bytes32 metadata,bytes32 builder)";
      var MODE_SIGNATURE_TYPE = Object.freeze({ eoa: 0, proxy: 1, safe: 2, deposit_wallet: 3 });
      var ORDER_FIELDS = Object.freeze([
        ["salt", "uint256"],
        ["maker", "address"],
        ["signer", "address"],
        ["tokenId", "uint256"],
        ["makerAmount", "uint256"],
        ["takerAmount", "uint256"],
        ["side", "uint8"],
        ["signatureType", "uint8"],
        ["timestamp", "uint256"],
        ["metadata", "bytes32"],
        ["builder", "bytes32"]
      ]);
      var TYPED_DATA_SIGN_FIELDS = Object.freeze([
        ["contents", "Order"],
        ["name", "string"],
        ["version", "string"],
        ["chainId", "uint256"],
        ["verifyingContract", "address"],
        ["salt", "bytes32"]
      ]);
      var DOMAIN_FIELDS = Object.freeze([
        { name: "name", type: "string" },
        { name: "version", type: "string" },
        { name: "chainId", type: "uint256" },
        { name: "verifyingContract", type: "address" }
      ]);
      var HEX_SIGNATURE = /^0x[0-9a-fA-F]{130}$/;
      var HEX_32 = /^0x[0-9a-fA-F]{64}$/;
      var SHA256 = /^[0-9a-f]{64}$/;
      var ADDRESS = /^0x[0-9a-fA-F]{40}$/;
      function extractCapability(window2) {
        const raw = String(window2.location.hash || "");
        const params = new URLSearchParams(raw.startsWith("#") ? raw.slice(1) : raw);
        const token = params.get("access_token");
        if (!token || params.size !== 1 || token.length > 256) {
          throw new Error("Order signing capability is unavailable.");
        }
        window2.history.replaceState(
          null,
          "",
          `${window2.location.pathname}${window2.location.search || ""}`
        );
        if (window2.location.hash) window2.location.hash = "";
        return token;
      }
      function utf8Hex(value) {
        return Array.from(new TextEncoder().encode(value), (byte) => byte.toString(16).padStart(2, "0")).join("");
      }
      function wrapDepositWalletSignatureParts(rawSignature, domainSeparator, contentsHash) {
        if (!HEX_SIGNATURE.test(rawSignature) || !HEX_32.test(domainSeparator) || !HEX_32.test(contentsHash)) {
          throw new Error("Wallet signature is invalid.");
        }
        const orderTypeHex = utf8Hex(ORDER_TYPE_STRING);
        const lengthHex = (orderTypeHex.length / 2).toString(16).padStart(4, "0");
        return `${rawSignature}${domainSeparator.slice(2)}${contentsHash.slice(2)}${orderTypeHex}${lengthHex}`;
      }
      function finalizeWalletSignature(rawSignature, session) {
        if (!HEX_SIGNATURE.test(rawSignature)) {
          throw new Error("Wallet signature is invalid.");
        }
        const signatureType = session.order_payload.order.signatureType;
        if (signatureType !== 3) return rawSignature;
        const typedData = session.order_payload.typed_data;
        const domainSeparator = hashDomain({
          domain: typedData.domain,
          types: { EIP712Domain: DOMAIN_FIELDS }
        });
        const contentsHash = hashStruct({
          data: typedData.message.contents,
          primaryType: "Order",
          types: typedData.types
        });
        return wrapDepositWalletSignatureParts(
          rawSignature,
          domainSeparator,
          contentsHash
        );
      }
      function assertSessionProjection(session) {
        if (!session || typeof session !== "object" || session.status !== "pending_browser_signature") {
          throw new Error("This order is not waiting for a wallet signature.");
        }
        const payload = session.order_payload;
        const typedData = payload && payload.typed_data;
        const order = payload && payload.order;
        const domain = typedData && typedData.domain;
        const walletMode = String(session.wallet_mode || "").toLowerCase();
        const expectedSignatureType = MODE_SIGNATURE_TYPE[walletMode];
        const exactKeys = (value, expected) => Boolean(
          value && typeof value === "object" && !Array.isArray(value) && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...expected].sort())
        );
        const typeEntries = (value) => Array.isArray(value) ? value.map((field) => [field && field.name, field && field.type]) : [];
        const sameTypes = (actual, expected) => JSON.stringify(typeEntries(actual)) === JSON.stringify(expected);
        const typeKeys = typedData && typedData.types ? Object.keys(typedData.types).sort() : [];
        const expectedTypeKeys = walletMode === "deposit_wallet" ? ["Order", "TypedDataSign"] : ["Order"];
        const orderKeys = order && typeof order === "object" ? Object.keys(order).sort() : [];
        const expectedOrderKeys = [
          ...ORDER_FIELDS.map(([name]) => name),
          "expiration"
        ].sort();
        const payloadKeys = [
          "typed_data",
          "order",
          "orderType",
          "exchange",
          "collateral",
          "tickSize",
          "minOrderSize",
          "negRisk",
          "provenance",
          "projection_sha256"
        ];
        const provenanceKeys = [
          "preview_id",
          "market_id",
          "core_action_id",
          "core_policy_decision_id",
          "funding_operation_id"
        ];
        const expectedExchange = payload && payload.negRisk === true ? NEG_RISK_EXCHANGE : STANDARD_EXCHANGE;
        const messageKeys = walletMode === "deposit_wallet" ? ["contents", "name", "version", "chainId", "verifyingContract", "salt"] : ORDER_FIELDS.map(([name]) => name);
        if (!payload || !typedData || !order || !domain || !ADDRESS.test(String(session.wallet_address || "")) || !ADDRESS.test(String(payload.exchange || "")) || typeof session.session_id !== "string" || !session.session_id.startsWith("pm_sign_sess_") || session.session_id.length > 128 || domain.name !== "Polymarket CTF Exchange" || domain.version !== "2" || Number(domain.chainId) !== 137 || String(domain.verifyingContract).toLowerCase() !== String(payload.exchange).toLowerCase() || !exactKeys(payload, payloadKeys) || !exactKeys(typedData, ["domain", "types", "primaryType", "message"]) || !exactKeys(domain, ["name", "version", "chainId", "verifyingContract"]) || !exactKeys(typedData.message, messageKeys) || !exactKeys(payload.provenance, provenanceKeys) || Object.values(payload.provenance).some((value) => typeof value !== "string" || !value) || typeof payload.negRisk !== "boolean" || String(payload.exchange).toLowerCase() !== expectedExchange.toLowerCase() || String(session.exchange).toLowerCase() !== expectedExchange.toLowerCase() || String(payload.collateral).toLowerCase() !== PUSD_COLLATERAL.toLowerCase() || !SHA256.test(String(payload.projection_sha256 || "")) || expectedSignatureType === void 0 || order.signatureType !== expectedSignatureType || typedData.primaryType !== (walletMode === "deposit_wallet" ? "TypedDataSign" : "Order") || JSON.stringify(typeKeys) !== JSON.stringify(expectedTypeKeys.sort()) || !sameTypes(typedData.types.Order, ORDER_FIELDS) || walletMode === "deposit_wallet" && !sameTypes(typedData.types.TypedDataSign, TYPED_DATA_SIGN_FIELDS) || JSON.stringify(orderKeys) !== JSON.stringify(expectedOrderKeys) || !["GTC", "GTD"].includes(payload.orderType) || String(order.side) !== String(session.side || "").toUpperCase()) {
          throw new Error("The server order projection is invalid.");
        }
        const typedOrder = walletMode === "deposit_wallet" ? typedData.message && typedData.message.contents : typedData.message;
        if (!typedOrder || !exactKeys(typedOrder, ORDER_FIELDS.map(([name]) => name)) || String(typedOrder.maker).toLowerCase() !== String(order.maker).toLowerCase() || String(typedOrder.signer).toLowerCase() !== String(order.signer).toLowerCase() || String(typedOrder.salt) !== String(order.salt) || String(typedOrder.tokenId) !== String(order.tokenId) || String(typedOrder.makerAmount) !== String(order.makerAmount) || String(typedOrder.takerAmount) !== String(order.takerAmount) || Number(typedOrder.side) !== (order.side === "BUY" ? 0 : order.side === "SELL" ? 1 : -1) || Number(typedOrder.signatureType) !== Number(order.signatureType) || String(typedOrder.timestamp) !== String(order.timestamp) || String(typedOrder.metadata) !== String(order.metadata) || String(typedOrder.builder) !== String(order.builder)) {
          throw new Error("The server order projection has changed.");
        }
        const wallet = String(session.wallet_address).toLowerCase();
        const maker = String(order.maker).toLowerCase();
        const signer = String(order.signer).toLowerCase();
        if ((walletMode === "deposit_wallet" ? maker !== signer : signer !== wallet) || walletMode === "eoa" && maker !== wallet || (walletMode === "proxy" || walletMode === "safe") && maker === wallet) {
          throw new Error("The order signer does not match the bound wallet.");
        }
        if (walletMode === "deposit_wallet") {
          const outer = typedData.message;
          if (outer.name !== "DepositWallet" || outer.version !== "1" || Number(outer.chainId) !== 137 || String(outer.verifyingContract).toLowerCase() !== signer || outer.salt !== ZERO_BYTES32) {
            throw new Error("The Deposit Wallet projection is invalid.");
          }
        }
        return session;
      }
      function createOrderSigningPage({ document: document2, window: window2, fetch }) {
        const elements = {
          title: document2.getElementById("order-title"),
          outcome: document2.getElementById("order-outcome"),
          side: document2.getElementById("order-side"),
          amount: document2.getElementById("order-amount"),
          limit: document2.getElementById("order-limit-price"),
          worst: document2.getElementById("order-worst-price"),
          slippage: document2.getElementById("order-slippage"),
          wallet: document2.getElementById("order-wallet"),
          exchange: document2.getElementById("order-exchange"),
          mode: document2.getElementById("order-signature-mode"),
          walletList: document2.getElementById("wallet-list"),
          sign: document2.getElementById("sign-order"),
          status: document2.getElementById("order-status"),
          returnLink: document2.getElementById("return-link")
        };
        let capability = null;
        let session = null;
        let selectedProvider = null;
        let pending = false;
        let submissionAttempted = false;
        let providerSwitchLocked = false;
        let exited = false;
        let generation = 0;
        const providers = /* @__PURE__ */ new Map();
        const providerListeners = /* @__PURE__ */ new Map();
        function setStatus(message) {
          elements.status.textContent = message;
        }
        function headers(json = false) {
          if (!capability) throw new Error("Order signing capability is unavailable.");
          return {
            Authorization: `Bearer ${capability}`,
            "X-Clink-Origin": window2.location.origin,
            ...json ? { "Content-Type": "application/json" } : {}
          };
        }
        async function api(url, init = {}) {
          const response = await fetch(url, {
            ...init,
            headers: { ...headers(Boolean(init.body)), ...init.headers || {} },
            credentials: "omit",
            referrerPolicy: "no-referrer",
            cache: "no-store"
          });
          if (!response.ok) throw new Error("Order signing request was rejected.");
          return response.json();
        }
        function renderSession(value) {
          elements.title.textContent = String(value.title || "Unknown market");
          elements.outcome.textContent = String(value.outcome || "\u2014");
          elements.side.textContent = String(value.side || "\u2014").toUpperCase();
          elements.amount.textContent = `${String(value.amount_usd || "\u2014")} pUSD`;
          elements.limit.textContent = String(value.limit_price ?? "\u2014");
          elements.worst.textContent = String(value.worst_case_price ?? "\u2014");
          elements.slippage.textContent = `${String(value.max_slippage_bps ?? 0)} bps`;
          elements.wallet.textContent = String(value.wallet_address || "\u2014");
          elements.exchange.textContent = String(value.exchange || "\u2014");
          elements.mode.textContent = value.wallet_mode === "deposit_wallet" ? "Deposit Wallet" : String(value.wallet_mode || "\u2014").toUpperCase();
          elements.returnLink.setAttribute?.("href", String(value.return_url || "/"));
        }
        function detachProvider() {
          if (!selectedProvider) return;
          const listeners = providerListeners.get(selectedProvider);
          if (listeners && typeof selectedProvider.removeListener === "function") {
            selectedProvider.removeListener("accountsChanged", listeners.accountsChanged);
            selectedProvider.removeListener("chainChanged", listeners.chainChanged);
          }
          providerListeners.delete(selectedProvider);
        }
        function invalidateWallet(message) {
          generation += 1;
          pending = false;
          elements.sign.disabled = true;
          setStatus(message);
        }
        function selectProvider(provider, button) {
          if (pending && selectedProvider && selectedProvider !== provider) {
            generation += 1;
            pending = false;
            providerSwitchLocked = true;
          }
          detachProvider();
          selectedProvider = provider;
          for (const candidate of elements.walletList.children) {
            candidate.dataset.selected = candidate === button ? "true" : "false";
          }
          if (typeof provider.on === "function") {
            const listeners = {
              accountsChanged: () => invalidateWallet("Wallet account changed. Reopen this order."),
              chainChanged: () => invalidateWallet("Wallet network changed. Reopen this order.")
            };
            provider.on("accountsChanged", listeners.accountsChanged);
            provider.on("chainChanged", listeners.chainChanged);
            providerListeners.set(provider, listeners);
          }
          elements.sign.disabled = !session || pending || submissionAttempted || providerSwitchLocked;
          setStatus(
            providerSwitchLocked ? "Wallet changed during this attempt. Reopen the order to continue." : "Ready. Confirm once to request the wallet signature."
          );
        }
        function addProvider(detail) {
          const provider = detail && detail.provider;
          if (!provider || typeof provider.request !== "function") return;
          const key = String(detail.info && detail.info.uuid || `provider-${providers.size}`);
          if (providers.has(key)) return;
          providers.set(key, provider);
          const button = document2.createElement("button");
          button.type = "button";
          button.textContent = String(detail.info && detail.info.name || "Browser wallet");
          button.addEventListener("click", () => selectProvider(provider, button));
          elements.walletList.append(button);
          if (providers.size === 1) selectProvider(provider, button);
        }
        const announceProvider = (event) => addProvider(event.detail);
        async function pollStatus() {
          const status = await api(STATUS_URL);
          if (exited) return null;
          if (status.status === "submitted") {
            setStatus("Order submitted. Return to Agentonomy to monitor it.");
            elements.returnLink.hidden = false;
          } else {
            setStatus("Submission status is uncertain. No second order was sent.");
          }
          elements.sign.disabled = true;
          return status;
        }
        async function signOnce() {
          if (pending || submissionAttempted || providerSwitchLocked || exited || !session || !selectedProvider) return;
          pending = true;
          elements.sign.disabled = true;
          const attempt = generation;
          const provider = selectedProvider;
          try {
            assertSessionProjection(session);
            const chainId = await provider.request({ method: "eth_chainId" });
            if (attempt !== generation || exited) return;
            if (String(chainId).toLowerCase() !== POLYGON_CHAIN_ID) {
              throw new Error("Switch your wallet to Polygon before signing.");
            }
            const accounts = await provider.request({ method: "eth_requestAccounts" });
            const account = String(accounts && accounts[0] || "");
            if (account.toLowerCase() !== String(session.wallet_address).toLowerCase()) {
              throw new Error("Select the bound wallet before signing.");
            }
            if (attempt !== generation || exited) return;
            submissionAttempted = true;
            const rawSignature = await provider.request({
              method: "eth_signTypedData_v4",
              params: [account, JSON.stringify(session.order_payload.typed_data)]
            });
            if (attempt !== generation || exited) return;
            const signature = finalizeWalletSignature(rawSignature, session);
            const signedOrder = {
              order: { ...session.order_payload.order, signature },
              orderType: session.order_payload.orderType
            };
            try {
              const completed = await api(COMPLETE_URL, {
                method: "POST",
                body: JSON.stringify({
                  signed_order: signedOrder,
                  wallet_address: account,
                  order_type: session.order_payload.orderType
                })
              });
              if (attempt !== generation || exited) return;
              setStatus(
                completed.status === "submitted" ? "Order submitted. Return to Agentonomy to monitor it." : "Order was not submitted. Return to Agentonomy for status."
              );
              elements.returnLink.hidden = false;
              elements.sign.disabled = true;
            } catch (error) {
              if (attempt !== generation || exited) return;
              elements.sign.disabled = true;
              try {
                await pollStatus();
              } catch (_statusError) {
                if (attempt !== generation || exited) return;
                setStatus("Submission status is uncertain. No second order will be sent.");
                elements.sign.disabled = true;
              }
              return;
            }
          } catch (error) {
            if (attempt !== generation || exited) return;
            pending = false;
            elements.sign.disabled = submissionAttempted || providerSwitchLocked;
            setStatus(String(error && error.message ? error.message : "Wallet signing failed."));
          }
        }
        async function start() {
          const startGeneration = generation;
          try {
            capability = extractCapability(window2);
            window2.addEventListener("eip6963:announceProvider", announceProvider);
            window2.dispatchEvent(new Event("eip6963:requestProvider"));
            if (window2.ethereum) {
              addProvider({
                info: { uuid: "window-ethereum", name: "Browser wallet" },
                provider: window2.ethereum
              });
            }
            const loaded = await api(SESSION_URL);
            if (exited || startGeneration !== generation) return;
            session = assertSessionProjection(loaded);
            renderSession(session);
            elements.sign.disabled = !selectedProvider || submissionAttempted || providerSwitchLocked;
            setStatus(
              selectedProvider ? "Ready. Confirm once to request the wallet signature." : "Choose a browser wallet to continue."
            );
          } catch (error) {
            if (!exited) {
              elements.sign.disabled = true;
              setStatus(String(error && error.message ? error.message : "Order could not be loaded."));
            }
          }
        }
        function exit() {
          exited = true;
          generation += 1;
          pending = false;
          capability = null;
          session = null;
          elements.sign.disabled = true;
          detachProvider();
          window2.removeEventListener("eip6963:announceProvider", announceProvider);
          window2.removeEventListener("pagehide", exit);
        }
        elements.sign.addEventListener("click", signOnce);
        window2.addEventListener("pagehide", exit);
        return { exit, pollStatus, signOnce, start };
      }
      if (typeof module !== "undefined" && module.exports) {
        module.exports = {
          ORDER_TYPE_STRING,
          assertSessionProjection,
          createOrderSigningPage,
          extractCapability,
          finalizeWalletSignature,
          wrapDepositWalletSignatureParts
        };
      }
      if (typeof document !== "undefined" && typeof window !== "undefined") {
        createOrderSigningPage({ document, window, fetch: window.fetch.bind(window) }).start();
      }
    }
  });
  require_order_signing();
})();
