using System.Runtime.InteropServices;

namespace HorneSci.Hstcore;

/// <summary>
/// Raw P/Invoke declarations for the HST-core Embedded ABI — the thirteen
/// <c>extern "C"</c> functions of <c>hstcore.h</c>, ABI node <c>HSTCORE_1.4</c>.
/// </summary>
/// <remarks>
/// <para>
/// This package computes nothing. The work is done by <c>libhstcore</c>, a shared
/// library this package does not contain. In an HST Studio download the library is
/// already in <c>bin/</c> (<c>libhstcore.so</c> / <c>libhstcore.dylib</c>), Apache-2.0,
/// unmetered, and needs no key, token or account -- place it where the runtime's native
/// resolver finds it as <c>hstcore</c>, since <c>bin/</c> is not on that search path by
/// default. A separate, metered build of the same library also exists as its own artifact.
/// Install this on its own and the first call throws — there is no evaluation fallback
/// and no managed path. If what you wanted was a sparse delta matvec you can actually
/// run, you want <c>spdelta</c>: Apache-2.0, open, and deliberately the
/// <i>baseline</i> rather than a product.
/// </para>
/// <para>
/// This remark called the library "closed-source ... under a signed licence" without
/// qualification until 2026-08-06, which was true of the metered build and false of
/// the community one shipped beside this binding in the same tree.
/// </para>
/// <para>
/// Thirteen, not twelve. The commit that added <c>hst_apply_shadow</c> described the
/// surface as "12 total"; the version map the linker reads lists thirteen, and both the
/// Python and Rust bindings shipped without <c>hst_set_input</c> because of it. The
/// authority is <c>oss/hstcore-abi/abi.json</c>.
/// </para>
/// <para>
/// <c>LibraryImport</c> rather than <c>DllImport</c>: source-generated marshalling, no
/// runtime reflection, and it works under NativeAOT — which matters because a customer
/// deploying this into an industrial control stack may not have a JIT.
/// </para>
/// </remarks>
internal static partial class Abi
{
    /// <summary>The library name, resolved by the platform's usual search.</summary>
    internal const string Lib = "hstcore";

    /// <summary>The versioned symbol node the library exports.</summary>
    public const string AbiNode = "HSTCORE_1.4";

    /// <summary>Every function in the ABI, in header order.</summary>
    public static readonly string[] Symbols =
    [
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

    [LibraryImport(Lib, EntryPoint = "hst_open", StringMarshalling = StringMarshalling.Utf8)]
    internal static partial IntPtr hst_open(string artifactPath, string licenseToken,
                                            Span<byte> errbuf, nuint errbufLen);

    [LibraryImport(Lib, EntryPoint = "hst_open_batched", StringMarshalling = StringMarshalling.Utf8)]
    internal static partial IntPtr hst_open_batched(string artifactPath, string licenseToken,
                                                    int batch, Span<byte> errbuf, nuint errbufLen);

    [LibraryImport(Lib, EntryPoint = "hst_apply_delta")]
    internal static partial int hst_apply_delta(IntPtr ctx, ReadOnlySpan<int> cols,
                                                ReadOnlySpan<double> vals, int n,
                                                Span<double> yOut);

    [LibraryImport(Lib, EntryPoint = "hst_apply_shadow")]
    internal static partial int hst_apply_shadow(IntPtr ctx, ReadOnlySpan<int> cols,
                                                 ReadOnlySpan<double> vals, int n,
                                                 Span<double> yOut);

    [LibraryImport(Lib, EntryPoint = "hst_batch")]
    internal static partial int hst_batch(IntPtr ctx);

    [LibraryImport(Lib, EntryPoint = "hst_output_dim")]
    internal static partial int hst_output_dim(IntPtr ctx);

    [LibraryImport(Lib, EntryPoint = "hst_input_dim")]
    internal static partial int hst_input_dim(IntPtr ctx);

    [LibraryImport(Lib, EntryPoint = "hst_state")]
    internal static partial IntPtr hst_state(IntPtr ctx);

    [LibraryImport(Lib, EntryPoint = "hst_set_state")]
    internal static partial int hst_set_state(IntPtr ctx, ReadOnlySpan<double> y0, int len);

    [LibraryImport(Lib, EntryPoint = "hst_set_input")]
    internal static partial int hst_set_input(IntPtr ctx, ReadOnlySpan<double> x0, int len);

    [LibraryImport(Lib, EntryPoint = "hst_recompute_full")]
    internal static partial int hst_recompute_full(IntPtr ctx, Span<double> yOut);

    [LibraryImport(Lib, EntryPoint = "hst_close")]
    internal static partial void hst_close(IntPtr ctx);

    [LibraryImport(Lib, EntryPoint = "hst_version")]
    internal static partial IntPtr hst_version();
}
