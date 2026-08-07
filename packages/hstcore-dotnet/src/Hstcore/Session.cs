using System.Runtime.InteropServices;

namespace HorneSci.Hstcore;

/// <summary>Anything the native boundary refused.</summary>
public sealed class HstException : Exception
{
    /// <summary>The native return code, or 0 when the failure was not a return code.</summary>
    public int Code { get; }

    public HstException(string message) : base(message) { }

    public HstException(string message, int code)
        : base(code == 0 ? message : $"{message} (code {code}{Explain(code)})") => Code = code;

    private static string Explain(int code) => code switch
    {
        -1 => ": bad arguments or length mismatch",
        -2 => ": internal exception in libhstcore",
        -3 => ": shadow quota exhausted",
        -4 => ": licence carries no shadow-apply grant",
        -5 => ": input and output states were not primed together — call SetState and "
              + "SetInput with the same baseline, or neither",
        _ => "",
    };
}

/// <summary>
/// A live HST session: a compiled operator plus the dense state evolving under it.
/// </summary>
/// <remarks>
/// <para>
/// Everything here is in-process. Putting a network hop in front of it destroys the win
/// outright, which is why there is no client mode to reach for by mistake.
/// </para>
/// <para>
/// <b>Lane interleaving.</b> With <c>batch &gt; 1</c> every state-shaped and value-shaped
/// buffer is lane-interleaved: element <c>i</c> of lane <c>b</c> is at
/// <c>buf[i * batch + b]</c>, <i>not</i> <c>buf[b * n + i]</c>. This is the most commonly
/// mis-bound detail in this ABI, and getting it wrong yields plausible numbers that are
/// wrong.
/// </para>
/// <para>
/// <b>Two rules.</b> (1) <see cref="SetState"/> and <see cref="SetInput"/> go together —
/// they prime different buffers, and priming one alone makes
/// <see cref="RecomputeFull"/> refuse with <c>-5</c> rather than return a vector that
/// disagrees with the held state by exactly <c>A*x0</c> forever. (2) Shadow and production
/// applies must not share a session.
/// </para>
/// <para>Not thread-safe. One session, one thread, or your own lock.</para>
/// </remarks>
public sealed class Session : IDisposable
{
    private IntPtr _ctx;

    /// <summary>Output dimension N of the operator (rows).</summary>
    public int OutputDim { get; }

    /// <summary>Input dimension M of the operator (columns).</summary>
    public int InputDim { get; }

    /// <summary>Number of right-hand-side lanes.</summary>
    public int Batch { get; }

    /// <summary><c>OutputDim * Batch</c> — the length of every state-shaped buffer.</summary>
    public int StateSize => OutputDim * Batch;

    /// <summary>
    /// <c>InputDim * Batch</c> — the length <see cref="SetInput"/> requires. Differs from
    /// <see cref="StateSize"/> on any non-square operator, which is why SetInput cannot
    /// reuse the state length.
    /// </summary>
    public int InputSize => InputDim * Batch;

    private Session(IntPtr ctx)
    {
        _ctx = ctx;
        Batch = Abi.hst_batch(ctx);
        OutputDim = Abi.hst_output_dim(ctx);
        InputDim = Abi.hst_input_dim(ctx);
        if (OutputDim <= 0 || InputDim <= 0 || Batch <= 0)
        {
            Dispose();
            throw new HstException(
                $"library reported a nonsensical shape: output={OutputDim} "
                + $"input={InputDim} batch={Batch}");
        }
    }

    /// <summary>Open a single-lane session.</summary>
    public static Session Open(string artifactPath, string licenseToken)
        => Open(artifactPath, licenseToken, 1);

    /// <summary>
    /// Open a session with <paramref name="batch"/> independent right-hand-side lanes
    /// (1..32) under the same operator and the same delta sparsity pattern.
    /// </summary>
    /// <remarks>
    /// Batching amortizes the sparse index traversal across lanes, which is where HST beats
    /// a plain exact column delta. At <c>batch == 1</c> it frequently does not — measure
    /// before assuming.
    /// </remarks>
    public static Session Open(string artifactPath, string licenseToken, int batch)
    {
        if (batch is < 1 or > 32)
            throw new ArgumentOutOfRangeException(nameof(batch), batch, "must be 1..32");

        var errbuf = new byte[512];
        IntPtr ctx = batch == 1
            ? Abi.hst_open(artifactPath, licenseToken, errbuf, (nuint)errbuf.Length)
            : Abi.hst_open_batched(artifactPath, licenseToken, batch, errbuf, (nuint)errbuf.Length);

        if (ctx == IntPtr.Zero)
        {
            int len = Array.IndexOf(errbuf, (byte)0);
            string reason = System.Text.Encoding.UTF8.GetString(errbuf, 0, len < 0 ? 0 : len);
            throw new HstException($"hst_open failed: {reason} (artifact={artifactPath})");
        }
        return new Session(ctx);
    }

    /// <summary>Library version string.</summary>
    public static string Version()
        => Marshal.PtrToStringUTF8(Abi.hst_version()) ?? "";

    /// <summary>
    /// Apply a sparse delta. Column <c>cols[i]</c> changes by <c>vals[i * Batch + b]</c>
    /// in lane <c>b</c>. Metered against the licence's <c>max_applies</c>.
    /// </summary>
    public double[] ApplyDelta(ReadOnlySpan<int> cols, ReadOnlySpan<double> vals)
        => Apply(cols, vals, shadow: false);

    /// <summary>
    /// Shadow-mode apply: identical numerics, metered against
    /// <c>max_shadow_applies</c> instead, leaving <c>applies_used</c> untouched.
    /// </summary>
    /// <remarks>
    /// This is the primitive SHADOW validation is built on: run it beside the real
    /// computation, compare against <see cref="RecomputeFull"/>, change nothing. Use a
    /// session opened solely for shadow work — shadow rights come only from the signed
    /// licence token, and a licence without <c>max_shadow_applies</c> fails every call
    /// with <c>-4</c>.
    /// </remarks>
    public double[] ApplyShadow(ReadOnlySpan<int> cols, ReadOnlySpan<double> vals)
        => Apply(cols, vals, shadow: true);

    private double[] Apply(ReadOnlySpan<int> cols, ReadOnlySpan<double> vals, bool shadow)
    {
        IntPtr ctx = Live();
        if (vals.Length != cols.Length * Batch)
            throw new ArgumentException(
                $"vals must be cols.Length * Batch = {cols.Length} * {Batch} = "
                + $"{cols.Length * Batch}, got {vals.Length}. Values are LANE-INTERLEAVED: "
                + "vals[i * batch + b].", nameof(vals));

        var outBuf = new double[StateSize];
        int rc = shadow
            ? Abi.hst_apply_shadow(ctx, cols, vals, cols.Length, outBuf)
            : Abi.hst_apply_delta(ctx, cols, vals, cols.Length, outBuf);
        if (rc != 0)
            throw new HstException(shadow ? "hst_apply_shadow failed" : "hst_apply_delta failed", rc);
        return outBuf;
    }

    /// <summary>
    /// A copy of the current dense output state, lane-interleaved.
    /// </summary>
    /// <remarks>
    /// The native call returns a borrowed pointer invalidated by the next mutating call,
    /// so this copies rather than wrapping library memory in a managed array.
    /// </remarks>
    public double[] State()
    {
        IntPtr ctx = Live();
        IntPtr p = Abi.hst_state(ctx);
        if (p == IntPtr.Zero) throw new HstException("hst_state returned NULL");
        var outBuf = new double[StateSize];
        Marshal.Copy(p, outBuf, 0, StateSize);
        return outBuf;
    }

    /// <summary>Prime the held dense <b>output</b> state y. Pair with <see cref="SetInput"/>.</summary>
    public void SetState(ReadOnlySpan<double> y0)
    {
        IntPtr ctx = Live();
        Require(y0.Length, StateSize, "hst_set_state", nameof(StateSize));
        int rc = Abi.hst_set_state(ctx, y0, StateSize);
        if (rc != 0) throw new HstException("hst_set_state failed", rc);
    }

    /// <summary>
    /// Prime the held dense <b>input</b> state x — the buffer <see cref="RecomputeFull"/>
    /// computes <c>A*x</c> from. Pair with <see cref="SetState"/>.
    /// </summary>
    public void SetInput(ReadOnlySpan<double> x0)
    {
        IntPtr ctx = Live();
        Require(x0.Length, InputSize, "hst_set_input", nameof(InputSize));
        int rc = Abi.hst_set_input(ctx, x0, InputSize);
        if (rc != 0) throw new HstException("hst_set_input failed", rc);
    }

    private static void Require(int got, int want, string entry, string whatWant)
    {
        if (got != want)
            throw new ArgumentException($"{entry} needs {whatWant} = {want} values, got {got}");
    }

    /// <summary>
    /// Recompute the whole dense output from scratch. <b>Not metered.</b>
    /// </summary>
    /// <remarks>
    /// This is the reference arm — the "before" of a before/after comparison, and the only
    /// thing that can tell you the delta path is returning the right numbers. Assert
    /// against it every repeat, not once: three defects on one probe in this estate
    /// produced clean, well-formed, entirely wrong timings because each arm did the right
    /// <i>amount</i> of work with the wrong values.
    /// </remarks>
    public double[] RecomputeFull()
    {
        IntPtr ctx = Live();
        var outBuf = new double[StateSize];
        int rc = Abi.hst_recompute_full(ctx, outBuf);
        if (rc != 0) throw new HstException("hst_recompute_full failed", rc);
        return outBuf;
    }

    private IntPtr Live()
        => _ctx != IntPtr.Zero ? _ctx : throw new HstException("session is closed; open a new one");

    /// <summary>Release the handle. Idempotent.</summary>
    public void Dispose()
    {
        if (_ctx != IntPtr.Zero)
        {
            Abi.hst_close(_ctx);
            _ctx = IntPtr.Zero;
        }
    }
}
