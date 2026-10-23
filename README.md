# Pi Surround

An experimental Apple TV surround bridge: HomePods at the front, a wired stereo
speaker at the rear, and a Raspberry Pi coordinating the two.

This project contains the integration code and documented changes built around
[Shairport Sync](https://github.com/mikebrady/shairport-sync),
[OwnTone](https://github.com/owntone/owntone-server),
[NQPTP](https://github.com/mikebrady/nqptp) and
[pyatv](https://github.com/postlund/pyatv). Those projects supply the AirPlay,
streaming, clock synchronisation and Apple TV control foundations. This is an
independent integration; their maintainers do not support this custom setup.

**Status: source preview for review and experienced builders.** The original
system's 500 ms configuration passed a listening test covering new YouTube
videos and pause/seek/resume: aligned sound, steady playback, and a small onset
gap. The sanitized public packaging has offline checks, but has not been
installed from scratch on a second Pi. It is not a turnkey appliance or a claim
of hours-long fault-free operation.

```text
Apple TV --multichannel AirPlay--> Pi / Shairport Sync
                                  |
                             ALSA loopback
                                  |
                             channel mixer
                              /         \
                    stereo PCM FIFO     rear queue / clock correction
                           |                       |
                        OwnTone                Pi analogue jack
                           |                       |
                      front HomePods          rear stereo speaker

Apple TV remote / native HomePod volume <--> pyatv controller
```

The front signal includes a centre/LFE fold-down, while the patched receiver
supplies a rear bus. A stereo rear soundbar does not create separately placed
rear speakers. This is not a Dolby-certified renderer, and it does not turn
HomePods into Apple's native multichannel home-theatre system.

## Reference hardware

- Raspberry Pi 2B, Raspberry Pi OS Bookworm, 32-bit ARM userland.
- Ethernet from Pi to the LAN. The current sender uses an Ethernet macvlan
  namespace with its own reserved address. Wi-Fi is not a supported drop-in.
- Apple TV with a normal paired HomePod front route, and an analogue rear
  speaker. The reference rear was an Orbitsound, believed to be a ONE P70.
- Same local network, working multicast discovery, Linux ALSA loopback.

The Pi 2B has no built-in Wi-Fi. HomePods are already wireless endpoints; the
Ethernet requirement concerns the central bridge and its network isolation.

## Start here

1. [Architecture](docs/ARCHITECTURE.md) and [timing profile](docs/TIMING.md).
2. [Manual setup and build](docs/INSTALL.md).
3. [Findings and remaining work](docs/FINDINGS.md).
4. [Upstream changes and credits](docs/UPSTREAM.md).
5. [Release audit and verification limits](docs/RELEASE-AUDIT.md).

`make check` performs device-free source, configuration and DSP checks.
`make native` compiles the two small arithmetic libraries into `build/native/`;
it does not install anything or open an audio device.

The examples deliberately contain placeholders, disabled commissioning approval
and a neutral rear trim. Do not copy the reference system's +38 dB rear trim
blindly: it was a workaround for that particular analogue input, not a universal
surround setting. Start at low listening levels.

## Contents and licence

`app/` and `native/` contain integration sources; `config/` has private-data-free
templates; `systemd/` contains service examples; `patches/` holds changes against
specific upstream versions. No paired database, credentials, Apple firmware,
movie recordings, Python environment or compiled executable is distributed.

Our original contributions are GPL-2.0-or-later; see [LICENSE](LICENSE).
Upstream material retains its own notices and licences; see
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). No affiliation with or endorsement
by Apple, Raspberry Pi, Orbitsound or the upstream projects is implied.

Please report integration issues here, with credentials and device identities
removed. See [CONTRIBUTING.md](CONTRIBUTING.md) before reporting an upstream bug.
