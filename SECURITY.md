# Private data and deployment boundary

Never publish `apple-tv.json`, paired OwnTone databases, native route snapshots,
runtime status/logs without review, or recorded PCM. A .gitignore is a reminder,
not a secret scanner. Rotate exposed pairing credentials if they are leaked.

The session controller runs as root and can start services and change routes.
The front sender runs inside a network namespace, but that is not a security
sandbox. Its API is meant for the local controller; keep the service on a
trusted LAN and review firewall exposure. Do not expose its HTTP or AirPlay
ports directly to the internet.

Until a public repository with private reporting is configured, do not post
security-sensitive reports publicly. The initial release must add an actual
private reporting contact or enable the host's private vulnerability reporting.
