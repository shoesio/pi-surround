# Changes

## Unreleased — 24 October 2026

Keep the rear gain instruction fresh during slow native-volume operations; retry
unconfirmed volume requests after transport failure; move steady playback HTTP
checks off the controller event loop. Retain the physical-key startup initialization
and add separate playback-state/route diagnostics. No timing, buffering, mixer or
calibration changes. Includes device-free regressions and measured reference-system
test limits in [Control reliability](docs/CONTROL-RELIABILITY.md).

## 0.1.0-preview.1 — 23 October 2026

First locally prepared source preview, based on the retained 500 ms household
prototype. Includes integration source, configuration templates, pinned receiver
and OwnTone patches, native DSP sources, architecture/findings documentation,
licence notices and device-free verification.

Public packaging moves personal device/network identities to private settings,
excludes optional centre startup, and uses a neutral initial rear trim. These
packaging changes were not installed on the reference system. Binary images,
Apple firmware, pairing files, databases and media are excluded.

This preview needs clean-device commissioning and a release-owner review before
publication. It is not an upstream-approved release of Shairport Sync or OwnTone.
