"""Wikidata topic pages behind the Probes tab: "Exploration of X", per body.

The planets have an article each; visited comets share the "visited by
spacecraft" list article. The minor-planet counterpart is only tables — its
lead says nothing, so it is left out.
Values are tuples like the other topic tables; no locale falls back to
English. Coverage comments are as of 2026-08-29.
"""

_COMET_LIST = ("Q16000472",)  # list of comets visited by spacecraft — en

EXPLORATION_PAGES: dict[str, tuple[str, ...]] = {
    "naif-199": ("Q1188264",),  # exploration of Mercury — en fr ja zh ar ru pt it
    "naif-299": (
        "Q2707053",
    ),  # observations and explorations of Venus — en fr zh ar ru pt it es
    "naif-301": (
        "Q1064739",
    ),  # exploration of the Moon — en fr ja zh ar ru pt it es he
    "naif-499": ("Q716774",),  # exploration of Mars — en fr ja zh ar ru pt it es pl
    "naif-501": ("Q5421330",),  # exploration of Io — en fr ar it
    "naif-599": ("Q3276",),  # exploration of Jupiter — en fr ja zh ar ru pt it es
    "naif-606": ("Q43402238",),  # exploration of Titan — en it
    "naif-699": ("Q2724351",),  # exploration of Saturn — en fr ja zh ar ru it he
    "naif-799": ("Q2609494",),  # exploration of Uranus — en fr ja zh ar pt it es
    "naif-899": ("Q1110754",),  # exploration of Neptune — en fr ja zh ar ru it
    "naif-999": ("Q23581368",),  # exploration of Pluto — en zh ar ru it es
    # Comets with a visit on record.
    "spkid-1000036": _COMET_LIST,  # 1P/Halley
    "spkid-1000032": _COMET_LIST,  # 21P/Giacobini-Zinner
    "spkid-1000034": _COMET_LIST,  # 26P/Grigg-Skjellerup
    "spkid-1000005": _COMET_LIST,  # 19P/Borrelly
    "spkid-1000107": _COMET_LIST,  # 81P/Wild 2
    "spkid-1000093": _COMET_LIST,  # 9P/Tempel 1
    "spkid-1000041": _COMET_LIST,  # 103P/Hartley 2
    "spkid-1000012": _COMET_LIST,  # 67P/Churyumov-Gerasimenko
}
