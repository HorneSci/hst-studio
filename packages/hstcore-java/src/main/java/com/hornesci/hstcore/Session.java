package com.hornesci.hstcore;

import java.lang.foreign.Arena;
import java.lang.foreign.MemorySegment;
import java.nio.file.Path;

import static java.lang.foreign.ValueLayout.JAVA_DOUBLE;
import static java.lang.foreign.ValueLayout.JAVA_INT;

/**
 * A live HST session: a compiled operator plus the dense state evolving under it.
 *
 * <p>Everything here is in-process. The measured reason that matters: putting a network
 * hop in front of this destroys the win outright, so there is no client/server mode to
 * reach for by mistake.
 *
 * <h2>Lane interleaving</h2>
 *
 * With {@code batch > 1}, every state-shaped and value-shaped buffer is
 * <b>lane-interleaved</b>: element {@code i} of lane {@code b} lives at
 * {@code buf[i * batch + b]}, <i>not</i> at {@code buf[b * n + i]}. This is the single
 * most commonly mis-bound detail in this ABI, and getting it wrong produces plausible
 * numbers that are wrong — the failure class that costs the most to find later.
 *
 * <h2>Two rules the library enforces so you cannot quietly break them</h2>
 *
 * <ol>
 *   <li><b>{@link #setState} and {@link #setInput} go together.</b> They prime different
 *       buffers — the output {@code y} and the input {@code x} that {@link #recomputeFull}
 *       computes {@code A*x} from. Prime one alone and {@code recomputeFull} refuses with
 *       {@code -5} rather than return a vector that disagrees with {@code y} by exactly
 *       {@code A*x0} forever. Leaving both pristine is also consistent.</li>
 *   <li><b>Shadow and production applies must not share a handle.</b>
 *       {@link #applyShadow} has identical numerics to {@link #applyDelta} but meters
 *       against a different budget, and the two share held state. Open a separate session
 *       for shadow validation. This class cannot enforce that across instances, so it is
 *       said here and in {@code abi.json}.</li>
 * </ol>
 *
 * <p>Not thread-safe. One session, one thread, or your own lock.
 */
public final class Session implements AutoCloseable {

    private final Abi abi;
    private final Arena arena;
    private MemorySegment ctx;
    private final int outputDim;
    private final int inputDim;
    private final int batch;

    private Session(Abi abi, MemorySegment ctx) {
        this.abi = abi;
        this.ctx = ctx;
        this.arena = Arena.ofShared();
        try {
            this.batch = (int) abi.hstBatch.invokeExact(ctx);
            this.outputDim = (int) abi.hstOutputDim.invokeExact(ctx);
            this.inputDim = (int) abi.hstInputDim.invokeExact(ctx);
        } catch (Throwable t) {
            throw new HstException("could not read session dimensions", t);
        }
        if (outputDim <= 0 || inputDim <= 0 || batch <= 0) {
            close();
            throw new HstException("library reported a nonsensical shape: output=" + outputDim
                    + " input=" + inputDim + " batch=" + batch);
        }
    }

    /** Open a single-lane session. */
    public static Session open(Abi abi, Path artifact, String licenseToken) {
        return open(abi, artifact, licenseToken, 1);
    }

    /**
     * Open a session with {@code batch} independent right-hand-side lanes (1..32), all
     * evolving under the same operator and the same delta sparsity pattern.
     *
     * <p>Batching amortizes the sparse index traversal across lanes, which is where HST
     * beats a plain exact column delta. At {@code batch == 1} it frequently does not —
     * measure before assuming.
     */
    public static Session open(Abi abi, Path artifact, String licenseToken, int batch) {
        if (batch < 1 || batch > 32) {
            throw new IllegalArgumentException("batch must be 1..32, got " + batch);
        }
        try (Arena tmp = Arena.ofConfined()) {
            MemorySegment path = tmp.allocateFrom(artifact.toAbsolutePath().toString());
            MemorySegment token = tmp.allocateFrom(licenseToken);
            MemorySegment errbuf = tmp.allocate(512);
            errbuf.set(java.lang.foreign.ValueLayout.JAVA_BYTE, 0, (byte) 0);

            MemorySegment handle;
            try {
                handle = batch == 1
                        ? (MemorySegment) abi.hstOpen.invokeExact(path, token, errbuf, 512L)
                        : (MemorySegment) abi.hstOpenBatched.invokeExact(
                                path, token, batch, errbuf, 512L);
            } catch (Throwable t) {
                throw new HstException("hst_open threw at the native boundary", t);
            }
            if (handle == null || handle.address() == 0) {
                throw new HstException("hst_open failed: " + errbuf.getString(0)
                        + " (artifact=" + artifact + ")");
            }
            return new Session(abi, handle);
        }
    }

    /** Output dimension N of the operator (rows). */
    public int outputDim() {
        return outputDim;
    }

    /** Input dimension M of the operator (columns). */
    public int inputDim() {
        return inputDim;
    }

    /** Number of right-hand-side lanes. */
    public int batch() {
        return batch;
    }

    /** {@code outputDim * batch} — the length of every state-shaped buffer. */
    public int stateSize() {
        return outputDim * batch;
    }

    /**
     * {@code inputDim * batch} — the length {@link #setInput} requires.
     *
     * <p>Differs from {@link #stateSize} on any non-square operator, which is exactly why
     * {@code setInput} cannot reuse the state length.
     */
    public int inputSize() {
        return inputDim * batch;
    }

    /**
     * Apply a sparse delta. Column {@code cols[i]} changes by {@code vals[i * batch + b]}
     * in lane {@code b}.
     *
     * <p>Metered against the licence's {@code max_applies}.
     *
     * @return the updated dense output, length {@link #stateSize}
     */
    public double[] applyDelta(int[] cols, double[] vals) {
        return apply(abi.hstApplyDelta, "hst_apply_delta", cols, vals);
    }

    /**
     * Shadow-mode apply: identical numerics, metered against the licence's
     * {@code max_shadow_applies} instead, and it does not touch {@code applies_used}.
     *
     * <p>This is the primitive SHADOW validation is built on: run it beside the real
     * computation, compare against {@link #recomputeFull}, change nothing.
     *
     * <p><b>Use a session opened solely for shadow work.</b> Shadow rights come only from
     * the signed licence token — no argument, environment variable or flag can grant them,
     * and a licence without {@code max_shadow_applies} fails every call with {@code -4}.
     */
    public double[] applyShadow(int[] cols, double[] vals) {
        return apply(abi.hstApplyShadow, "hst_apply_shadow", cols, vals);
    }

    private double[] apply(java.lang.invoke.MethodHandle fn, String name,
                           int[] cols, double[] vals) {
        MemorySegment h = live();
        if (cols == null || vals == null) {
            throw new IllegalArgumentException("cols and vals must not be null");
        }
        if (vals.length != cols.length * batch) {
            throw new IllegalArgumentException(
                    "vals must be cols.length * batch = " + cols.length + " * " + batch
                    + " = " + (cols.length * batch) + ", got " + vals.length
                    + ". Values are LANE-INTERLEAVED: vals[i * batch + b].");
        }
        try (Arena tmp = Arena.ofConfined()) {
            MemorySegment c = tmp.allocateFrom(JAVA_INT, cols);
            MemorySegment v = tmp.allocateFrom(JAVA_DOUBLE, vals);
            MemorySegment out = tmp.allocate(JAVA_DOUBLE, stateSize());
            int rc;
            try {
                rc = (int) fn.invokeExact(h, c, v, cols.length, out);
            } catch (Throwable t) {
                throw new HstException(name + " threw at the native boundary", t);
            }
            if (rc != 0) throw new HstException(name + " failed", rc);
            return out.toArray(JAVA_DOUBLE);
        }
    }

    /**
     * A copy of the current dense output state, lane-interleaved.
     *
     * <p>The native call returns a borrowed pointer invalidated by the next mutating
     * call, so this copies. A binding that handed the raw view to Java would produce a
     * segment whose contents change under the reader.
     */
    public double[] state() {
        MemorySegment h = live();
        MemorySegment p;
        try {
            p = (MemorySegment) abi.hstState.invokeExact(h);
        } catch (Throwable t) {
            throw new HstException("hst_state threw at the native boundary", t);
        }
        if (p == null || p.address() == 0) throw new HstException("hst_state returned NULL");
        return p.reinterpret((long) stateSize() * Double.BYTES).toArray(JAVA_DOUBLE);
    }

    /**
     * Prime the held dense <b>output</b> state y.
     *
     * <p><b>Pair with {@link #setInput}</b> using the same baseline — see the class note.
     */
    public void setState(double[] y0) {
        set(abi.hstSetState, "hst_set_state", y0, stateSize(), "stateSize");
    }

    /**
     * Prime the held dense <b>input</b> state x — the buffer {@link #recomputeFull}
     * computes {@code A*x} from.
     *
     * <p>There is otherwise no way to set it other than accumulating it one apply at a
     * time from a pristine zero start. <b>Pair with {@link #setState}.</b>
     */
    public void setInput(double[] x0) {
        set(abi.hstSetInput, "hst_set_input", x0, inputSize(), "inputSize");
    }

    private void set(java.lang.invoke.MethodHandle fn, String name,
                     double[] buf, int want, String whatWant) {
        MemorySegment h = live();
        if (buf == null) throw new IllegalArgumentException("buffer must not be null");
        if (buf.length != want) {
            throw new IllegalArgumentException(
                    name + " needs " + whatWant + " = " + want + " values, got " + buf.length);
        }
        try (Arena tmp = Arena.ofConfined()) {
            MemorySegment seg = tmp.allocateFrom(JAVA_DOUBLE, buf);
            int rc;
            try {
                rc = (int) fn.invokeExact(h, seg, want);
            } catch (Throwable t) {
                throw new HstException(name + " threw at the native boundary", t);
            }
            if (rc != 0) throw new HstException(name + " failed", rc);
        }
    }

    /**
     * Recompute the whole dense output from scratch. <b>Not metered.</b>
     *
     * <p>This is the reference arm — the "before" of a before/after comparison, and the
     * only thing that can tell you the delta path is returning the right numbers. Assert
     * against it every repeat, not once at the start: three defects on one probe in this
     * estate produced clean, well-formed, entirely wrong timings because each arm did the
     * right <i>amount</i> of work with the wrong values.
     *
     * @throws HstException with code {@code -5} if the held input and output states were
     *         not primed together
     */
    public double[] recomputeFull() {
        MemorySegment h = live();
        try (Arena tmp = Arena.ofConfined()) {
            MemorySegment out = tmp.allocate(JAVA_DOUBLE, stateSize());
            int rc;
            try {
                rc = (int) abi.hstRecomputeFull.invokeExact(h, out);
            } catch (Throwable t) {
                throw new HstException("hst_recompute_full threw at the native boundary", t);
            }
            if (rc != 0) throw new HstException("hst_recompute_full failed", rc);
            return out.toArray(JAVA_DOUBLE);
        }
    }

    /** Library version string. */
    public String version() {
        try {
            MemorySegment p = (MemorySegment) abi.hstVersion.invokeExact();
            return (p == null || p.address() == 0) ? "" : p.reinterpret(Long.MAX_VALUE).getString(0);
        } catch (Throwable t) {
            throw new HstException("hst_version threw at the native boundary", t);
        }
    }

    private MemorySegment live() {
        if (ctx == null) throw new HstException("session is closed; open a new one");
        return ctx;
    }

    /** Release the handle. Idempotent. */
    @Override
    public void close() {
        if (ctx != null) {
            try {
                abi.hstClose.invokeExact(ctx);
            } catch (Throwable t) {
                // hst_close is documented safe and returns void; swallowing here keeps
                // close() usable from a finally block, which is where it belongs.
            }
            ctx = null;
        }
        if (arena != null) {
            try {
                arena.close();
            } catch (IllegalStateException ignored) {
                // already closed
            }
        }
    }
}
