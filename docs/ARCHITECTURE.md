# Architecture

The receiver and front sender have separate network identities. The receiver's
NQPTP clock service runs on the Pi's main network. OwnTone runs in the
`homeambient-fronts` network namespace on an Ethernet macvlan interface, using a
second LAN address. This avoids mixing the receiver's and sender's timing roles.
The front profile sets `ptp_disable = true` for each HomePod output.

Shairport outputs eight-channel 48 kHz PCM16 to `snd-aloop`. The order is
FL, FR, FC, LFE, BL, BR, SL, SR. The receiver has local channel processing: its
SL/SR output is the established rear bus, rather than an assurance of untouched
source channels. Consult `patches/shairport-sync.patch`, especially `player.c`,
before changing mappings or using this as a reference decoder.

`wired_router.py` captures the loopback and sends stereo front PCM to a named
pipe read by OwnTone. The rear worker has an independent ALSA playback clock.
It adjusts its resampling ratio against its queue target; the queue's
`correction_ppm` and `queue_ms` are diagnostics, not proof of acoustic sync.
Source timestamps and output-device timing are also reconciled inside Shairport.
There is no single physical oscillator shared by the Pi DAC and both HomePods.

The session controller owns output selection, startup, restoration, front
recovery and Apple TV control. The standby watcher remembers the normal route
and only starts surround after the user selects the Pi. A root service manages
the namespace and other services. This code is intended for a dedicated Pi on a
trusted LAN, not a multiuser hosted service.

The native HomePod cluster is the volume authority. The controller reconciles
native changes with the Apple TV/Pi source-volume commands and publishes the
rear gain. This matters because menu clicks and some app previews can take a
native audio path while programme audio goes through the Pi. Adjusting only
OwnTone or PCM gain does not control that other path.

Pause cancellation uses receiver transport metadata, a front `.metadata` pipe,
patched OwnTone flush handling and responses from both selected outputs.
Software acknowledgement does not prove the exact acoustic stop instant.

Recorded waveform tracing is dormant unless explicitly requested. Such traces
can contain copyrighted or private audio; do not include them in public issues.
The optional kitchen/centre implementation is excluded from this release and
the public controller refuses `centre_enabled=true`.
