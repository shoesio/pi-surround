# Third-party notices and distribution scope

| Component | Role | Licence / source |
| --- | --- | --- |
| Shairport Sync | AirPlay receiver and source timing | MIT-style project notice plus file-specific terms; [upstream](https://github.com/mikebrady/shairport-sync), preserved notices in `licenses/Shairport-*` |
| OwnTone 29.3 | Front PCM sender | GPL-2.0-or-later source notices, GPLv2 text in `licenses/GPL-2.0.txt`; [upstream](https://github.com/owntone/owntone-server) |
| NQPTP 1.2.8 | Receiver clock service | GPL-2.0-or-later; [upstream licence](https://github.com/mikebrady/nqptp/blob/main/LICENSE); fetched/installed separately |
| pyatv 0.18.0 | Apple TV and native HomePod control | MIT; [upstream](https://github.com/postlund/pyatv); installed separately, not vendored |
| NumPy | Python DSP fallback and queue arithmetic | BSD-3-Clause; [upstream](https://github.com/numpy/numpy); OS package, not vendored |

The OwnTone patch is based on tag `29.3`; the receiver patch is based on commit
`7bad231c18368dbd26f298577f6210e36e4b0797`. Existing copyright and licence notices
remain in the patched files. Modified OwnTone files gain a dated change notice.
Special receiver notices for ALAC, tinyhttp and tinysvcmdns are retained for
clarity; do not replace their terms with a blanket project licence.

Original integration code, configuration and documentation in this repository
are offered under GPL-2.0-or-later. This does not relicense upstream code.
See OwnTone's preserved AUTHORS file for its contributor acknowledgement.

Build/runtime dependencies include Linux/ALSA, OpenSSL, FFmpeg, Avahi, libsoxr,
libevent, SQLite, libplist, libgcrypt, libwebsockets, libconfuse and libmosquitto,
among others. They are not copied into this source preview. Their licence and
source-distribution requirements must be reviewed again before distributing
a binary, container, prebuilt SD-card image or bundled Python environment.

No Apple firmware, decompiled Apple implementation, DRM keys, pairing material
or media captures are included. The protocol implementations come from the
credited open-source projects and our integration. Apple product names identify
compatibility; this is not an Apple-certified or endorsed product. This source
review does not certify patents, trademarks or every jurisdiction's law.
