"""Hand-curated Wikidata mapping for IAU planetary quadrangles.

Keyed by ``(object_id, quad_code)`` matching ``Feature.quad_code``. Values are
Wikidata QIDs only — Wikipedia sitelinks (per-language URL) come from the
downloaded entity payload at export time, via ``WikidataEntityCache``.

Scope: Mercury (15), Mars (30), Venus (61). The Moon's IAU LAC 1:1M grid
uses a different scale than Wikipedia's coverage so its 144 quadrangles
are not mapped here. Venus v62 (south pole) has no Wikidata entity yet.

Notes on name drift (the QID points to the same area; the IAU name in our
DB may pre-date the current Wikipedia label):
- Mercury H-04/05/09/10/13/14 renamed since IAU ingest.
- Venus v06 Regio→Mons, v38 Maat Mons→Stanton, v47 Dorsum→Chasma.
"""

QUADRANGLE_QIDS: dict[tuple[str, str], str] = {
    # -- Mercury (15) -------------------------------------------------------
    ("naif-199", "H-01"): "Q3642430",  # Borealis
    ("naif-199", "H-02"): "Q3629859",  # Victoria
    ("naif-199", "H-03"): "Q3649494",  # Shakespeare
    ("naif-199", "H-04"): "Q3926564",  # Raditladi (was IAU Liguria)
    ("naif-199", "H-05"): "Q3620708",  # Hokusai (was IAU Apollonia)
    ("naif-199", "H-06"): "Q3926561",  # Kuiper
    ("naif-199", "H-07"): "Q3926556",  # Beethoven
    ("naif-199", "H-08"): "Q3926569",  # Tolstoj
    ("naif-199", "H-09"): "Q940057",  # Eminescu (was IAU Solitudo Criopho)
    ("naif-199", "H-10"): "Q3926566",  # Derain (was IAU Pieria)
    ("naif-199", "H-11"): "Q3926559",  # Discovery
    ("naif-199", "H-12"): "Q3926565",  # Michelangelo
    ("naif-199", "H-13"): "Q3926567",  # Neruda (was IAU Solitudo Perseph)
    ("naif-199", "H-14"): "Q3926558",  # Debussy (was IAU Cyllene)
    ("naif-199", "H-15"): "Q3629997",  # Bach
    # -- Mars (30) ----------------------------------------------------------
    ("naif-499", "mc01"): "Q3129187",  # Mare Boreum
    ("naif-499", "mc02"): "Q3055620",  # Diacria
    ("naif-499", "mc03"): "Q3054199",  # Arcadia
    ("naif-499", "mc04"): "Q3055662",  # Mare Acidalium
    ("naif-499", "mc05"): "Q3054227",  # Ismenius Lacus
    ("naif-499", "mc06"): "Q3055677",  # Casius
    ("naif-499", "mc07"): "Q3055697",  # Cebrenia
    ("naif-499", "mc08"): "Q3054547",  # Amazonis
    ("naif-499", "mc09"): "Q3054525",  # Tharsis
    ("naif-499", "mc10"): "Q3054565",  # Lunae Palus
    ("naif-499", "mc11"): "Q3054209",  # Oxia Palus
    ("naif-499", "mc12"): "Q3038730",  # Arabia
    ("naif-499", "mc13"): "Q3039434",  # Syrtis Major
    ("naif-499", "mc14"): "Q3055659",  # Amenthes
    ("naif-499", "mc15"): "Q3055646",  # Elysium
    ("naif-499", "mc16"): "Q19838113",  # Memnonia
    ("naif-499", "mc17"): "Q3054218",  # Phoenicis Lacus
    ("naif-499", "mc18"): "Q3054559",  # Coprates
    ("naif-499", "mc19"): "Q3054518",  # Margaritifer Sinus
    ("naif-499", "mc20"): "Q3039427",  # Sinus Sabaeus
    ("naif-499", "mc21"): "Q2382875",  # Iapygia
    ("naif-499", "mc22"): "Q3054529",  # Mare Tyrrhenum
    ("naif-499", "mc23"): "Q3055638",  # Aeolis
    ("naif-499", "mc24"): "Q3055669",  # Phaethontis
    ("naif-499", "mc25"): "Q3054248",  # Thaumasia
    ("naif-499", "mc26"): "Q3055653",  # Argyre
    ("naif-499", "mc27"): "Q3055690",  # Noachis
    ("naif-499", "mc28"): "Q3054539",  # Hellas
    ("naif-499", "mc29"): "Q3055681",  # Eridania
    ("naif-499", "mc30"): "Q3055631",  # Mare Australe
    # -- Venus (61 of 62; v62 has no Wikidata entity yet) -------------------
    ("naif-299", "v01"): "Q29451937",  # Snegurochka Planitia
    ("naif-299", "v02"): "Q29452521",  # Fortuna Tessera
    ("naif-299", "v03"): "Q29453537",  # Meskhent Tessera
    ("naif-299", "v04"): "Q29454060",  # Atalanta Planitia
    ("naif-299", "v05"): "Q29454374",  # Pandrosos Dorsa
    ("naif-299", "v06"): "Q29456932",  # Metis Mons (IAU: Metis Regio)
    ("naif-299", "v07"): "Q29458498",  # Lakshmi Planum
    ("naif-299", "v08"): "Q29458655",  # Bereghinya Planitia
    ("naif-299", "v09"): "Q29459595",  # Bell Regio
    ("naif-299", "v10"): "Q29460261",  # Tellus Tessera
    ("naif-299", "v11"): "Q29478441",  # Shimti Tessera
    ("naif-299", "v12"): "Q29478576",  # Vellamo Planitia
    ("naif-299", "v13"): "Q29478625",  # Ganiki Planitia
    ("naif-299", "v14"): "Q29478602",  # Nemesis Tesserae
    ("naif-299", "v15"): "Q29478655",  # Bellona Fossae
    ("naif-299", "v16"): "Q29487998",  # Kawelu Planitia
    ("naif-299", "v17"): "Q29495218",  # Beta Regio
    ("naif-299", "v18"): "Q29495389",  # Lachesis Tessera
    ("naif-299", "v19"): "Q16004956",  # Sedna Planitia
    ("naif-299", "v20"): "Q29496976",  # Sappho Patera
    ("naif-299", "v21"): "Q29514183",  # Mead
    ("naif-299", "v22"): "Q29518721",  # Hestia Rupes
    ("naif-299", "v23"): "Q15139348",  # Niobe Planitia
    ("naif-299", "v24"): "Q29529117",  # Greenaway
    ("naif-299", "v25"): "Q29529229",  # Rusalka Planitia
    ("naif-299", "v26"): "Q29529295",  # Atla Regio
    ("naif-299", "v27"): "Q29529325",  # Ulfrun Regio
    ("naif-299", "v28"): "Q29529352",  # Hecate Chasma
    ("naif-299", "v29"): "Q29529385",  # Devana Chasma
    ("naif-299", "v30"): "Q16004976",  # Guinevere Planitia
    ("naif-299", "v31"): "Q29536969",  # Sif Mons
    ("naif-299", "v32"): "Q29537508",  # Alpha Regio
    ("naif-299", "v33"): "Q29537853",  # Scarpellini
    ("naif-299", "v34"): "Q29539218",  # Ix Chel Chasma
    ("naif-299", "v35"): "Q29539428",  # Ovda Regio
    ("naif-299", "v36"): "Q29541231",  # Thetis Regio
    ("naif-299", "v37"): "Q29541318",  # Diana Chasma
    ("naif-299", "v38"): "Q29541467",  # Stanton (IAU: Maat Mons)
    ("naif-299", "v39"): "Q29545321",  # Taussig
    ("naif-299", "v40"): "Q29545546",  # Galindo
    ("naif-299", "v41"): "Q29545778",  # Phoebe Regio
    ("naif-299", "v42"): "Q29546001",  # Navka Planitia
    ("naif-299", "v43"): "Q29448980",  # Carson
    ("naif-299", "v44"): "Q29546192",  # Kaiwan Fluctus
    ("naif-299", "v45"): "Q29556078",  # Agnesi
    ("naif-299", "v46"): "Q29561448",  # Aino Planitia
    ("naif-299", "v47"): "Q29561459",  # Juno Chasma (IAU: Juno Dorsum)
    ("naif-299", "v48"): "Q29446224",  # Artemis Chasma
    ("naif-299", "v49"): "Q29561464",  # Mahuea Tholus
    ("naif-299", "v50"): "Q29561474",  # Isabella
    ("naif-299", "v51"): "Q29561478",  # Imdr Regio
    ("naif-299", "v52"): "Q15139349",  # Helen Planitia
    ("naif-299", "v53"): "Q29562801",  # Themis Regio
    ("naif-299", "v54"): "Q29562833",  # Nepthys Mons
    ("naif-299", "v55"): "Q16004873",  # Lavinia Planitia
    ("naif-299", "v56"): "Q16004983",  # Lada Terra
    ("naif-299", "v57"): "Q29562897",  # Fredegonde
    ("naif-299", "v58"): "Q29562901",  # Henie
    ("naif-299", "v59"): "Q29562984",  # Barrymore
    ("naif-299", "v60"): "Q29563245",  # Godiva
    ("naif-299", "v61"): "Q29563359",  # Mylitta Fluctus
}


def quadrangle_qids() -> set[str]:
    """All quadrangle QIDs, for seeding the Wikidata referenced-entity download."""
    return set(QUADRANGLE_QIDS.values())
