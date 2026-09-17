"""The only history of the DSN anyone kept: a bot's posts, read back.

Russ Garrett's pydsn has parsed the same feed we do since 2015 and posted every
downlink it saw. The Twitter run is gone and the fediverse instance that hosted
the second run has shut down, but the Bluesky account has been posting since
2024-12-03 and its whole repository is one unauthenticated request, so those
months are recoverable where our own record starts in September 2026. What we
keep is our reading of the posts, not the posts: the account hands over its
whole history on request, so there is no reason to hold a copy of it.

What comes back is narrower than what we collect ourselves. The bot posts one
line per spacecraft when its downlink reaches *data* status, debounced by a
minute; a pass that never gets past carrier lock leaves no trace, and nothing
carries band, uplink, range or light time. Treat it as a lower bound on
activity, at minute precision, observed by someone else — never as our own
sighting.
"""
