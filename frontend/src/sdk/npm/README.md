# spacemap

The map of the Solar System from [spacemap.co](https://spacemap.co), for other
pages: bodies, spacecraft and their orbits over time, in a container of your
own. There is a flat map too, of one body's surface, in a projection of your
choosing.

Distances are kilometres and angles are degrees throughout. Objects are named
by their export id — `naif-399` for Earth, `naif-499` for Mars.

Licensed MPL-2.0. No key, no quota. The credit line the map draws is not
removable: the imagery it shows is published on those terms.

## Getting it

As one script that carries everything it needs — `spacemap.js`, an ES module,
next to `spacemap.iife.js` for pages that want a global instead:

```html
<div id="map" style="height: 500px"></div>
<script type="module">
	import { createMap } from './spacemap.js';
	const map = await createMap({ container: '#map' });
</script>
```

Or from npm, where three.js is yours to provide:

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

### Drawing on it

Markers are your own elements, pinned to a place that keeps up with the map.
Polylines are measured from an anchor, so a ring drawn round a body travels
with it.

```js
const marker = map.addMarker({
	anchor: { body: 'naif-499', latitude: 18.4, longitude: 77.5, altitudeKm: 0 },
	element: pin,
	align: [0.5, 1],
	occlude: true
});
marker.remove();

map.addPolyline({
	anchor: { body: 'naif-499' },
	points,
	color: '#66aaff',
	widthPx: 2,
	closed: true
});
```

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

## Where the data comes from

Both maps read the published export. `dataUrl` and `imagesUrl` point them
somewhere else — your own mirror, or a local copy while you develop. They are
page-wide: the last map created sets them, and data already fetched keeps the
origin it came from.

`locale` picks localized names; `messages` replaces the English wording the map
renders itself, one key at a time.

## Finishing with a map

```js
map.remove();
```
