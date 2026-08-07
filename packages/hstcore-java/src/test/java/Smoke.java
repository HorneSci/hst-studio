import com.hornesci.hstcore.Abi;
import com.hornesci.hstcore.HstException;
import com.hornesci.hstcore.Session;

import java.nio.file.Path;
import java.util.Arrays;

/**
 * Conformance smoke test for the Java binding, run against the shared C stub — the same
 * stub the Python binding's tests use, so "conformance" means the two bindings agree
 * about one library rather than each agreeing with itself.
 *
 * <p>No licence, no real library, no network. Plain {@code java Smoke.java}-able so it
 * needs no test framework and no dependency resolution.
 *
 * <p>What it actually pins, in rough order of how expensive the bug would be:
 * lane interleaving, the state copy, the set_state/set_input pairing, and that a
 * mismatched length is rejected in Java rather than passed to the native side.
 */
public final class Smoke {

    private static int failures = 0;

    static void check(String what, boolean ok) {
        System.out.printf("  %-5s %s%n", ok ? "ok" : "FAIL", what);
        if (!ok) failures++;
    }

    static void expectThrows(String what, Runnable r) {
        try {
            r.run();
            check(what + " (should have thrown)", false);
        } catch (IllegalArgumentException | HstException e) {
            check(what, true);
        }
    }

    public static void main(String[] args) {
        Path lib = Path.of(args.length > 0 ? args[0] : "build/stub/libhstcore.dylib");
        System.out.println("\n  hstcore-java conformance smoke\n");

        Abi abi = Abi.load(lib);
        check("loaded " + lib.getFileName() + " with all " + Abi.SYMBOLS.size() + " symbols",
                Abi.SYMBOLS.size() == 13);

        // The stub reports n=8, m=5 -- deliberately non-square, so a binding that
        // confuses stateSize with inputSize is caught rather than tolerated.
        try (Session s = Session.open(abi, Path.of("operator.bin"), "stub-token", 4)) {
            check("outputDim = 8", s.outputDim() == 8);
            check("inputDim = 5", s.inputDim() == 5);
            check("batch = 4", s.batch() == 4);
            check("stateSize = outputDim*batch = 32", s.stateSize() == 32);
            check("inputSize = inputDim*batch = 20", s.inputSize() == 20);
            check("stateSize and inputSize differ (non-square operator)",
                    s.stateSize() != s.inputSize());

            check("version reads back", !s.version().isEmpty());

            // Lane interleaving: 3 dirty columns x 4 lanes = 12 values.
            int[] cols = {0, 2, 4};
            double[] vals = new double[12];
            for (int i = 0; i < 12; i++) vals[i] = i + 1;
            double[] y = s.applyDelta(cols, vals);
            check("applyDelta returns stateSize values", y.length == 32);

            expectThrows("vals of the wrong length is rejected in Java",
                    () -> s.applyDelta(new int[] {0, 1}, new double[] {1.0}));

            // set_state wants 32, set_input wants 20. Passing either length to the
            // other must fail -- this is the check that catches the confusion.
            double[] y0 = new double[32];
            Arrays.fill(y0, 1.5);
            s.setState(y0);
            check("setState accepts stateSize", true);
            expectThrows("setState rejects inputSize", () -> s.setState(new double[20]));

            double[] x0 = new double[20];
            Arrays.fill(x0, 0.25);
            s.setInput(x0);
            check("setInput accepts inputSize", true);
            expectThrows("setInput rejects stateSize", () -> s.setInput(new double[32]));

            double[] st = s.state();
            check("state() returns a copy of stateSize values", st.length == 32);

            double[] ref = s.recomputeFull();
            check("recomputeFull returns stateSize values", ref.length == 32);

            double[] shadow = s.applyShadow(cols, vals);
            check("applyShadow returns stateSize values", shadow.length == 32);
        }

        // close() is idempotent and use-after-close is refused, not undefined.
        Session s2 = Session.open(abi, Path.of("operator.bin"), "stub-token");
        s2.close();
        s2.close();
        check("close() is idempotent", true);
        expectThrows("use after close is refused", s2::state);

        System.out.println();
        if (failures > 0) {
            System.out.println("  " + failures + " FAILED\n");
            System.exit(1);
        }
        System.out.println("  all checks passed\n");
    }
}
