// Conformance tests against the shared stub — the same fake libhstcore the
// Python, Java, Go and Rust bindings use, so conformance means the bindings agree
// about ONE library rather than each agreeing with itself.
//
// The stub reports a deliberately NON-SQUARE operator (n=8, m=5), which is what
// makes a stateSize/inputSize confusion detectable. Square fixtures hide it.
//
//   ../hstcore-abi/conformance/build-stub.sh && npm test

import assert from "node:assert/strict";
import test from "node:test";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { Session, SYMBOLS, HstError, load, defaultLibraryName } from "../index.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STUB = path.resolve(HERE, "../../hstcore-abi/conformance/lib", defaultLibraryName());
const TOKEN = "stub-token";

const haveStub = existsSync(STUB);
const skip = haveStub ? false : "shared stub not built — run hstcore-abi/conformance/build-stub.sh";

function open(batch = 1) {
  return Session.open("operator.bin", TOKEN, batch, STUB);
}

test("the symbol list is the whole ABI", () => {
  assert.equal(SYMBOLS.length, 13, "the ABI has thirteen symbols, not twelve");
  for (const s of ["hst_set_input", "hst_apply_shadow", "hst_recompute_full"]) {
    assert.ok(SYMBOLS.includes(s), `SYMBOLS is missing ${s}`);
  }
});

test("loading a library resolves every symbol", { skip }, () => {
  const api = load(STUB);
  for (const s of SYMBOLS) {
    assert.equal(typeof api[s], "function", `${s} did not bind`);
  }
});

test("dimensions come from the library", { skip }, () => {
  const s = open(4);
  try {
    assert.equal(s.outputDim, 8);
    assert.equal(s.inputDim, 5);
    assert.equal(s.batch, 4);
  } finally {
    s.close();
  }
});

test("stateSize and inputSize differ on a non-square operator", { skip }, () => {
  const s = open(4);
  try {
    assert.equal(s.stateSize, 32, "outputDim * batch");
    assert.equal(s.inputSize, 20, "inputDim * batch");
    assert.notEqual(s.stateSize, s.inputSize,
      "the stub is supposed to be non-square; that is what makes the confusion detectable");
  } finally {
    s.close();
  }
});

test("vals must be cols.length * batch", { skip }, () => {
  const s = open(4);
  try {
    assert.throws(() => s.applyDelta([0, 1], [1.0]), HstError,
      "a wrong-length vals array was accepted; values are lane-interleaved");
    const out = s.applyDelta([0, 2, 4], new Float64Array(12));
    assert.equal(out.length, s.stateSize);
  } finally {
    s.close();
  }
});

test("setState and setInput want different lengths", { skip }, () => {
  const s = open(4);
  try {
    s.setState(new Float64Array(s.stateSize));
    assert.throws(() => s.setState(new Float64Array(s.inputSize)), HstError,
      "setState accepted inputSize");
    s.setInput(new Float64Array(s.inputSize));
    assert.throws(() => s.setInput(new Float64Array(s.stateSize)), HstError,
      "setInput accepted stateSize");
  } finally {
    s.close();
  }
});

test("state() copies rather than aliasing library memory", { skip }, () => {
  const s = open(4);
  try {
    const prime = Float64Array.from({ length: s.stateSize }, (_, i) => i);
    s.setState(prime);
    const first = s.state();
    assert.equal(first.length, s.stateSize);
    first[0] = -12345;
    const second = s.state();
    assert.notEqual(second[0], -12345,
      "state() aliases library memory; it must copy, because the native pointer is " +
      "invalidated by the next mutating call");
  } finally {
    s.close();
  }
});

test("recomputeFull returns stateSize values", { skip }, () => {
  const s = open(4);
  try {
    assert.equal(s.recomputeFull().length, s.stateSize);
  } finally {
    s.close();
  }
});

test("shadow apply is reachable", { skip }, () => {
  const s = open(4);
  try {
    assert.equal(s.applyShadow([0, 2, 4], new Float64Array(12)).length, s.stateSize);
  } finally {
    s.close();
  }
});

test("close is idempotent and use-after-close is refused", { skip }, () => {
  const s = open(1);
  s.close();
  s.close();
  assert.throws(() => s.state(), HstError);
});

test("batch outside 1..32 is rejected before the native call", () => {
  for (const bad of [0, 33, 1.5, -1]) {
    assert.throws(() => Session.open("operator.bin", TOKEN, bad, STUB), RangeError,
      `batch=${bad} was accepted`);
  }
});

test("error codes explain themselves", () => {
  assert.match(new HstError("x", -3).message, /shadow quota exhausted/);
  assert.match(new HstError("x", -4).message, /no shadow-apply grant/);
  assert.match(new HstError("x", -5).message, /primed together/);
});
