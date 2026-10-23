# Local release review — 23 October 2026

## Scope

Source preview 0.1.0-preview.1, prepared from the retained 500 ms checkpoint.
Nothing was published, sent upstream, installed on the Pi or restarted during
this preparation. Private recovery bundles remain separate and unchanged.

Files were selected by allowlist from the application checkpoint. Raw private
settings, paired databases, venvs, executables, runtime records, recordings,
firmware and reverse-engineering caches were excluded. Original source IDs were
moved to private settings; the templates use placeholders/documentation values.

## Checks performed

- Six device-free regression tests: commissioning defaults and identity
  validation; scanner rejection of a synthetic private payload; rear invariance
  across the front-correlation boundary; very small samples surviving gain;
  silence and soft-limited hot input remaining bounded.
- Native mixer and gain-ramp libraries compiled locally with warnings treated
  as errors. These local test binaries are excluded from the release.
- Both source patches applied to freshly fetched pinned upstream bases.
  All 14 affected source files matched the retained source trees, apart from
  OwnTone's added dated modification notices.
- NQPTP 1.2.8: 16 source/build inputs matched the official tag, and its built
  executable matched the installed executable. Its unmodified source is fetched
  separately rather than vendored.
- Installed pyatv: all 173 Python source files matched its published 0.18.0
  wheel. No private dependency fork is required.
- Python syntax, example JSON, shell syntax and local documentation links were
  checked. Local import dependencies resolve to supplied files, standard Python,
  declared pyatv or system NumPy.
- Public files compared against the private credential and device-identity
  values without displaying those values; no matches found.
- A publication scanner checked for literal hardware addresses, personal Mac
  paths, non-documentation IP addresses, private-key markers and excluded file
  types. This is a targeted check, not a universal proof of absence of secrets.
- Packaged source files have checksums; archive verification excludes build
  products, Git metadata and private working directories.

## Licence/provenance review

The release retains upstream notices, GPLv2 text and component credits. The
OwnTone patch marks modified files with a date. Shairport's per-file exceptions
are documented. Only our original integration contributions receive the project
GPL-2.0-or-later notice. Dependencies are fetched rather than repackaged as
binaries. The review does not certify all patent/trademark questions, and any
future binary/image distribution needs a fresh dependency/licence review.

## Before public launch

1. Owner reviews naming, licence choice, technical claims and documentation.
2. Choose repository ownership and enable a private security-reporting channel;
   SECURITY.md currently explains that one has not been configured.
3. Commission the sanitized package on a spare Pi. The working household system
   is not the same thing as a clean install of this public packaging.
4. Run new-video, pause, seek/resume, format-switch and volume tests, followed by
   hours of playback. Publish measured limits and remaining issues honestly.

The source preview may be shared as experimental after review; these remaining
checks prevent presenting it as a turnkey or universally reliable appliance.
