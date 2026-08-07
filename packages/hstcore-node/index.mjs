// Bindings for the HST-core Embedded ABI — the thirteen extern "C" functions of
// hstcore.h, exported under ABI node HSTCORE_1.4.
//
// This package computes nothing. The work is done by libhstcore, a shared
// library this package does not contain. In an HST Studio download the
// library is already in bin/ (libhstcore.so / libhstcore.dylib), Apache-2.0,
// unmetered, and needs no key, token or account -- pass its path to load(),
// since bin/ is not on koffi's default search path. A separate, metered
// build of the same library also exists as its own artifact -- that is not
// "the Enterprise build", which is Profile 1 plus Profile 3 and has never been
// built. Install this on its own
// and the first open() throws — there is no evaluation fallback and no JS
// path. If what you wanted was a sparse delta matvec you can actually run,
// you want spdelta: Apache-2.0, open, and deliberately the baseline rather
// than a product.
//
// This comment called the library "closed-source" and licence-gated across
// the board until 2026-08-06, which was true of the metered build and
// false of the community one shipped beside this binding in the same tree.
//
// ON THE ONE DEPENDENCY. Every other binding in this family has none. Node has no
// stable built-in FFI: the alternatives are a native addon (a compile step and a
// prebuild matrix per Node ABI and platform) or koffi. koffi is the smaller
// commitment — it keeps `npm install` working everywhere and keeps this package
// as pure JavaScript, which is the same reasoning that made the Python binding
// ctypes rather than a C extension.
//
// LANE INTERLEAVING. With batch > 1 every state-shaped and value-shaped array is
// lane-interleaved: element i of lane b is at buf[i*batch+b], NOT buf[b*n+i].
// This is the most commonly mis-bound detail in this ABI and getting it wrong
// yields plausible numbers that are wrong.

import koffi from "koffi";
import { createRequire } from "node:module";

/** The versioned symbol node the library exports. */
export const ABI_NODE = "HSTCORE_1.4";

/**
 * Every function in the ABI, in header order.
 *
 * Thirteen, not twelve: the commit that added hst_apply_shadow said "12 total",
 * and the Python and Rust bindings were both written from that count and shipped
 * without hst_set_input. The authority is oss/hstcore-abi/abi.json.
 */
export const SYMBOLS = [
  "hst_open",
  "hst_open_batched",
  "hst_apply_delta",
  "hst_apply_shadow",
  "hst_batch",
  "hst_output_dim",
  "hst_input_dim",
  "hst_state",
  "hst_set_state",
  "hst_set_input",
  "hst_recompute_full",
  "hst_close",
  "hst_version",
];

/** Anything the native boundary refused. */
export class HstError extends Error {
  constructor(message, code = 0) {
    super(code === 0 ? message : `${message} (code ${code}${explain(code)})`);
    this.name = "HstError";
    this.code = code;
  }
}

function explain(code) {
  switch (code) {
    case -1: return ": bad arguments or length mismatch";
    case -2: return ": internal exception in libhstcore";
    case -3: return ": shadow quota exhausted";
    case -4: return ": licence carries no shadow-apply grant";
    case -5: return ": input and output states were not primed together — call " +
                    "setState and setInput with the same baseline, or neither";
    default: return "";
  }
}

/** Platform-conventional file name of the shipped library. */
export function defaultLibraryName() {
  if (process.platform === "darwin") return "libhstcore.dylib";
  if (process.platform === "win32") return "hstcore.dll";
  return "libhstcore.so";
}

let _lib = null;
let _api = null;
let _path = null;

/**
 * Load libhstcore for this process. Idempotent.
 *
 * One library per process, held forever: the handles it hands out outlive any
 * individual call, and unloading underneath them would invalidate them.
 */
export function load(path = defaultLibraryName()) {
  if (_api) {
    if (path !== _path && path !== defaultLibraryName()) {
      throw new HstError(
        `library already loaded from ${_path}; refusing to also load ${path}. ` +
        `One library per process.`);
    }
    return _api;
  }
  try {
    _lib = koffi.load(path);
  } catch (e) {
    throw new HstError(
      `could not load ${path}: ${e.message}. This package is only the binding; ` +
      `it ships no library. In an HST Studio download the library is in bin/ ` +
      `(libhstcore.so or libhstcore.dylib) -- pass its path to load(), since ` +
      `bin/ is not on koffi's default search path.`);
  }

  const ptr = koffi.pointer(koffi.opaque("hst_ctx"));
  const missing = [];
  const bind = (name, ret, args) => {
    try {
      return _lib.func(name, ret, args);
    } catch {
      missing.push(name);
      return null;
    }
  };

  const api = {
    hst_open: bind("hst_open", ptr, ["str", "str", "char *", "size_t"]),
    hst_open_batched: bind("hst_open_batched", ptr, ["str", "str", "int32_t", "char *", "size_t"]),
    hst_apply_delta: bind("hst_apply_delta", "int", [ptr, "int32_t *", "double *", "int32_t", "double *"]),
    hst_apply_shadow: bind("hst_apply_shadow", "int", [ptr, "int32_t *", "double *", "int32_t", "double *"]),
    hst_batch: bind("hst_batch", "int32_t", [ptr]),
    hst_output_dim: bind("hst_output_dim", "int32_t", [ptr]),
    hst_input_dim: bind("hst_input_dim", "int32_t", [ptr]),
    hst_state: bind("hst_state", "double *", [ptr]),
    hst_set_state: bind("hst_set_state", "int", [ptr, "double *", "int32_t"]),
    hst_set_input: bind("hst_set_input", "int", [ptr, "double *", "int32_t"]),
    hst_recompute_full: bind("hst_recompute_full", "int", [ptr, "double *"]),
    hst_close: bind("hst_close", "void", [ptr]),
    hst_version: bind("hst_version", "str", []),
  };

  if (missing.length) {
    throw new HstError(
      `${path} does not export ${missing.length} of the ${SYMBOLS.length} ` +
      `${ABI_NODE} symbols: ${missing.join(", ")}. A library missing ` +
      `hst_apply_shadow or hst_set_input is a STALE BUILD from before the ` +
      `1.3 -> 1.4 bump, not a different ABI.`);
  }

  _api = api;
  _path = path;
  return api;
}

/** Path the library was loaded from, or null. */
export function loadedPath() {
  return _path;
}

/** Library version string. */
export function version() {
  return load().hst_version();
}

/**
 * A live HST session: a compiled operator plus the dense state evolving under it.
 *
 * Everything is in-process. A network hop in front of this destroys the win
 * outright, which is why there is no client mode.
 *
 * Two rules the library enforces so you cannot quietly break them:
 *
 *  1. setState and setInput go together. They prime different buffers — the
 *     output y, and the input x that recomputeFull computes A*x from. Prime one
 *     alone and recomputeFull refuses with -5 rather than return a vector that
 *     disagrees with y by exactly A*x0 forever.
 *  2. Shadow and production applies must not share a session.
 */
export class Session {
  #api;
  #ctx;

  constructor(api, ctx) {
    this.#api = api;
    this.#ctx = ctx;
    this.batch = api.hst_batch(ctx);
    this.outputDim = api.hst_output_dim(ctx);
    this.inputDim = api.hst_input_dim(ctx);
    if (this.outputDim <= 0 || this.inputDim <= 0 || this.batch <= 0) {
      this.close();
      throw new HstError(
        `library reported a nonsensical shape: output=${this.outputDim} ` +
        `input=${this.inputDim} batch=${this.batch}`);
    }
  }

  /**
   * Open a session with `batch` independent right-hand-side lanes (1..32).
   *
   * Batching amortizes the sparse index traversal across lanes, which is where
   * HST beats a plain exact column delta. At batch === 1 it frequently does not —
   * measure before assuming.
   */
  static open(artifactPath, licenseToken, batch = 1, libraryPath = undefined) {
    if (!Number.isInteger(batch) || batch < 1 || batch > 32) {
      throw new RangeError(`batch must be an integer 1..32, got ${batch}`);
    }
    const api = load(libraryPath ?? defaultLibraryName());
    const errbuf = Buffer.alloc(512);
    const ctx = batch === 1
      ? api.hst_open(artifactPath, licenseToken, errbuf, errbuf.length)
      : api.hst_open_batched(artifactPath, licenseToken, batch, errbuf, errbuf.length);
    if (!ctx) {
      const nul = errbuf.indexOf(0);
      const reason = errbuf.toString("utf8", 0, nul < 0 ? 0 : nul);
      throw new HstError(`hst_open failed: ${reason} (artifact=${artifactPath})`);
    }
    return new Session(api, ctx);
  }

  /** outputDim * batch — the length of every state-shaped array. */
  get stateSize() {
    return this.outputDim * this.batch;
  }

  /**
   * inputDim * batch — the length setInput requires. Differs from stateSize on
   * any non-square operator, which is why setInput cannot reuse it.
   */
  get inputSize() {
    return this.inputDim * this.batch;
  }

  #live() {
    if (!this.#ctx) throw new HstError("session is closed; open a new one");
    return this.#ctx;
  }

  #apply(cols, vals, shadow) {
    const ctx = this.#live();
    const c = cols instanceof Int32Array ? cols : Int32Array.from(cols);
    const v = vals instanceof Float64Array ? vals : Float64Array.from(vals);
    if (v.length !== c.length * this.batch) {
      throw new HstError(
        `vals must be cols.length * batch = ${c.length} * ${this.batch} = ` +
        `${c.length * this.batch}, got ${v.length}. Values are LANE-INTERLEAVED: ` +
        `vals[i*batch+b].`);
    }
    const out = new Float64Array(this.stateSize);
    const fn = shadow ? this.#api.hst_apply_shadow : this.#api.hst_apply_delta;
    const name = shadow ? "hst_apply_shadow" : "hst_apply_delta";
    const rc = fn(ctx, c, v, c.length, out);
    if (rc !== 0) throw new HstError(`${name} failed`, rc);
    return out;
  }

  /** Apply a sparse delta. Metered against the licence's max_applies. */
  applyDelta(cols, vals) {
    return this.#apply(cols, vals, false);
  }

  /**
   * Shadow-mode apply: identical numerics, metered against max_shadow_applies
   * instead, leaving applies_used untouched. The primitive SHADOW validation is
   * built on: run it beside the real computation, compare against
   * recomputeFull(), change nothing.
   *
   * Use a session opened solely for shadow work. Shadow rights come only from
   * the signed licence token, and a licence without max_shadow_applies fails
   * every call with -4.
   */
  applyShadow(cols, vals) {
    return this.#apply(cols, vals, true);
  }

  /**
   * A copy of the current dense output state, lane-interleaved.
   *
   * The native call returns a borrowed pointer invalidated by the next mutating
   * call, so this copies.
   */
  state() {
    const ctx = this.#live();
    const p = this.#api.hst_state(ctx);
    if (!p) throw new HstError("hst_state returned NULL");
    const view = koffi.decode(p, koffi.array("double", this.stateSize, "Typed"));
    return Float64Array.from(view);
  }

  #set(buf, want, entry, whatWant) {
    const ctx = this.#live();
    const a = buf instanceof Float64Array ? buf : Float64Array.from(buf);
    if (a.length !== want) {
      throw new HstError(`${entry} needs ${whatWant} = ${want} values, got ${a.length}`);
    }
    const rc = entry === "hst_set_state"
      ? this.#api.hst_set_state(ctx, a, want)
      : this.#api.hst_set_input(ctx, a, want);
    if (rc !== 0) throw new HstError(`${entry} failed`, rc);
  }

  /** Prime the held dense output state y. Pair with setInput. */
  setState(y0) {
    this.#set(y0, this.stateSize, "hst_set_state", "stateSize");
  }

  /**
   * Prime the held dense input state x — the buffer recomputeFull computes A*x
   * from. Pair with setState.
   */
  setInput(x0) {
    this.#set(x0, this.inputSize, "hst_set_input", "inputSize");
  }

  /**
   * Recompute the whole dense output from scratch. NOT metered.
   *
   * This is the reference arm — the "before" of a before/after comparison, and
   * the only thing that can tell you the delta path is returning the right
   * numbers. Assert against it every repeat, not once: three defects on one probe
   * in this estate produced clean, well-formed, entirely wrong timings because
   * each arm did the right amount of work with the wrong values.
   */
  recomputeFull() {
    const ctx = this.#live();
    const out = new Float64Array(this.stateSize);
    const rc = this.#api.hst_recompute_full(ctx, out);
    if (rc !== 0) throw new HstError("hst_recompute_full failed", rc);
    return out;
  }

  /** Release the handle. Idempotent. */
  close() {
    if (this.#ctx) {
      this.#api.hst_close(this.#ctx);
      this.#ctx = null;
    }
  }
}

export default { ABI_NODE, SYMBOLS, Session, HstError, load, loadedPath, version, defaultLibraryName };
