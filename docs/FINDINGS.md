# What the investigation established

## Rear silence had more than one mechanism

An early mixer rounded quiet rear samples before boosting them. That could
turn very small samples into zero. Scaling before final conversion fixes that
specific loss; it does not explain all audible silence.

A waveform-correlation classifier also substituted an attenuated front copy
for the rear bus. Quiet ambience crossing its threshold could produce a large
rear level change. The retained native mixer and NumPy fallback now use the
same rear bus and trim regardless of front correlation. Front classification
remains in the code; it is not a universal content classifier.

In a repeatable quiet scene, headphones connected directly to the Pi played
continuously while the soundbar cut in and out. A larger feed, with the
soundbar's own level reduced, stopped the observed cutouts. This supports a
level-dependent problem downstream of the Pi, but does not establish the exact
soundbar circuit or a documented gate threshold.

The reference system eventually retained +38 dB of rear trim. This was an
empirical hardware workaround. Removing its soft limiter led to extensive
clipping in a louder passage; the user requested restoration. The released
sources retain it. A neutral trim is the public starting point.

## Volume paths differ

Programme PCM gain, OwnTone receiver volume and native HomePod volume are not
interchangeable. A controller anchored to native HomePod volume finally made
both navigation clicks and in-app previews follow the remote in listening
tests. Residual button-to-sound response lag remains. pyatv 0.18.0 is used
unmodified, including internal MRP interfaces that may change in future releases.

## Timing and recovery

Receiver scheduling plus the former downstream buffering could discard opening
audio. The coordinated 500 ms profile improved new-video and seek/resume
behaviour in a listening test. Advertising different latency alone did not
solve the problem. Some failed trials also left playback paused or the route
unready; a service being active was not sufficient evidence of working audio.

Front RTSP closures, source-loopback XRUNs and user-triggered pause/route changes
were all observed at different times. They must not all be labelled spontaneous
buffer starvation. A single logged underrun without a matching audible event
does not prove the listener's reported fault.

## Control reliability update — 24 October 2026

Slow volume-control operations could expire the rear gain instruction, and a
failed volume write could consume a key without applying its requested level.
The controller now maintains the applied gain independently and retries
unconfirmed intent. See [test results and limits](CONTROL-RELIABILITY.md).
The existing startup key initialization is retained. These corrections do not
resolve every possible analogue rear dropout or certify acoustic sync.

## Still open

- Small onset gap and exact audible pause-stop timing.
- Cold startup/transfer robustness and film/format switches.
- Residual remote-volume response lag.
- Multi-hour endurance, especially with other LAN traffic.
- Reproduction on a second, clean installation.
- A different networking design before claiming Wi-Fi Pi support.

The reference listener accepted sync and steady playback in the latest short
test. That is narrower than a general reliability certification.
