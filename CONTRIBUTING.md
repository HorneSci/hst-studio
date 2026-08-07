# Contributing

Be honest about the model before you spend an evening on a patch: **this
repository is generated.** A private estate's release pipeline builds this
tree from its own sources and republishes it, so a pull request against these
files edits the output of a build — the next build regenerates it away. We
would rather tell you that here than merge something we cannot keep.

The contribution channel that works, and that we genuinely want, is
**issues** — especially reproduction reports:

- "Your number does not reproduce on my machine" is the most valuable thing
  you can send. Include the `./verify.sh` output and your platform; a failed
  run is more useful to us than a clean one.
- Defects in the scripts, the READMEs, or anything this tree says about
  itself. Corrections land in the templates upstream and appear in the next
  build, dated, not silently.
- Fit questions and workload shapes. "Does HST fit X" reports with a trace
  attached get read.

If you have a patch anyway, attach it to an issue as a diff. We will carry it
into the upstream templates with credit rather than merging it here.
