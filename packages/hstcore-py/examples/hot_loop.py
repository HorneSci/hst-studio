"""The integration shape, end to end. Needs a licensed libhstcore to run.

    python hot_loop.py /opt/hst/libhstcore.so op.bin "$(cat production.license)"

It does four things worth copying:

* allocates every buffer once, outside the loop, and refills them in place —
  the binding refuses anything that would need converting, so this is not a
  style preference, it is the only shape that compiles;
* keeps the dense output inside the library and reads it back zero-copy;
* checks the delta path against the unmetered from-scratch reference arm before
  trusting a single number out of it;
* runs shadow-mode validation on a *separate* handle, because the two must
  never be interleaved.
"""

from __future__ import annotations

import sys

import numpy as np

import hstcore


def main(lib_path: str, artifact: str, token: str) -> int:
    hstcore.load_library(lib_path)
    print(hstcore.version())

    with hstcore.HSTContext(artifact, token) as ctx:
        print(f"operator N={ctx.output_dim} M={ctx.input_dim} lanes={ctx.batch}")

        n_dirty = 32
        cols = np.empty(n_dirty, dtype=np.int32)
        vals = np.empty(n_dirty, dtype=np.float64)
        reference = np.empty(ctx.state_size, dtype=np.float64)

        rng = np.random.default_rng(7)
        base = int(rng.integers(0, max(1, ctx.input_dim - n_dirty)))

        for step in range(100):
            # In a real integration these come from your own state, written
            # straight into the buffers. No allocation, no conversion.
            cols[:] = np.arange(base, base + n_dirty, dtype=np.int32)
            vals[:] = 0.01 * (step + 1)

            try:
                ctx.apply(cols, vals)
            except hstcore.HSTQuotaError as exc:
                print(f"stopped at step {step}: {exc}")
                break

            if step == 0:
                # The control. Not metered, so it costs nothing but time, and
                # it is the only thing that can tell you the fast path is right.
                ctx.recompute_full(reference)
                y = ctx.state
                if not np.allclose(y, reference.reshape(y.shape), rtol=0, atol=1e-9):
                    print("MISMATCH between the delta path and the full recompute")
                    return 1
                print("delta path agrees with the full recompute")

        y = ctx.state
        print(f"y[0:4] = {np.asarray(y).ravel()[:4]}")

        # Wrong on purpose, to show what the binding stops:
        try:
            ctx.apply([0, 1, 2], [1.0, 2.0, 3.0])
        except hstcore.HSTBufferError as exc:
            print(f"refused a Python list, as designed: {str(exc)[:60]}...")

    # Shadow validation belongs on its own handle. Same artifact, same token,
    # separate hst_ctx — the buffers are shared, so interleaving is not allowed.
    try:
        with hstcore.HSTContext(artifact, token) as shadow:
            shadow.apply_shadow(cols, vals)
            print("shadow apply ok")
    except hstcore.HSTShadowNotGrantedError:
        print("this license carries no shadow-apply grant")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(*sys.argv[1:]))
