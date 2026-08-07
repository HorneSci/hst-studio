# Security

Report vulnerabilities to **ericspencer1450@gmail.com**. Include what you
found, how to reproduce it, and what you think it reaches. We reply from the
same address; there is no bounty programme.

What you can verify about this tree today:

- `SHA256SUMS` at the root covers every file in `bin/` plus `install.sh` and
  `verify.sh`; `shasum -a 256 -c SHA256SUMS` checks it, and `./verify.sh` runs
  that check first.
- Nothing in this tree contacts a server, at install time or after; the only
  outbound traffic is pip talking to your index.

A known gap, stated rather than implied away: **there is no build attestation
for the binaries.** The runtime libraries are built on our own private
hardware, not in a public CI run, so the checksums prove what you received
matches what we published — they do not prove how it was built. If your threat
model needs provenance beyond that, this download does not provide it yet.
