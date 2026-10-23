# Retained timing profile

Reference checkpoint: 23 October 2026, listener-tested 500 ms profile.

| Setting | Retained reference value |
| --- | ---: |
| OwnTone `start_buffer_ms` | 500 ms |
| Rear `REAR_DELAY_MS` | 615 ms |
| Receiver `audio_backend_latency_offset_in_seconds` | -0.540 s |
| Live-input cap control file | See `config/live-input-buffer-ms.example` |
| Fixed programme gain | 0.125 |
| Reference rear trim | +38 dB, hardware-specific; public default is 0 dB |
| Rear soft limiter | Enabled |
| Centre | Disabled |

The previous timing vector was 2250 / 2365 / -2.290. Moving all three timing
values together by 1750 ms retained the relative relationship. Changing a
single buffer value is not an equivalent experiment. These are settings, not
measurements of complete acoustic latency.

A 300 ms trial initially aligned startup but produced intermittent glitches;
it was rejected. The 500 ms profile had a listener-confirmed small opening gap
and steady sound in the tested sequence. A longer soak is still needed.

The receiver patch also contains historical opt-in negotiation experiments.
Do not set `HOMEAMBIENT_OUTPUT_LATENCY_MICROS`,
`HOMEAMBIENT_ARRIVAL_TO_RENDER_MS` or other timing trial variables for this
baseline. Merely including dormant source does not mean an experiment succeeded.

Starting a network session, filling a queue, recovering a failed output and
seeking within a playing item are different events. Diagnose their logs and
timestamps separately. A stable presentation relationship can make a film look
aligned while the entire system still has substantial response latency; this
profile is not a low-latency gaming solution.
