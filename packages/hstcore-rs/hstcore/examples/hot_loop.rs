//! The integration shape, end to end. Needs a licensed `libhstcore` to run.
//!
//! ```text
//! cargo run --example hot_loop -- /opt/hst/libhstcore.so op.bin "$(cat production.license)"
//! ```
//!
//! Four things here are worth copying: buffers allocated once and refilled in
//! place; the dense output left inside the library and read back zero-copy; the
//! delta path checked against the unmetered from-scratch reference arm before
//! anything is believed; and shadow validation on a session that can no longer
//! be used for production, because the conversion consumed it.

use hstcore::{Error, Library};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        eprintln!("usage: {} <libhstcore> <op.bin> <license-token>", args[0]);
        std::process::exit(2);
    }

    // Safety: the operator is pointing this at a library they chose.
    let lib = unsafe { Library::open_at(&args[1])? };
    println!("{}", lib.version()?);

    let mut session = lib.open(std::path::Path::new(&args[2]), &args[3])?;
    println!(
        "operator N={} M={} lanes={}",
        session.output_dim(),
        session.input_dim(),
        session.batch()
    );

    // Allocated once. Nothing in the loop below allocates or converts.
    let dirty = 32usize.min(session.input_dim() as usize);
    let cols: Vec<i32> = (0..dirty as i32).collect();
    let mut vals = vec![0.0f64; dirty];
    let mut reference = vec![0.0f64; session.state_len()];

    for step in 0..100 {
        for value in vals.iter_mut() {
            *value = 0.01 * (step + 1) as f64;
        }

        match session.apply(&cols, &vals) {
            Ok(()) => {}
            Err(Error::QuotaExhausted { .. }) => {
                println!("apply budget spent at step {step}");
                break;
            }
            Err(other) => return Err(other.into()),
        }

        if step == 0 {
            // The control. Not metered, and the only thing that can tell you
            // the fast path is returning the right numbers.
            session.recompute_full(&mut reference)?;
            let y = session.state();
            let worst = y
                .iter()
                .zip(reference.iter())
                .map(|(a, b)| (a - b).abs())
                .fold(0.0f64, f64::max);
            if worst > 1e-9 {
                eprintln!("delta path disagrees with the full recompute by {worst:e}");
                return Ok(());
            }
            println!("delta path agrees with the full recompute");
        }
    }

    let head: Vec<f64> = session.state().iter().take(4).copied().collect();
    println!("y[0..4] = {head:?}");

    // Shadow validation. `into_shadow` consumes the session on purpose: the two
    // kinds of apply share held buffers and must never be interleaved, so after
    // this line the production entry point is not reachable from `shadow`.
    let mut shadow = session.into_shadow();
    match shadow.apply(&cols, &vals) {
        Ok(()) => println!("shadow apply ok"),
        Err(Error::ShadowNotGranted) => println!("this license carries no shadow-apply grant"),
        Err(other) => return Err(other.into()),
    }

    Ok(())
}
