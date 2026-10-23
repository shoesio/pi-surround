# Control reliability correction — 24 October 2026

## Two demonstrated defects

The rear audio reader rejects a gain instruction after two seconds without a
refresh (`app/coupled_trial.py`, `render_gain`). Previously the native volume
controller refreshed it only as its reads, writes and connection work progressed.
A slow control request could therefore mute otherwise healthy rear audio.

The controller now publishes the last applied gain independently every 100 ms.
Explicit mute, lost ownership, stale route observation and session shutdown still
produce zero gain. No playback buffer or audio clock changes are involved.
Synchronous steady playback HTTP requests run off the event loop so they cannot
block that publication or native protocol notifications.

A separate defect discarded volume intent after an unsuccessful write.
`Policy.observe()` acknowledged the new command before the operation completed;
the exception handler restored the old master level but retained that
acknowledgement. The controller now restores the unconfirmed policy checkpoint
on failure and retries the latest input without requiring another key press.
The regression fails against the prior code and passes with this correction.

Startup keeps its existing physical-key initialization and native/stream volume
mirroring. Separate diagnostics now record whether a startup checkpoint rejected
playback state or route ownership. The intermittent historical startup guard
failure has not been reproduced by these short tests.

## Reference-system checks

These results are from the existing wired Pi 2B system, using actual 7.1 movie
playback. They do not represent a clean installation of the sanitized package.

- Four consecutive transfers completed: approximately 36.2, 30.9, 31.7 and
  30.7 seconds. The last includes the final volume retry correction.
- No front RTSP closure, rear queue underrun or ALSA xrun during those trial
  windows. Fronts were selected and rendering continued on the rear output.
- A control-only worker was deliberately suspended for 4.5 seconds. The sampled
  rear gain instruction stayed no older than 105 ms; no rear mute, underrun or
  xrun occurred. The controller recovered without restarting audio services.
- In the final fault test, a relative volume-down key was sent during the stall.
  Its latest level reached the native HomePod control and rear gain after
  recovery without a second key press.
- Relative remote-key commands during Playing and Paused states reached the
  HomePod volume in approximately 0.65–0.73 seconds, without an unintended
  playback-state change. The previous level was restored after each check.
- Four added device-free regressions cover gain freshness, explicit mute and
  ownership loss, retry after a failed volume write, and publisher shutdown.

Continuous-playback observation verified 330 seconds without a rear mute, queue
error or front RTSP closure. The sender then paused, closed the Pi stream and
changed route/programme. The observation harness encountered a logging error at
that transition, so this is **not** a completed ten-minute endurance pass. Timing/buffering settings, mixer arithmetic, limiter, saved controls and
speaker offsets were preserved throughout these corrections.

## Limits

The listener confirmed the rear returned during testing, after initially
reporting no rear sound despite nonzero rendered PCM. This does not prove that
all historical quiet-scene cutouts were caused by the control defects. A
level-dependent analogue/soundbar issue remains possible.

Initial handover is still slow. The 500 ms profile describes downstream audio
buffering, not the complete transfer procedure. Menu-click and preview loudness,
picture/speech alignment and multi-hour audible reliability still need further
listening checks. Successful service status or native volume readback alone does
not certify those acoustic results.

GitHub Actions runs the device-free tests and publication scan on pushes and pull
requests. It does not exercise hardware or establish audible reliability.

The main-branch corrections are newer than the `v0.1.0-preview.1` archive. That
historical tag and its release assets are unchanged.
