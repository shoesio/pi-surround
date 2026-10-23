# Contributing

Please describe the trigger, expected result, actual result, hardware, package
versions and timing profile. Distinguish observed logs from inferred acoustic
behaviour. A service's `playing=true` flag is not proof of audible output.

Use `make check` before submitting source changes. Do not run installation or
audio tests on someone else's active playback without their permission.

Keep credentials, output IDs, addresses, device names, pairing files, databases
and captured programme audio out of issues and patches. See SECURITY.md.

Changes to delay, clock correction, queue limits or route ownership need a
specific failure case and a rollback plan. Test startup, pause, seek/resume,
format changes and volume together; a fix to one can break another.

Contributions to our original files are under GPL-2.0-or-later. Upstream-derived
changes must retain the applicable upstream licence. This repository's patches
are local changes, not claims that the upstream projects have accepted them.
