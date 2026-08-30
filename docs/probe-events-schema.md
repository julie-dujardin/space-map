# Probe events (schema v3)

`space-map-downloads/sources/position/probe-events/*.json` — hand-curated
records of what each spacecraft did and when. One file per batch, each holding
a list of probes. The pipeline reads them for landed phases
(`probes/landing_events.py`), for the propagation veto
(`probes/propagation.py`), for mission status (`export/objects/missions.py`)
and for the timeline on a probe's page.

Load them through `probes/events.py`, never by hand:

```python
from space_map_data.probes.events import load_event_probes, events_by_probe_id
```

`probes/events_validate.py` checks the files against this document;
`tests/probes/test_events.py` runs it over the shipped data.

## Shape

```json
{
  "_meta": {"batch": "mariner_pioneer", "schema_version": "v3", "coverage_notes": "…"},
  "probes": [
    {
      "probe_id": 61775872,
      "name": "Giotto",
      "parent_mission": "Halley Armada",
      "mission_type": "comet_flyby",
      "agency": "ESA",
      "status": {"where": "heliocentric", "alive": null},
      "description": "…",
      "source_urls": ["…"],
      "events": []
    }
  ]
}
```

`probe_id` is the join to `derived/position/tables/probe_ids.json`, which owns
every other identifier — COSPAR, NORAD, Wikidata QID, NAIF. Those are **not**
repeated here; `name` is a label for readers and logs. A craft the registry has
no row for yet may carry `"probe_id": null`: the record is kept, the validator
reports it, and nothing downstream can join to it.

`propagation` is an optional per-probe instruction to the propagation
detector: `"force_on"`, `"force_off"`, or `{"mode": "from_state", …}` for a
craft with no kernel at all.

### status

Two independent claims, plus one about how it ended.

| field | values |
| --- | --- |
| `where` | `planned`, `transit`, `orbiting`, `landed`, `impacted`, `reentered`, `recovered`, `heliocentric`, `interstellar`, `unknown` |
| `alive` | `true`, `false`, `null` (dormant, nobody has called) |
| `lost` | `true` when contact was lost before the mission finished — it failed rather than retired |

`landed` is intact on a surface; `impacted` is destroyed against one;
`reentered` is destroyed in an atmosphere; `recovered` came back to Earth and
was collected.

## Events

```json
{
  "type": "flyby",
  "date": "1986-03-14T00:03:02Z",
  "description": "Closest approach to comet 1P/Halley at 596 km …",
  "target": {"naif": 1000036, "name": "1P/Halley"},
  "purpose": "gravity_assist",
  "stated": {"closest_approach_km": 596, "relative_velocity_kms": 68.4},
  "computed": {"kernel_source": "GIOTTO", "closest_approach_km": 629.2}
}
```

**`type`** says what happened; everything that varies is a field, so a reader
never has to parse the type to find the subject:

`launch`, `stage_separation`, `flyby`, `orbit_insertion`, `orbit_departure`,
`atmospheric_entry`, `landing`, `reentry`, `sample_collection`,
`sample_return`, `observation`, `perihelion`, `contact_loss`, `hibernation`,
`anomaly`, `mission_end`, `milestone`.

`milestone` is the deliberate catch-all for a moment that matters and fits no
other type; its prose carries it.

**`date`** is ISO-8601 at the precision the record actually supports — one of
`YYYY`, `YYYY-MM`, `YYYY-MM-DD`, `YYYY-MM-DDTHH:MMZ`, `YYYY-MM-DDTHH:MM:SSZ`.
A bare `1965` claims a year, not midnight on New Year's Day; `date_precision`
recovers which was meant. Offsets and fractional seconds are not used.
`approximate` is the different claim, that the source itself hedges about the
moment.

**`description`** is the curators' working note on the event — why the row
reads the way it does, what the source said. It is never loaded or shipped;
the frontend labels events from their `type`.

**`failed`** marks an event that was attempted and missed — a flyby that flew
wide, an insertion that did not take. The row stays so the timeline tells the
story; the target pages skip it as a visit.

**`end_date`** turns an event into a stretch of time: an `observation`
campaign, a `contact_loss` later recovered from, a `hibernation` that ended, a
`landing` the craft later left. The types in `INSTANT_TYPES` are moments by
definition and may not carry one.

**`target`** is what the event was directed at — a body by NAIF id (Horizons
convention for small bodies: `2_000_000+n` asteroids, `1_000_000+n` comets) or
another craft by its registry `probe_id`. A craft with no registry row is
named without an id; the validator lists those.

**`stated` vs `computed`.** `stated` is what the published sources say;
`computed` is what our kernels say, written by the compute pass and never
edited by hand. They share key names where they measure the same thing, so a
reader can show either and label it honestly. Unknown keys in either are
allowed and reported as drift — a genuinely new figure is a decision, not an
accident.

Type-specific fields: `purpose` (`flyby`), `outcome` and `intentional`
(`landing`), `site` (`landing`, `reentry` — `lat_deg`, `lon_deg`, optional
`name`).

## Where it ships

Two readers, both joining on `probe_id`:

- `probes/landing_events.py` turns each `landing` that names a `site` into a
  landed phase, so the craft sits on the surface it came down on.
- `export/objects/probe_events.py` attaches the whole record to the probe's
  object bundle under `events`: the strip along the map, and the drawer's
  Targets tab, which groups the record under each place the craft reached.
  `target` becomes a focus link where the body or craft has an object of its
  own; each event gains the `jd` of its date so a click can move the clock.

`export/objects/missions.py` reads `status` for the mission pages: `alive`
makes a mission operating, `lost` separates a failure from a retirement.

## Editing

Events are ordered by date within a probe; a landed phase ends at the next
departure event, so order carries meaning.

After any edit:

```
uv run pytest tests/probes/test_events.py
```

Migrating from v2: `scripts/migrate_probe_events_v3.py` (one-shot, kept for
reference — the v2 files are archived under
`space-map-downloads/archive/probe-events-v2-2026-08-25/`).
