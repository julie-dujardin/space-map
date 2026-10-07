# spacemap

The map of the Solar System from [spacemap.co](https://spacemap.co), on your
website! There are flat maps too, 360 panoramas from the surface, and a
diagram of the whole system to pick a body from.

Distances are kilometres and angles are degrees throughout. Objects are named
by their export id — `naif-399` for Earth, `spkid-20000004` for Vesta,
`norad_satcat-25544` for the ISS.

No key, no quota for now.

## Licensing

The code is MPL-2.0. The data and imagery the map fetches keep the terms of
their sources, which is why the credit line the map draws is not removable:
these license require attribution.

Every surface map and panorama is ranked by its terms, and the SDK draws only
what a page may use:

- **Open** imagery is free for any use, commercial included. It is the default
  and all a map draws unless asked otherwise.
- **Non-commercial** imagery is licensed for educational and non-commercial
  use: the Uranus map, and the Huygens descent panorama of Titan. A page that
  is not commercial turns it on:

  ```js
  const map = await createMap({ container: '#map', includeNonCommercial: true });
  ```

  Asking for it is accepting its terms, and the credit line naming each author
  is part of those terms. Without the flag Uranus renders in a flat fallback
  colour, and the Huygens stop is a place on Titan with no panorama to open.

- **Site-only** imagery is licensed to spacemap.co alone and never reaches the
  SDK.

## Getting it

As one script that carries everything it needs, from the CDN or copied next to
your page:

```html
<div id="map" style="height: 500px"></div>
<script type="module">
	import { createMap } from 'https://cdn.jsdelivr.net/npm/spacemap@0.1.11/dist/spacemap.js';
	const map = await createMap({ container: '#map' });
</script>
```

`spacemap.iife.js` next to it defines a `spacemap` global instead, for pages
without modules. Pin the version you tested: a published version never changes,
and an `integrity` attribute with the file's `sha384` digest keeps the page from
running anything else.

Or from npm, where you also need to provide three.js:

```sh
npm install spacemap three
```

```js
import { createMap } from 'spacemap';
```

## The Solar System map

`createMap` resolves once the map is worth looking at: the opening body placed,
and the one-off quality benchmark done. Small bodies go on streaming in behind
the map it hands back.

```js
const map = await createMap({
	container: '#map',
	view: { body: 'naif-499', lat: 20, lon: 0, distanceKm: 40000 },
	date: new Date('2030-01-01'),
	locale: 'fr'
});
```

### Moving the camera

```js
await map.flyTo({ body: 'naif-599' }); // fly, framing it for you
map.jumpTo({ body: 'naif-599', distanceKm: 2e6 }); // no flight
map.jumpTo({ body: 'naif-399', facing: 'naif-10', elevationDeg: 30 });
map.getCamera(); // { body, lat, lon, distanceKm }
```

`flyTo` resolves when the flight lands. What a target leaves out the map frames
itself, so `{ body }` alone is the ordinary way to move.

Clicking a named surface feature reports it; `panTo` turns to one without
travelling:

```js
map.on('featureselect', (feature) => map.panTo({ body: feature.bodyId, feature }));
```

To place the camera yourself, frame by frame, take it off the map's own
controls:

```js
const hold = map.holdCamera();
map.on('frame', () =>
	hold.set({ position: { body: 'naif-499', offsetKm: [x, y, z] }, target: { body: 'naif-499' } })
);
hold.release();
```

### Events

`on` returns a function that stops listening; `once` and `off` do what they say.

| event                             | when                                               |
| --------------------------------- | -------------------------------------------------- |
| `focuschange`                     | the camera settled on another object               |
| `camera`                          | the camera came to rest                            |
| `featureselect`                   | a nomenclature label was clicked                   |
| `clock`                           | the date, play state, rate or direction changed    |
| `loading` / `progress`            | data is coming in                                  |
| `error`                           | the data could not be loaded                       |
| `notice` / `noticedismiss`        | a condition worth telling the reader about         |
| `layerschange`                    | a layer was switched                               |
| `frame`                           | once per drawn frame                               |
| `contextlost` / `contextrestored` | the GPU context dropped and came back              |
| `datastale`                       | the export was republished while this map was open |
| `userpromoted`                    | how many reader-promoted bodies can be cleared     |

### The clock

`map.clock` is the simulation clock. It starts on wall-clock time unless the
map was opened on a date.

```js
map.clock.pause();
map.clock.setTimeScale(86400); // a day a second
map.clock.toggleDirection();
map.clock.setDate(new Date('2035-06-01'));
map.clock.now();
```

### Measuring

Some things can be read off the scene instead of drawn on it. All take the
bodies where the last frame put them, so after `setDate` wait for a `frame`
before asking.

```js
// Kilometres between two anchors: centres, places on a surface, or one of each.
map.distanceKm({ body: 'naif-499' }, { body: 'naif-401' });
map.distanceKm({ body: 'naif-499', latitude: 18.4, longitude: 77.5 }, { body: 'naif-401' });

// The same with its direction kept, on ecliptic axes: [x, y, z] kilometres.
map.offsetKm({ body: 'naif-499' }, { body: 'naif-401' });

// Where the Sun is overhead: the middle of the lit half.
map.getSubsolarPoint('naif-499'); // { lon, lat }
```

Any of them is null while a body it names is not loaded, or is nowhere at the
map's date: a moon before its discovery, a craft outside its mission. The
sub-solar point is given in the frame a surface anchor is placed in, so an
anchor there is on the lit side even on a body whose spin is not measured. It
is null as well until the map has read how the body spins, which it does once
the camera is on the body or its system.

The same three measures are functions that need no map, for a page that has
none or that cannot wait for one to reach a date. They take the date and
resolve when the export has answered for it:

```js
import { distanceKm, offsetKm, subsolarPoint } from 'spacemap';

const landing = new Date('1971-07-30T22:16:00Z');
await distanceKm({ body: 'naif-301' }, { body: 'naif-499' }, landing);
await offsetKm({ body: 'naif-301' }, { body: 'naif-499' }, landing);
await subsolarPoint('naif-301', landing);
```

Null means nowhere at that date and never not loaded yet. They place planets,
moons and small bodies as the map does. Spacecraft are not placed, and a
satellite of Earth only near the present: those need the map. A failed
download rejects.

### Drawing on it

Everything you draw is put somewhere by an **anchor**, and the anchor is what
keeps it there as the map moves under it. There are two kinds. A surface anchor
is a longitude, a latitude and a height on a body, and turns with the body as
it spins; an inertial anchor is a body and an offset in kilometres on ecliptic
axes, which travels with the body but does not turn. Either way the drawing
follows what it is drawn on, over any distance and any date.

Six things sit **in space**, measured from an anchor in kilometres:

```js
// Your own element, pinned to a place.
const marker = map.addMarker({
	anchor: { body: 'naif-499', latitude: 18.4, longitude: 77.5, altitudeKm: 0 },
	element: pin,
	align: [0.5, 1],
	occlude: true
});

// A line. Points are kilometres from the anchor, on ecliptic axes.
map.addPolyline({ anchor: { body: 'naif-499' }, points, color: '#66aaff', closed: true });

// An area, filled in its own colour unless you name another.
map.addPolygon({ anchor: { body: 'naif-499' }, points, color: '#ffcc55', fillOpacity: 0.3 });

// A circle round a place, in a plane you turn where you like. It is a ring
// rather than a disc unless you give it a fill: what it is drawn round is
// usually the point.
const ring = map.addCircle({
	anchor: { body: 'naif-499' },
	radiusKm: 20000,
	normal: [0.4, 0, 1],
	widthPx: 3
});
ring.setRadiusKm(30000);

// Text at a place, without an element of your own to build and style.
map.addLabel({ anchor: { body: 'naif-499', latitude: 18.4, longitude: 77.5 }, text: 'Elysium' });

// A picture at a place. It holds its size on screen wherever the camera goes.
map.addIcon({ anchor: { body: 'naif-499' }, url: badge, widthPx: 28, occlude: true });
```

Three more are drawn **on a body**, following its curve and turning with it.
These take longitude and latitude rather than kilometres — the same places the
flat map's shapes take, so one list of points draws on both maps:

```js
map.addSurfacePolyline({ body: 'naif-499', points: track, interpolate: 'geodesic' });
map.addSurfacePolygon({ body: 'naif-499', points: quadrangle, color: '#88ddff' });
map.addSurfaceCircle({ body: 'naif-499', center: { lon: 77.5, lat: 18.4 }, radiusKm: 800 });
```

`boxRing`, `smallCircle` and `graticule`, the flat map's helpers, make point
lists these take; `circlePoints` does the same for a circle in space.
`groundDistanceM` and `bearingDeg` measure between any two places on a body,
given its radius.

Every drawing answers `remove()` and `setVisible()`, a shape answers
`setAnchor()` and `setPoints()`, and `map.clearDrawings()` takes them all away
at once, leaving the map itself alone.

`ShapeStyle` is shared by the shapes: `color`, `widthPx` in screen pixels,
`opacity`, `fill` and `fillOpacity`. A width of zero leaves the outline out, for
an area drawn as a fill alone. The flat map says the same things with the same
words — its version is `FlatShapeStyle`, named apart because a page can hold
both maps at once — so a drawing described once can be handed to either.

A line, in space or on a surface, takes `dash` as the flat map's does: `'4 3'`
is four pixels drawn and three left out, counted on screen like the width, so
the dashes read the same from any distance.

Two rules fall out of the scene rather than out of taste. Widths are pixels
because the map spans metres to astronomical units, and a line a kilometre wide
is a wall from low orbit and nothing at all from the next planet out. And a body
hides what is behind it: a shape in space is drawn with the orbit trails and is
cut off at a body's edge exactly as they are, and a shape on a surface stops at
the limb. Markers, labels and icons are HTML rather than geometry and would
otherwise show through the body they sit on, so they take `occlude` to be hidden
when the place they mark turns away.

A shape on a surface floats a little above it by default — half a percent of the
body's radius, which is 17 km at Mars. That clears the relief the map draws, so
the shape reads as lying on the ground rather than sinking into it, and ground
higher than that still comes through, as it should. Give it an `altitudeKm` of
its own for a track flown rather than walked.

Labels and icons are elements, so listen to them directly through their
`element`; they take pointer events only once you pass `interactive: true`,
since the camera is dragged through the layer they sit in. Shapes drawn as
geometry are not clickable.

### Objects of your own

A spacecraft, a station, a body the export has never heard of: your own thing on
the map, moving under its own trajectory and drawn with your own model.

```js
const sat = map.objects.add({
	id: 'my-sat',
	name: 'My Satellite',
	position: tle(line1, line2),
	model: { object3d: myMesh, scaleM: 12, minPx: 24 },
	label: true
});

map.objects.get('my-sat');
map.objects.all();
sat.remove();
map.objects.clear();
```

**The map ships no model loader.** `object3d` is a three.js `Object3D` you have
already built or loaded — a mesh of your own, or a GLB you put through your own
`GLTFLoader`. That keeps a loader, its Draco and KTX2 decoders and their WASM out
of a bundle every reader downloads, for a feature most embeds never use, and it
leaves you the loader you already have rather than one this package chose for
you. From npm, three.js is a peer dependency: your copy is the map's copy, and
there is nothing to reconcile. From the CDN script the map's three.js is bundled
inside it and private, so a page that builds a model loads its own copy; that
works, since all the map does with the object is put it in a scene and place it,
but the package is the way to do this without two copies of three.js on the page.

`scaleM` is how big the model is drawn, in metres across its longest dimension
— the real size, arrays and booms deployed. Left out, it is drawn at the size it
was built. A twelve-metre satellite is nothing at all from a planetary view, so
`minPx` gives it a floor in pixels: below that it is drawn bigger than life,
above it, true to size.

Four constructors say where an object is, and any of them can be used anywhere
an anchor can — a marker, a drawing, a camera pose:

```js
import { elements, fixed, kmToAu, samples, tle } from 'spacemap';

// Parked: on the ground, or at an offset from a body's centre.
fixed({ body: 'naif-499', latitude: 18.4, longitude: 77.5, altitudeKm: 0 });
fixed({ body: 'naif-499', offsetKm: [0, 20000, 0] });

// A list of states, read between.
samples({ body: 'naif-399', samples: [{ jd, km: [x, y, z] }, ...] });

// A Keplerian orbit, propagated from its epoch.
elements({
	body: 'naif-399',
	elements: {
		a: kmToAu(6878), // semi-major axis, in AU
		e: 0.001,
		i: 51.6, // inclination, degrees
		om: 247, // longitude of the ascending node
		w: 130, // argument of pericentre
		ma: 325, // mean anomaly at the epoch
		n: 5658, // mean motion, degrees a day
		epoch: 2460584.5, // Julian date
		equatorial: true // referenced to Earth's equator, not the ecliptic
	}
});

// Two lines of a NORAD element set, propagated with SGP4 round Earth.
tle(line1, line2);
```

Offsets and states are kilometres on ecliptic J2000 axes, measured from the body
they name — the Sun when they name none. Orbital elements are the export's own,
which means the semi-major axis is in astronomical units: the one distance on
this surface that is not in kilometres, because that is how elements are quoted
everywhere the map reads them. `kmToAu` is there for that line alone. Set
`equatorial` when the angles are referenced to Earth's equator, as a TLE's are.

Between two states the path is a cubic through both of them, tangent to the
slope their neighbours imply, which is the curve a coasting object actually
follows — a straight line between states would cut every corner of an orbit.
States may be given in any order and at any spacing; they are read at their own
dates. **Outside the dates the states cover, the object is not drawn.** A list
that has run out is not evidence of where anything is, and the map would rather
show nothing than park a probe at its last known place. A TLE is the same the
other way: SGP4 propagates it as far as you ask, accuracy falling away from the
element set's epoch, and a date it cannot be propagated to — a decayed satellite
— leaves the object undrawn. Keplerian elements are defined at every date, so an
object on them is always somewhere.

What an object takes part in, and what it does not, is worth saying plainly. It
is drawn in the scene beside the bodies, so **a body in front of it hides it and
it hides what is behind it**, and it holds its place as the map's origin moves
from body to body. `label: true` writes its name beside it in the map's own
label style, `occludeLabel` hiding that while the object is round the far side.

It is **not** a body. `getBody` does not know it, `flyTo` cannot reach it, a
click does not select it — the map resolves a click through a pass over its own
objects, which a host object has no id in — and it draws no orbit trail of its
own. Those all read the published catalogue, and an object of yours is not in
it. What you get instead is its position, at any date you like, which is enough
to do the rest yourself:

```js
sat.positionKm(map.clock.jd); // [x, y, z] km from the body it is measured from

// Following it: its position is an anchor, so a held camera takes it as a
// target, and a standoff behind it as its own place.
const hold = map.holdCamera();
map.on('frame', ({ jd }) => {
	const km = sat.positionKm(jd);
	if (!km) return;
	hold.set({
		position: { body: sat.position.body, offsetKm: [km[0] + 500, km[1], km[2] + 200] },
		target: sat.position
	});
});

// A trail: sample the trajectory and hand the points to a polyline.
const points = [];
for (let i = -60; i <= 0; i++) points.push(sat.positionKm(map.clock.jd + i / 1440));
map.addPolyline({ anchor: { body: 'naif-399' }, points: points.filter(Boolean), fade: true });
```

`clearDrawings()` leaves objects alone — they are not drawings — and
`map.objects.clear()` takes only them.

### Its own imagery on a body

A body the map already knows can wear your pictures instead of the export's:

```js
map.setBodyAppearance('naif-499', { surface: url, night: url, clouds: url });
map.setBodyAppearance('naif-499', {}); // back to the map's own
```

Each is a URL the browser can load — an equirectangular map, east to the right,
longitude 0 in the middle, which is how every body's imagery is drawn. `night`
is the lights on the unlit side, `clouds` a layer over the surface whose alpha
is the cover; a body with neither of its own gets one built for it. The set is
replaced whole, so what a call leaves out goes back to the map's own picture.

**A picture given here is what the body wears at every distance.** The map picks
its own imagery by how much of the screen the body fills, stepping up a tier as
you approach; there is nothing to pick once a host has said what the body looks
like, so that pass stops fetching for it and, every frame, checks that what is on
the body is still yours — a system reload, a defocus or a lost GPU context puts
it straight back.

The flat map needs nothing of its own for this: its pictures are layers already,
and `addRasterLayer` puts one of yours over or in place of them.

### Layers

What the map draws is a set of layers, each switched by id — the kinds of
object first, then the chrome drawn around them:

`planets`, `dwarfPlanets`, `moons`, `asteroids`, `comets`, `spacecraft`,
`satellites` (the ones round Earth), `debris`, `orbits`, `labels` (the names of
objects), `halos` (the rings that mark objects too far to show a disc),
`nomenclature` (the names of places on them) and `stars` (the sky behind
everything).

```js
const map = await createMap({
	container: '#map',
	layers: { asteroids: false, comets: false, debris: false }
});

map.setLayerVisible('moons', false);
map.isLayerVisible('moons'); // false
map.getLayers(); // every id, so a switcher need not spell them out
```

**A layer switched off in the options is never downloaded; a layer switched off
later is only hidden.** The two are different asks and the map answers them
differently on purpose. `layers` at open time is what an embed about Mars
wants: the belts, the comets and the thirty thousand Earth satellites are not
fetched at all, and the map opens on a fraction of the data. `setLayerVisible`
is what a reader's checkbox wants: it lands on the next frame and never asks
the network for anything, whichever way it is switched.

The corollary is worth saying plainly: **switching on a layer that was off at
open time shows nothing**, because there is nothing to show. Switch off in the
options what the map is not for; switch at runtime what the reader is to have a
say in.

Two groups are hidden rather than skipped. `planets` and `dwarfPlanets` share
one file with the Sun, so leaving them out saves no download. `satellites` and
`debris` share one file with each other, so the download is only skipped when
neither is wanted.

The asteroids are one layer, not five. The export files them by orbit class,
and those classes do not divide cleanly into the dynamical families
`Body.orbitClass` reports — two of them belong to no family at all — so a
family switch would leave objects answering to nothing. Read `orbitClass` off a
body to tell the families apart.

Hiding is a drawing decision and nothing else. The Sun lights the scene
whatever is off, `flyTo` reaches a hidden body, and `getBody` still knows it.

The flat map has layers too, of its own: the pictures wrapped round a body and
the lines drawn over them. Those depend on the body on screen and carry their
own names, so it reads them out whole:

```js
flat.getLayers(); // ['surface', 'clouds', 'night', 'graticule', 'nomenclature']
flat.layers; // the same, with a label, a kind and a credit each
flat.setLayerVisible('clouds', false);
flat.isLayerVisible('clouds');
flat.on('layerschange', (layers) => redraw(layers));
```

### Bodies kept in sight

The map decides what to name by how far the camera is: a planet's halo and
orbit drop out once its whole orbit is a few pixels across, and a name gives way
to a bigger neighbour's. `setPinnedBodies` takes that decision for the bodies a
page is about:

```js
map.setPinnedBodies(['naif-499', 'spkid-20000433']); // Mars and Eros, from anywhere
map.setPinnedBodies([]); // back to the map's own judgement
```

A pinned body keeps its halo, name and orbit from however far, and through a
hidden layer. A moon is the exception: it is only drawn inside the system the
camera is in, so pin its planet to mark it from outside.

## The flat map

One body's surface, drawn flat, with layers you can switch and drawings of your
own on top.

```js
const flat = await createFlatMap({
	container: '#flat',
	body: 'naif-399',
	projection: 'orthographic',
	centerLon: 10,
	zoom: 2
});

flat.setLayerVisible('clouds', false);
flat.setProjection('equirectangular');
flat.addCircle({ at: { lon: 12.5, lat: 41.9 }, radiusDeg: 5, stroke: '#f80' });
flat.on('click', (at) => at && console.log(at.lon, at.lat));
```

## Panoramas

A rover's panorama from the inside, with arrows along its traverse. The
three-dimensional part is all the SDK draws; the date, the place, a list to
pick from or a map of the traverse are the page's to build.

Which bodies have panoramas, and where each one stands, can be read before a
view exists — what a page picking one for the reader needs, since `createPanorama`
opens the body's first unless told which:

```js
import { fetchPanoramaIndex, fetchPanoramas, isViewable } from 'spacemap';

await fetchPanoramaIndex(); // every body with coverage, and the missions on it
const entries = (await fetchPanoramas('naif-499')).filter(isViewable); // every one that opens
const pick = entries[(Math.random() * entries.length) | 0];
const view = await createPanorama({ container: '#panorama', body: 'naif-499', at: pick.id });
```

The list is every stop on every traverse, and not every stop has a sphere this
page may open: some are places the archive withheld the imagery of, and some
are under a licence the page has not accepted (`includeNonCommercial`).
`isViewable` says which open; the view skips the rest itself.

Both read the page's own settings, which a `create…` call applies. A page that
reads the list before it has made anything applies them itself first, or the
list comes from the published export and under the default licence:

```js
import { configureHost } from 'spacemap';

configureHost({ textures: 'non-commercial' }); // what `includeNonCommercial` sets
```

```js
const view = await createPanorama({
	container: '#panorama',
	body: 'naif-499',
	// A panorama's id, or its `time,lat,lon` key; the body's first when omitted.
	at: 'curiosity-n_l000_0016_edr003cyltsm0078_drivem3'
});

view.getPanoramas(); // every panorama of the body, mission by mission in time order
view.getNeighbours(); // the previous and next one on this traverse, with bearing and distance
view.on('load', (entry) => console.log(entry.sol, entry.time, entry.lat, entry.lon));
view.on('viewchange', ({ heading, pitch, fov }) => {});
view.setView({ heading: 90 });
await view.open(view.getPanoramas()[3]);
await view.step('next');
```

Pressing an arrow opens the panorama it points at, unless `followArrows` is
false: then only the `step` event fires, for a page that keeps the panorama in
its own URL. The `arrows` event says where each arrow landed on screen, for a
label beside it. `interactive: false` turns the drag, pinch, wheel and arrow
keys off; `arrows: false` and `setArrowsVisible` hide the arrows.

Limits keep the reader inside part of the sweep, or at one zoom. Headings run
clockwise from the first to the second, so `[300, 60]` is the arc across
north; a pair of equal values locks that axis.

```js
createPanorama({ container: '#panorama', body: 'naif-499', limits: { pitch: [-20, 20] } });
view.setLimits({ heading: [300, 60], fov: [60, 60] }); // ±60° of north, no zoom
view.setLimits({}); // free again
```

## The system map

The Solar System as a diagram to pick from: the Sun at the left edge, every
body along a log distance axis at its true relative size, moons stacked over
their planet, the belts as bands. It is what spacemap.co opens its Solar System
and planetary system pages with.

```js
import { createSystemMap } from 'spacemap';

const picker = await createSystemMap({ container: '#picker' });
picker.on('select', (target) => console.log(target.kind, target.name));
```

It is as wide as its container and three times as wide as it is tall, and it
reads at any width from a corner panel up. It draws from the export's own
figures and no imagery, so it is the one map with no credit line.

There are three views:

```js
await picker.setView({ kind: 'solar-system' });
await picker.setView({ kind: 'system', id: 'naif-699' }); // Saturn and its moons
await picker.setView({ kind: 'zone', zone: 'inner' }); // small bodies inside Jupiter's orbit
await picker.setView({ kind: 'zone', zone: 'outer' }); // and from it outward, the trojans included
```

A `system` is named by its primary and measured in the primary's radii. A body
with no moons has no system map, and asking for one rejects, leaving the map as
it was.

**A click reports what was picked and goes nowhere.** Walking down into a
system and back up is the page's own doing, which is what lets it keep a back
button, a breadcrumb or a URL of its own:

```js
picker.on('select', (target) => {
	if (target.kind === 'system') picker.setView({ kind: 'system', id: target.id });
	else if (target.kind === 'zone') picker.setView({ kind: 'zone', zone: target.zone });
	else choose(target.id); // a body
});
```

`getView()` says which view is up and `getTargets()` lists everything a click
on it can pick, for a page that wants a list beside the picture. `viewchange`
fires once a new view is drawn, and `error` when one could not be.

Two options decide what a click on the Solar System means:

```js
createSystemMap({ container: '#picker', grouping: 'systems', zones: 'inner-outer' });
```

- `grouping: 'systems'` makes a primary and the moons stacked on it one target,
  a `system` — one click for "somewhere round Saturn". A primary with no moons
  drawn stays a `body`. The default, `'bodies'`, leaves the dot and its stack a
  target each.
- `zones: 'inner-outer'` turns the two belts into the doors of the two zones of
  small bodies, labelled as such. The default, `'belts'`, leaves them the
  scenery they are.

A map that offers part of the catalogue names it, and everything else goes
undrawn in every view:

```js
const picker = await createSystemMap({
	container: '#picker',
	bodies: ['naif-499', 'naif-401', 'naif-602', 'spkid-20101955'],
	names: { 'naif-602': 'Encelade' }
});
await picker.setBodies(null); // everything again, once redrawn
```

A primary left out is still drawn while a moon of it is in, as the thing the
moon is found by; it is then not a target itself. `names` goes over the
export's own names, and is worth filling in for a small moon: the export names
a system's twenty most notable in a system view and the rest by id.

A zone shows the dwarf planets and large asteroids the Solar System view has,
and every other small body `bodies` names — a comet, a near-Earth asteroid, a
moon of one, which rides over its parent. The map has to learn where each of
those is, and reading that from the export costs a few hundred kilobytes a
body. A page that already knows says so instead, and nothing is read:

```js
createSystemMap({
	container: '#picker',
	view: { kind: 'zone', zone: 'inner' },
	bodies: ['spkid-20101955', 'spkid-20065803', 'spkid-120065803'],
	places: [
		{ id: 'spkid-20101955', name: 'Bennu', aAu: 1.126, tiltDeg: 6.03, radiusKm: 0.245 },
		{ id: 'spkid-20065803', name: 'Didymos', aAu: 1.643, tiltDeg: 3.41, radiusKm: 0.39 },
		{ id: 'spkid-120065803', name: 'Dimorphos', moon: true, parent: 'spkid-20065803' }
	]
});
```

The colours are custom properties, set on the container or anything above it:
`--sm-system-map-background`, `--sm-system-map-ink` for the axis and the muted
band, `--sm-system-map-sky` and `--sm-system-map-amber` for the other two bands
with a `-label` of each, `--sm-system-map-tip-background` and
`--sm-system-map-tip-ink` for the hover readout, and `--sm-system-map-radius`
for the corners. The words it writes itself are in `messages`, under
`system_map_*`, `planetary_system_*`, `tab_rings` and
`unit_symbol_astronomical_unit`. Kilometres are written by the browser, in the
`locale`'s own form.

## Restricting the map

Both maps take restrictions on what the reader may do. Each gesture is a
handler of its own, the way Mapbox has them:

```js
map.scrollZoom.disable();
map.scrollZoom.isEnabled(); // false
map.dragRotate.enable();
```

The Solar System map has `dragRotate`, `scrollZoom`, `keyboard`, `bodySelect`
and `featureSelect`; the flat map has `dragPan` and `scrollZoom`. They can be
set as the map opens, either one at a time or all at once:

```js
createMap({ container: '#map', interactive: false }); // every gesture off
createMap({ container: '#map', interactions: { scrollZoom: false } }); // one
```

`limits` says how far the reader may go. On the Solar System map that is a
distance from the focused body, a band of it to look down from, and the objects
a click may focus:

```js
const map = await createMap({
	container: '#map',
	limits: {
		minDistanceKm: 8000,
		maxDistanceKm: 400000,
		minLat: -40,
		maxLat: 40,
		minLon: -60,
		maxLon: 60,
		bodies: ['naif-399', 'naif-301']
	}
});

map.setLimits({ maxDistanceKm: 1e6 }); // replaced whole, not merged
map.getLimits();
```

On the flat map it is a zoom range and a band the middle of the frame stays in:

```js
flat.setLimits({ minZoom: 2, maxZoom: 8, minLon: -30, maxLon: 30 });
flat.getLimits();
```

**Limits gate reader input and nothing else.** `flyTo`, `jumpTo`, `panTo`,
`setView` and a held camera go where they are told, outside the limits
included; the reader's next gesture brings the map back inside. This is a
deliberate departure from Mapbox, where `maxBounds` holds the map whatever
moved it. Restrict what the reader may reach, and drive the map yourself to
anywhere you like.

A longitude band may run through the antimeridian: 170 to −170 is the twenty
degrees across it. One edge alone leaves the other at the antimeridian.

`setLimits` replaces the whole set, so `setLimits({})` lifts the restrictions
again. Angles are degrees and distances kilometres, as everywhere else.

### Cooperative gestures

A map inside a page the reader scrolls past can hand the plain gestures back to
the page:

```js
createMap({ container: '#map', cooperativeGestures: true });
```

The wheel then scrolls the page unless ctrl (⌘ on a Mac) is held, and one
finger drags the page rather than the map — two fingers still move it. A hint
says so whenever the plain gesture is tried; `messages` rewords it through
`cooperative_wheel`, `cooperative_wheel_mac` and `cooperative_touch`. The
handler is `map.cooperativeGestures`, on and off like any other.

## Controls

A control is anything that builds an element when it is added:

```js
map.addControl(
	{
		onAdd() {
			const button = document.createElement('button');
			button.textContent = 'Home';
			button.onclick = () => map.flyTo({ body: 'naif-399' });
			return button;
		}
	},
	'top-left'
);
```

Corners are `top-left`, `top-right`, `bottom-left` and `bottom-right`;
top-right unless the control or the caller names another. `removeControl` takes
one back off — except the credit line, which throws.

The panorama view takes controls the same way. The credit line is the only control the SDK ships. Zoom buttons, a layer
switcher or a clock are the page's to build, in its own look, from the calls
this document describes: `flyTo` and `jumpTo`, `getLayers` and
`setLayerVisible` with the `layerschange` event, and `map.clock` with the
`clock` event.

## Where the data comes from

Every map reads the published export. `dataUrl` and `imagesUrl` point them
somewhere else — your own mirror, or a local copy while you develop. They are
page-wide: the last map created sets them, and data already fetched keeps the
origin it came from.

`locale` picks localized names; `messages` replaces the English wording the map
renders itself, one key at a time.

## Finishing with a map

```js
map.remove();
```
