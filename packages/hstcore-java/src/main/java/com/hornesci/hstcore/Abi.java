package com.hornesci.hstcore;

import java.lang.foreign.Arena;
import java.lang.foreign.FunctionDescriptor;
import java.lang.foreign.Linker;
import java.lang.foreign.MemorySegment;
import java.lang.foreign.SymbolLookup;
import java.lang.invoke.MethodHandle;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_DOUBLE;
import static java.lang.foreign.ValueLayout.JAVA_INT;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * Raw FFI handles for the HST-core Embedded ABI — the thirteen {@code extern "C"}
 * functions of {@code hstcore.h}, exported under ABI node {@code HSTCORE_1.4}.
 *
 * <p><b>Panama, not JNI, deliberately.</b> There is no compile step, no per-platform
 * artifact to publish, and no ABI of this package's own to keep in step with a library
 * the customer receives separately and may replace between releases. JNI would add a
 * native build to every consumer for no benefit: the boundary here carries only
 * {@code int32}, {@code double}, {@code size_t} and opaque pointers.
 *
 * <p><b>This package computes nothing.</b> The work is done by {@code libhstcore}, a
 * shared library this package does not contain. In an HST Studio download the library is
 * already in {@code bin/} ({@code libhstcore.so} / {@code libhstcore.dylib}), Apache-2.0,
 * unmetered, and needs no key, token or account. A separate, metered build of the same library
 * also exists as its own artifact. Install this on its own and the first call throws —
 * there is no evaluation fallback and no pure-Java path. If what you wanted was a sparse
 * delta matvec you can actually run, you want {@code spdelta}: Apache-2.0, open, and
 * deliberately the <i>baseline</i> rather than a product.
 *
 * <p>This javadoc called the library "closed-source ... under a signed licence" without
 * qualification until 2026-08-06, which was true of the metered build and false of the
 * community one shipped beside it in this same tree.
 *
 * <p><b>Thirteen, not twelve.</b> The commit that introduced {@code hst_apply_shadow}
 * described the surface as "12 total"; {@code embedded/exported.linux.map}, which is what
 * the linker reads, lists thirteen. Both the Python and Rust bindings were written from
 * the wrong count and shipped without {@code hst_set_input} until 2026-08-05. The
 * authority is {@code oss/hstcore-abi/abi.json}, and {@code validate.py} fails when a
 * binding does not reference every symbol in it.
 *
 * @see Session for the safe wrapper you should normally use
 */
public final class Abi {

    /** The versioned symbol node the library exports. */
    public static final String ABI_NODE = "HSTCORE_1.4";

    /** Every symbol in the ABI, in header order. Checked against the manifest. */
    public static final List<String> SYMBOLS = List.of(
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
            "hst_version");

    public final MethodHandle hstOpen;
    public final MethodHandle hstOpenBatched;
    public final MethodHandle hstApplyDelta;
    public final MethodHandle hstApplyShadow;
    public final MethodHandle hstBatch;
    public final MethodHandle hstOutputDim;
    public final MethodHandle hstInputDim;
    public final MethodHandle hstState;
    public final MethodHandle hstSetState;
    public final MethodHandle hstSetInput;
    public final MethodHandle hstRecomputeFull;
    public final MethodHandle hstClose;
    public final MethodHandle hstVersion;

    private final String path;

    private Abi(SymbolLookup lookup, String path) {
        this.path = path;
        Linker linker = Linker.nativeLinker();
        List<String> missing = new ArrayList<>();

        // hst_ctx *hst_open(const char*, const char*, char*, size_t)
        hstOpen = bind(linker, lookup, missing, "hst_open",
                FunctionDescriptor.of(ADDRESS, ADDRESS, ADDRESS, ADDRESS, JAVA_LONG));
        // hst_ctx *hst_open_batched(const char*, const char*, int32_t, char*, size_t)
        hstOpenBatched = bind(linker, lookup, missing, "hst_open_batched",
                FunctionDescriptor.of(ADDRESS, ADDRESS, ADDRESS, JAVA_INT, ADDRESS, JAVA_LONG));
        // int hst_apply_delta(hst_ctx*, const int32_t*, const double*, int32_t, double*)
        hstApplyDelta = bind(linker, lookup, missing, "hst_apply_delta",
                FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS, ADDRESS, JAVA_INT, ADDRESS));
        // int hst_apply_shadow(hst_ctx*, const int32_t*, const double*, int32_t, double*)
        hstApplyShadow = bind(linker, lookup, missing, "hst_apply_shadow",
                FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS, ADDRESS, JAVA_INT, ADDRESS));
        hstBatch = bind(linker, lookup, missing, "hst_batch",
                FunctionDescriptor.of(JAVA_INT, ADDRESS));
        hstOutputDim = bind(linker, lookup, missing, "hst_output_dim",
                FunctionDescriptor.of(JAVA_INT, ADDRESS));
        hstInputDim = bind(linker, lookup, missing, "hst_input_dim",
                FunctionDescriptor.of(JAVA_INT, ADDRESS));
        // const double *hst_state(const hst_ctx*)
        hstState = bind(linker, lookup, missing, "hst_state",
                FunctionDescriptor.of(ADDRESS, ADDRESS));
        // int hst_set_state(hst_ctx*, const double*, int32_t)
        hstSetState = bind(linker, lookup, missing, "hst_set_state",
                FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS, JAVA_INT));
        // int hst_set_input(hst_ctx*, const double*, int32_t)
        hstSetInput = bind(linker, lookup, missing, "hst_set_input",
                FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS, JAVA_INT));
        // int hst_recompute_full(hst_ctx*, double*)
        hstRecomputeFull = bind(linker, lookup, missing, "hst_recompute_full",
                FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS));
        // void hst_close(hst_ctx*)
        hstClose = bind(linker, lookup, missing, "hst_close",
                FunctionDescriptor.ofVoid(ADDRESS));
        // const char *hst_version(void)
        hstVersion = bind(linker, lookup, missing, "hst_version",
                FunctionDescriptor.of(ADDRESS));

        if (!missing.isEmpty()) {
            throw new HstException(
                    "%s does not export %d of the %d %s symbols: %s%n%n"
                    .formatted(path, missing.size(), SYMBOLS.size(), ABI_NODE, missing)
                    + "  A library missing hst_apply_shadow or hst_set_input is a STALE "
                    + "BUILD from before the 1.3 -> 1.4 bump, not a different ABI. "
                    + "Replace it with a current one; the library in an HST Studio "
                    + "download's bin/ is current by construction, because the build "
                    + "validates every library it stages against abi.json.");
        }
    }

    private static MethodHandle bind(Linker linker, SymbolLookup lookup, List<String> missing,
                                     String name, FunctionDescriptor fd) {
        return lookup.find(name)
                .map(seg -> linker.downcallHandle(seg, fd))
                .orElseGet(() -> {
                    missing.add(name);
                    return null;
                });
    }

    /** Path the library was loaded from. */
    public String path() {
        return path;
    }

    /**
     * Load {@code libhstcore} from an explicit path.
     *
     * <p>The arena is global on purpose: handles handed out by {@code hst_open} outlive
     * any individual call, and unloading the library underneath them would invalidate
     * them.
     */
    public static Abi load(Path library) {
        String p = library.toAbsolutePath().toString();
        try {
            return new Abi(SymbolLookup.libraryLookup(p, Arena.global()), p);
        } catch (IllegalArgumentException e) {
            throw new HstException(
                    "could not load " + p + ": " + e.getMessage()
                    + ". This package is only the binding; it ships no library. In an "
                    + "HST Studio download the library is in bin/ (libhstcore.so or "
                    + "libhstcore.dylib) -- pass its path to Abi.load, since bin/ is not "
                    + "on the JVM's default library search path.", e);
        }
    }

    /** Load by platform-conventional name, via the dynamic loader's usual search. */
    public static Abi load() {
        return load(Path.of(defaultLibraryName()));
    }

    /** Platform-conventional file name of the shipped library. */
    public static String defaultLibraryName() {
        String os = System.getProperty("os.name", "").toLowerCase();
        if (os.contains("mac") || os.contains("darwin")) return "libhstcore.dylib";
        if (os.contains("win")) return "hstcore.dll";
        return "libhstcore.so";
    }
}
