# Manual build and commissioning

This is a source preview, not an unattended installer. Use a spare dedicated Pi
first. The sanitized package has not yet passed a clean-device commissioning
test. None of these commands were run against the working playback system
during release preparation.

## 1. Host and dependencies

Use Raspberry Pi OS Bookworm with Ethernet and the analogue Headphones device.
The service examples assume a `pi` user with an `audio` supplementary group;
adapt every `User=pi` and OwnTone `uid` value if your user differs. Use system
Python for the audio worker and a separate venv for control, matching the service
paths. Do not run the control venv's Python as the router by accident.

Install the upstream build requirements for the pinned source versions. On the
reference OS the relevant development packages include:

```sh
sudo apt-get install build-essential git curl autoconf automake libtool pkg-config \
  bison flex gperf gettext libasound2-dev libsoxr-dev libavahi-client-dev \
  libssl-dev libpopt-dev libconfig-dev libplist-dev libsodium-dev \
  libmosquitto-dev libevent-dev libsqlite3-dev libavcodec-dev libavformat-dev \
  libavfilter-dev libavutil-dev libswresample-dev libconfuse-dev libgcrypt20-dev \
  libunistring-dev libcurl4-openssl-dev libwebsockets-dev libjson-c-dev \
  libmxml-dev libgpg-error-dev avahi-daemon alsa-utils iproute2 python3-numpy \
  python3-venv python3-dev
```

Treat that list as a starting point: upstream configure diagnostics are the
authority for optional features and distribution-specific package names.

The fetch helper below also obtains unmodified NQPTP 1.2.8 at its pinned tag
commit. Sixteen source/build inputs matched the reference Pi's build tree, and
that tree's executable matched the installed executable. Follow its upstream
build instructions without starting a second clock daemon; install its
executable at `/opt/homeambient-plan-b/bin/nqptp` for these service units.

## 2. Fetch and patch the two customized components

From the repository root, on your build host:

```sh
python3 scripts/fetch_sources.py
make check
make native
```

The fetch helper creates `build/sources`, checks the OwnTone source archive
checksum, checks both patches and applies them, and fetches pinned NQPTP. It refuses an existing source
directory so it cannot silently overwrite your changes. It does not install,
start services, select outputs or pair devices.

Build Shairport Sync from its patched directory:

```sh
autoreconf -fi
./configure --prefix=/opt/homeambient-plan-b --sysconfdir=/opt/homeambient-plan-b \
  --with-alsa --with-soxr --with-avahi --with-ssl=openssl --with-airplay-2 \
  --with-metadata --with-pipe --with-stdout --with-mqtt-client
make -j2
```

Build OwnTone from its patched directory:

```sh
autoreconf -fi
./configure --prefix=/opt/homeambient-plan-b --sysconfdir=/opt/homeambient-plan-b \
  --localstatedir=/var/lib/homeambient-plan-b --with-alsa --with-avahi \
  --with-libwebsockets --without-pulseaudio --disable-spotify \
  --disable-install-systemd CFLAGS='-O2 -g'
make -j2
```

Use each build's `make DESTDIR=<absolute-staging-directory> install` to inspect
the installation tree before copying it onto a Pi. Retain OwnTone's installed
SQLite extension, shared data and linked dependencies, not just its executable.
Executable compatibility requires the target architecture and OS libraries.

## 3. Private site configuration

Copy the integration sources to `/opt/homeambient-plan-b`, along with the two
native libraries built for that Pi. Create the control environment:

```sh
sudo python3 -m venv /opt/homeambient-plan-b/control-env
sudo /opt/homeambient-plan-b/control-env/bin/pip install -r requirements-control.txt
```

Create real files from `config/*.example`, removing only the `.example` suffix.
Store the result outside the public repository. Fill these fields:

- `settings.json`: the Pi's advertised AirPlay output ID, its LAN address, two
  OwnTone numeric output IDs and two native HomePod discovery IDs. These are
  different identity namespaces. Match discovered device identities, not names
  alone. Keep `centre_enabled=false` and `maintenance_approved=false` initially.
- `apple-tv.json`: the Apple TV identity, address and freshly paired credentials.
  Pair your own Apple TV with pyatv's `atvremote` tool; follow pyatv 0.18.0's
  pairing instructions. Its `Protocol` enum's numeric values are the JSON
  credential keys; do not guess them or copy someone else's credentials.
- `network.env`: your Ethernet parent, gateway, and a second unused LAN address
  reserved outside the DHCP allocation pool. The documentation addresses in the
  example are intentionally unusable on an ordinary home LAN. The switch/AP
  must allow the extra macvlan MAC. Ordinary Wi-Fi client interfaces generally
  cannot replace this Ethernet design unchanged.
- `owntone.conf`: use the exact discovered front receiver names in both
  `airplay` blocks and keep their `ptp_disable=true` profile. Each HomePod may
  need fresh OwnTone pairing. No paired database is included.

The native-master controller deliberately uses pyatv's internal MRP API. The
version pin matters; updating it is a compatibility change requiring tests.

## 4. Runtime directories and pipes

Create `/var/lib/homeambient-plan-b/{cache,media,diagnostics/pcm-traces}` owned by
the configured audio user, and `/opt/homeambient-plan-b` with readable code and
executable helper scripts. Keep pairing credentials root-readable only, and
protect the OwnTone database/cache as private data. The router's user must be
able to read non-secret settings and update runtime files.

Load `snd-aloop` with `index=8 id=HomeAmbient`. The example receiver writes
`hw:HomeAmbient,0,0`; the router captures `hw:HomeAmbient,1,0`. Confirm those
devices exist and that `plughw:Headphones,0` is your actual rear output.

Create a `front.pcm` FIFO and a `front.pcm.metadata` FIFO in the media directory,
owned by the audio user, with read/write permissions for that user. Do not
replace a real file blindly. Source metadata is read from the receiver's default
`/tmp/shairport-sync-metadata` FIFO. The pause controller needs readable OwnTone
logs and the `94-pause-cancel.conf` environment setting to verify front responses.

OwnTone must initialize and index its own database and pipe before the session
controller can operate; the controller expects the `speakers` table. Discover
and pair outputs in a commissioning session with the router/watcher stopped,
then stop OwnTone before changing its persisted selection. The namespace-scoped
API can be inspected using `ip netns exec homeambient-fronts` and the local
OwnTone HTTP API on port 3689. Do not expose that API publicly.

The ordinary session code assumes this initialization has been completed. It
does not contain a blank-device bootstrap or pairing wizard.

## 5. Controlled first run

Review and install the systemd examples and their drop-ins. `front-network`,
`airplay-volume` and `session-state` must be executable. Run `systemctl
daemon-reload` only when ready. Do not enable every unit automatically: front
sender/router are session-owned; receiver/watcher are the standby entry points.

With programme paused and speaker levels low, verify outputs and change
`maintenance_approved` to true only for your own commissioning. Start the
receiver timing/source and standby watcher, first allowing the watcher to
observe the normal HomePod route. Then select Pi Surround from Apple TV.
The session controller can pause, route and resume the programme as part of
handover. Stop if either speaker set is absent; do not repeatedly raise volume
to compensate for an unknown route.

Validate a new video, pause, seek/resume, a different programme format, remote
volume, menu clicks and previews. Check front/rear acoustically and lip sync
separately. Only then run a multi-hour test, retaining journals and counters.

Avoid copying the reference +38 dB rear trim. Increase the source feed only if
your analogue input needs it and lower the speaker's own amplifier accordingly.
The retained limiter shapes loud peaks and is not a guarantee against excessive
listening volume.

## Rollback

Before replacing a working installation, save its complete application tree,
units/drop-ins, configurations, private pairing files, transactionally consistent
OwnTone database, actual ALSA mixer state and matching build sources. Keep a
copy off the Pi. Restore timing values as a coherent set. Use a paused
maintenance window; never overwrite active database files or surprise another
viewer with route changes.
