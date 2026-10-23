# Upstream boundaries and patch review

Credit the foundations prominently: Mike Brady and Shairport contributors for
Shairport Sync/NQPTP; the OwnTone and earlier forked-daapd/mt-daapd contributors;
Pierre Ståhl and pyatv contributors; and NumPy contributors. Authoritative
attribution is in upstream source notices, not this abbreviated list.

## Receiver patch

Base: Shairport Sync `7bad231c18368dbd26f298577f6210e36e4b0797`.

- Stream-local handling of infeasible realtime latency offsets in `rtp.c`,
  `rtsp.c`, `player.h` and new `ap2_latency.h`.
- Local eight-channel/rear-bus processing and related metadata/diagnostics in
  `player.c`, `activity_monitor.c` and `ap2_buffered_audio_processor.c`.
- Dormant experimental latency-advertisement controls in `rtsp.c`.

This is the complete local delta, not a proposed single upstream pull request.
The stream-local offset correction is a plausible independent contribution,
after a minimal reproducer and current-upstream check. Custom channel mixing,
household timing settings and unsuccessful negotiation experiments should not
be presented as generally useful upstream fixes.

## OwnTone patch

Base: OwnTone tag `29.3`; its downloaded archive checksum is in provenance.json.

- `src/input.h`, `src/input.c`, `src/homeambient_live_buffer.h`: opt-in live FIFO
  queue trimming, marker boundaries and short splice smoothing.
- `src/inputs/pipe.c`, `src/player.c`, `src/outputs/airplay.c`: explicit pause
  flush metadata, propagation and diagnostic acknowledgements.
- `src/outputs/airplay_events.c`: local control-event handling changes.

The retained source delta includes experimental/history-related branches.
Review the patch before deciding which pieces to offer upstream. A small,
device-free regression case is preferable to sending this entire integration.

## Public packaging differences

Device IDs move to `settings.json`; network values move to `network.env`;
documentation comments and diagnostic storage paths are corrected. The optional
centre startup is omitted and `centre_enabled=true` is rejected. Example rear
gain starts at 0 dB rather than the household-specific +38 dB. These adaptations
have not been deployed to the working system and do not change it.

`provenance.json` records original integration source hashes. The current native
mixer was recovered from the retained, tested candidate source: the generic
source filename left on the Pi was older than the installed mixer. Publishing
that older filename would have reintroduced the rear classifier defect.

## Maintainer etiquette

Keep this integration's support and commissioning questions in this project.
Reproduce a defect against unmodified upstream before opening their issue.
Provide a small patch, exact base revision and test, and follow that project's
contribution rules. Do not imply upstream maintainers endorse this setup or owe
support for it. Nothing has been sent upstream or published by this preparation.
