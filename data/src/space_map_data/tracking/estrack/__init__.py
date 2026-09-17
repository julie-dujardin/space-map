"""ESA ESTRACK activity, from the ESTRACKnow backend.

The API is undocumented — routes were read out of the app's own bundle — and
unauthenticated. It answers for the ESA-led missions DSN never sees: JUICE,
Solar Orbiter, Hera, Euclid, BepiColombo, Mars Express, ExoMars TGO.

Monthly service volume is the usable signal. The ``live`` flags the app also
exposes read false for every mission and antenna even while the network is
demonstrably busy, so they are polled and recorded in case they come back, but
nothing should be derived from them.
"""
