package com.hornesci.hstcore;

/**
 * Anything the native boundary refused.
 *
 * <p>The negative return codes are documented per function in {@code hstcore.h}; the ones
 * worth recognising by sight:
 *
 * <ul>
 *   <li>{@code -1} bad arguments, or a length that did not match the operator</li>
 *   <li>{@code -2} internal exception inside the library</li>
 *   <li>{@code -3} shadow quota exhausted</li>
 *   <li>{@code -4} the licence carries no shadow-apply grant at all
 *       ({@code max_shadow_applies <= 0}), checked on every shadow call</li>
 *   <li>{@code -5} {@code recomputeFull} refused because the held input and output states
 *       are not known to be consistent — {@code setState} was called without a matching
 *       {@code setInput}, or vice versa</li>
 * </ul>
 *
 * <p>{@code -5} deserves its own note: it is the library declining to return a vector that
 * would disagree with the held state by exactly {@code A*x0}, forever, rather than
 * returning it and letting a caller build a claim on it. That refusal is a feature.
 */
public class HstException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    private final int code;

    public HstException(String message) {
        this(message, 0);
    }

    public HstException(String message, Throwable cause) {
        super(message, cause);
        this.code = 0;
    }

    public HstException(String message, int code) {
        super(code == 0 ? message : message + " (code " + code + explain(code) + ")");
        this.code = code;
    }

    /** The native return code, or 0 when the failure was not a return code. */
    public int code() {
        return code;
    }

    private static String explain(int code) {
        return switch (code) {
            case -1 -> ": bad arguments or length mismatch";
            case -2 -> ": internal exception in libhstcore";
            case -3 -> ": shadow quota exhausted";
            case -4 -> ": licence carries no shadow-apply grant";
            case -5 -> ": input and output states were not primed together — "
                    + "call setState and setInput with the same baseline, or neither";
            default -> "";
        };
    }
}
