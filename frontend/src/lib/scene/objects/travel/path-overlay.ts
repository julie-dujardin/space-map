/**
 * The planned trajectory, drawn on the map, and the ones it was chosen from.
 *
 * Everything here mirrors how trails are drawn, for the same reason: vertices
 * are held centre-relative in Float64 and rebased into Float32 against the
 * focus, so an arc a billion km across still holds together when the camera is
 * metres above a moon. What differs is where the centre comes from — a trail
 * hangs off the body's own parent, a trajectory off whatever the transfer goes
 * round, which the path names.
 *
 * The markers are sprites rather than geometry: a burn is a point on the trip,
 * not an object with a size, so it should stay the same size on screen whether
 * the camera is at Earth or at Neptune.
 *
 * Hazards ride on the same machinery. A hazard carries dates and never
 * positions, so the stretch it covers is cut out of the drawn arcs by date and
 * its marker is placed by asking where the craft is on that date — the panel and
 * the map therefore cannot disagree about where one starts, because only one of
 * them decides.
 */

import {
	CanvasTexture,
	Color,
	Group,
	Mesh,
	Scene,
	Sprite,
	SpriteMaterial,
	Vector3,
	type PerspectiveCamera,
	type ShaderMaterial
} from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { attachCanvasForwarders } from '$lib/scene/label/forward';
import { reserveLabelRects, type AcceptedRect } from '$lib/scene/label/culling';
import { ndcZVisible } from '$lib/scene/setup/depth-mode';
import { HALO_RADIUS_PX } from '$lib/scene/types';
import '$lib/scene/label/label.css';
// Deep imports, not the kernel's index: the renderer holds this overlay from the
// first frame, and the index re-exports Lambert, the porkchop and the vehicle
// catalogue — a chunk only `/nav` should ever pull in.
import { crossingWindow, type PathArc, type TrajectoryPath } from '$lib/math/travel/path';
import type { Vec3 as TravelVec3 } from '$lib/math/travel/vec3';
import type { PathEndLabel, LabelledPath } from '$lib/travel/labelled-path';
import { craftPositionAt } from '$lib/math/travel/path-sample';
import { eclipticToScene } from '$lib/math/travel/state';
import { buildFatLineFromThin, writeFatTrailVertices } from '$lib/scene/objects/trail/geometry';
import type { Vec3 } from '$lib/scene/animation/math';
// A coast is the plan itself; a drive held all the way is a different kind of
// flying and reads warm to say so. Shared with the timeline under the map.
import { ARC_COLORS } from '$lib/travel/arc-colors';
import { HAZARD_COLORS } from '$lib/travel/hazard-colors';
// Type only: `hazards.ts` reaches the trajectory kernel, and this module is held
// by the renderer from the first frame.
import type { Hazard, HazardSeverity } from '$lib/travel/hazards';
import { hazardChip } from '$lib/travel/hazard-labels';
import './hazards.css';

/** Wide enough to read against a trail crossing it, not so wide it hides one. */
const LINE_WIDTH = 3;

/**
 * Drawn at full strength, unlike the orbit trails it crosses.
 *
 * A trail is furniture and is dimmed to sit behind the bodies; the plan is the
 * thing being read, and at the same shade it reads as one more orbit among the
 * dozens already on screen.
 */
const LINE_BRIGHTNESS = 1;

/**
 * The trajectories still being chosen between: thinner and dimmer than the one
 * that gets picked, so that picking one reads as it coming forward.
 *
 * Still well above the trails, since half a dozen of them are the whole content
 * of the map while the choice is open.
 */
const OPTION_WIDTH = 2;
const OPTION_BRIGHTNESS = 0.6;

/**
 * The same trajectories once one of them has been taken: still drawn, so the
 * plan can be read against what it was chosen from, but well under the orbit
 * trails — they are no longer anything to decide about.
 */
const FAINT_WIDTH = 1.5;
const FAINT_BRIGHTNESS = 0.3;

/**
 * The orbit at either end of the trip: thin, and only drawn once the camera is
 * near enough for it to be a ring rather than a speck.
 *
 * A parking orbit is a few hundred km over a body the map draws at system scale,
 * so from anywhere else it is smaller than the dot the planet itself is. The
 * threshold is a multiple of the orbit's own radius, which is what makes it one
 * rule for a 200 km orbit round Earth and round a kilometre-wide asteroid.
 */
const RING_WIDTH = 1.5;
const RING_BRIGHTNESS = 0.85;
const RING_VISIBLE_RADII = 60;

/** Screen size of the markers, in the units an unattenuated sprite scales by. */
const STOP_SIZE = 0.018;
const MEETING_SIZE = 0.045;
/** The craft is the one marker that moves, so it is the one that reads first. */
const CRAFT_SIZE = 0.026;
const CRAFT_COLOR = '#ffffff';

/** Drawn after trails so the plan sits on top of the orbits it crosses. */
const PATH_RENDER_ORDER = 4;

/**
 * A hazard is a wide band laid *under* the plan rather than a repaint of it: the
 * arc's own colours already say how each stretch is flown, and losing that to
 * say something else about the same line would be a poor trade. Wide enough to
 * show either side of the line it sits behind.
 */
const HAZARD_LINE_WIDTH = 9;
/** Full strength. These are the one thing on the map asking to be noticed. */
const HAZARD_BRIGHTNESS = 1;
/** Under the plan, over the trails. Worse hazards draw over milder ones, so a
 *  stretch that is several at once takes the colour of the worst of them. */
const HAZARD_RENDER_ORDER: Record<HazardSeverity, number> = {
	notice: PATH_RENDER_ORDER - 3,
	caution: PATH_RENDER_ORDER - 2,
	severe: PATH_RENDER_ORDER - 1
};
/** Order to build in, so the worst is added last and wins a depth-free tie
 *  against a band of the same tier belonging to another hazard. */
const SEVERITY_ORDER: HazardSeverity[] = ['notice', 'caution', 'severe'];

/** The warning marker's screen size, between a burn dot and the meeting ring. */
const HAZARD_MARKER_SIZE = 0.03;

/** A filled dot, for the points on the trip where something is spent. */
function dotTexture(color: string): CanvasTexture {
	const size = 64;
	const canvas = document.createElement('canvas');
	canvas.width = canvas.height = size;
	const ctx = canvas.getContext('2d')!;
	ctx.beginPath();
	ctx.arc(size / 2, size / 2, size / 2 - 10, 0, Math.PI * 2);
	ctx.fillStyle = color;
	ctx.fill();
	ctx.lineWidth = 6;
	// A dark rim keeps the dot readable against a bright planet behind it.
	ctx.strokeStyle = 'rgba(0,0,0,0.65)';
	ctx.stroke();
	return new CanvasTexture(canvas);
}

/** A hollow ring: where the destination will be, as opposed to where it is. */
function ringTexture(color: string): CanvasTexture {
	const size = 128;
	const canvas = document.createElement('canvas');
	canvas.width = canvas.height = size;
	const ctx = canvas.getContext('2d')!;
	ctx.beginPath();
	ctx.arc(size / 2, size / 2, size / 2 - 12, 0, Math.PI * 2);
	ctx.lineWidth = 9;
	ctx.strokeStyle = color;
	ctx.stroke();
	return new CanvasTexture(canvas);
}

/**
 * A hazard's own marker: a filled triangle, the one shape on this overlay that
 * is neither a dot nor a ring.
 */
function warningTexture(color: string): CanvasTexture {
	const size = 64;
	const canvas = document.createElement('canvas');
	canvas.width = canvas.height = size;
	const ctx = canvas.getContext('2d')!;
	const inset = 8;
	ctx.beginPath();
	ctx.moveTo(size / 2, inset);
	ctx.lineTo(size - inset, size - inset);
	ctx.lineTo(inset, size - inset);
	ctx.closePath();
	ctx.fillStyle = color;
	ctx.fill();
	// The same dark rim the dots carry, for the same reason: a bright limb behind.
	ctx.lineWidth = 6;
	ctx.lineJoin = 'round';
	ctx.strokeStyle = 'rgba(0,0,0,0.65)';
	ctx.stroke();
	return new CanvasTexture(canvas);
}

/**
 * The samples of `arc` that fall between two dates, inside the window the arc is
 * drawn over.
 *
 * The arc's own vertices rather than a re-derived sub-arc: the band has to sit
 * exactly on the line it is calling out, and re-solving a stretch at a different
 * sampling would leave it visibly beside it on a tight curve. Fewer than two and
 * there is no band to draw — a hazard shorter than the gap between samples is a
 * marker and a chip, which is all a moment ever gets anyway.
 */
function spanPoints(
	arc: PathArc,
	startJd: number,
	endJd: number,
	window: { from: number; to: number }
): TravelVec3[] {
	const points: TravelVec3[] = [];
	for (let i = window.from; i < window.to; i++) {
		if (arc.jds[i] >= startJd && arc.jds[i] <= endJd) points.push(arc.points[i]);
	}
	return points;
}

function makeSprite(texture: CanvasTexture, scale: number): Sprite {
	const sprite = new Sprite(
		new SpriteMaterial({
			map: texture,
			transparent: true,
			sizeAttenuation: false,
			depthTest: false
		})
	);
	sprite.scale.setScalar(scale);
	sprite.renderOrder = PATH_RENDER_ORDER;
	return sprite;
}

/** One drawn arc: the line, plus the centre-relative vertices it is rebuilt from. */
interface DrawnArc {
	line: Mesh;
	/** The trajectory it belongs to, so hovering one can pick out its own arcs. */
	owner: string | null;
	/** What it is drawn in when nothing is hovering it. */
	color: string;
	brightness: number;
	width: number;
	/** Scene units, relative to the path's centre body. */
	local: Float64Array;
	/** Scratch the rebase writes into before the fat geometry is expanded. */
	positions: Float32Array;
	alphas: Float32Array;
	count: number;
}

/**
 * An end orbit's line, with what it takes to decide whether it is worth drawing:
 * where its centre is and how big the ring round it is, both in scene units.
 *
 * It belongs to the trajectory like every other line here, so it sits where the
 * arc meets its body rather than where that body is now.
 */
interface DrawnRing {
	arc: DrawnArc;
	/** Scene units, relative to the path's centre body — the same frame the arcs
	 *  are held in. */
	local: Vec3;
	radius: number;
	/** Where that centre is this frame, from the last {@link TravelPathOverlay.reposition}. */
	readonly world: Vector3;
}

/** A marker and where it sits, in scene units relative to the centre body. */
interface DrawnMarker {
	sprite: Sprite;
	local: Vec3;
}

/** A label on one end of an option, and where it sits, same units. */
interface DrawnLabel {
	object: CSS2DObject;
	local: Vec3;
	/** The trajectory it names — see DrawnArc.owner. */
	owner: string | null;
	/** Measured once the element is laid out; 0 until then. */
	width: number;
	height: number;
	/** Whether it lost its slot to a nearer label and is down to its ring. Held so
	 *  the class is only written when it changes rather than every frame. */
	dimmed: boolean;
	/** An alternative's end once one trajectory has been taken: the ring alone, and
	 *  out of the cull — a ring is small enough not to be in anyone's way. */
	faint: boolean;
}

/**
 * The label an end of a trajectory wears: the halo every body in the app wears,
 * in the colour of the arc it caps, with the place and the date beside it.
 *
 * Given an `onSelect` it is a button that takes the trajectory, matching the row
 * it stands for in the panel's list, and gestures are forwarded to the canvas so
 * grabbing one still drags the camera — the same treatment the body and feature
 * labels get. Without one it is a caption on the trajectory already being read,
 * and lets every gesture through untouched.
 */
function makeEndLabel(
	end: PathEndLabel,
	color: string,
	trajectory: Pick<LabelledPath, 'onSelect' | 'onHover'>,
	canvas: HTMLCanvasElement
): CSS2DObject {
	const { onSelect, onHover } = trajectory;
	const el = document.createElement(onSelect ? 'button' : 'div');
	if (el instanceof HTMLButtonElement) el.type = 'button';
	el.className = `scene-path-label${onSelect ? '' : ' scene-path-label--static'}`;
	el.setAttribute('aria-label', `${end.name} \u2014 ${end.when}`);

	const halo = document.createElement('span');
	halo.className = 'scene-path-label__halo';
	halo.style.border = `2px solid ${color}`;
	halo.style.background = `${color}22`;
	const text = document.createElement('span');
	text.className = 'scene-path-label__text';
	const nameEl = document.createElement('span');
	nameEl.className = 'scene-path-label__name';
	nameEl.dir = 'auto';
	nameEl.textContent = end.name;
	const whenEl = document.createElement('span');
	whenEl.className = 'scene-path-label__when';
	whenEl.dir = 'auto';
	whenEl.textContent = end.when;
	text.append(nameEl, whenEl);
	el.append(halo, text);

	if (onSelect) {
		attachCanvasForwarders(el, canvas);
		// Click-vs-drag, the same guard the body and feature labels carry: a camera
		// drag that happens to start on a label must not read as a press on it.
		let downX = 0;
		let downY = 0;
		el.addEventListener('pointerdown', (event) => {
			const e = event as PointerEvent;
			downX = e.clientX;
			downY = e.clientY;
		});
		el.addEventListener('click', (event) => {
			const e = event as MouseEvent;
			e.stopPropagation();
			const dx = e.clientX - downX;
			const dy = e.clientY - downY;
			if (dx * dx + dy * dy <= 9) onSelect();
		});
	}
	if (onHover) {
		el.addEventListener('mouseenter', () => onHover(true));
		el.addEventListener('mouseleave', () => onHover(false));
	}

	const object = new CSS2DObject(el);
	// Anchored by the point, with the halo pulled back over it by its own radius,
	// so the ring straddles the place and the text runs off to the side.
	object.center.set(0, 0.5);
	return object;
}

export class TravelPathOverlay {
	private readonly group = new Group();
	private arcs: DrawnArc[] = [];
	/** The end orbits, which are among `arcs` too — this is what gates them on how
	 *  close the camera is. */
	private rings: DrawnRing[] = [];
	private markers: DrawnMarker[] = [];
	/** The ends of the options, named and dated; empty once one is chosen. */
	private labels: DrawnLabel[] = [];
	/** Where the craft is right now; hidden whenever it is not in flight. */
	private craft: DrawnMarker | null = null;
	private path: TrajectoryPath | null = null;
	/** What every vertex here is measured from — the chosen path's centre, or the
	 *  alternatives' when none has been chosen. They always agree: the centre falls
	 *  out of the pair of ends, which every trajectory on offer shares. */
	private center: string | null = null;
	private layer: number | null = null;
	private readonly offset = new Vector3();
	private readonly projected = new Vector3();
	/** Pooled screen rects handed to the label cull; never reallocated. */
	private readonly rects: AcceptedRect[] = [];
	/** Scratch for settling the labels against each other, nearest first. */
	private readonly order: { label: DrawnLabel; left: number; y: number; distance: number }[] = [];
	/** Which trajectory the reader is pointing at, from either end of the link —
	 *  a label out here or its mark on the launch-window field. */
	private hovered: string | null = null;
	private readonly tint = new Color();

	constructor(
		private readonly scene: Scene,
		private readonly canvas: HTMLCanvasElement
	) {
		// The arcs carry their own world offsets, so the group never moves.
		this.group.frustumCulled = false;
		this.scene.add(this.group);
	}

	/** The body every vertex is measured from; null when nothing is drawn. */
	get centerId(): string | null {
		return this.center;
	}

	get isEmpty(): boolean {
		return this.center === null;
	}

	/** Hide the whole plan with the rest of the map furniture in immersive mode. */
	setLayer(layer: number): void {
		this.layer = layer;
		this.group.traverse((object) => object.layers.set(layer));
	}

	/**
	 * Draw `path` as the plan and `options` as the trajectories it was chosen
	 * from, replacing whatever was drawn before. Both may be empty; that clears it.
	 *
	 * Only the plan gets markers and a craft — an alternative is a shape, not an
	 * itinerary, and half a dozen sets of burn dots would bury the one being read.
	 * And the alternatives carry their names only while the choice is open: once
	 * one is taken they drop to a faint line with a ring at each end, still
	 * pressable, which is what the plan is read against rather than a set of
	 * captions competing with it.
	 *
	 * The vertices land centre-relative; nothing is placed until `reposition`
	 * says where the centre body currently is.
	 */
	set(
		plan: LabelledPath | null,
		options: readonly LabelledPath[] = [],
		hazards: readonly Hazard[] = []
	): void {
		this.clear();
		this.path = plan?.path ?? null;
		this.center = plan?.path.centerId ?? options[0]?.path.centerId ?? null;

		// Behind the plan, so a chosen trajectory running alongside one it beat is
		// the line drawn on top.
		const chosen = plan !== null;
		for (const option of options) {
			this.addArcs(
				option.path,
				chosen ? FAINT_WIDTH : OPTION_WIDTH,
				chosen ? FAINT_BRIGHTNESS : OPTION_BRIGHTNESS,
				option.id
			);
			this.addEndLabels(option, chosen);
		}
		if (plan) {
			this.addPlan(plan);
			// After the plan, so its markers are already in the group and this only
			// adds its own. Hazards belong to the trajectory being read: an
			// alternative is a shape rather than an itinerary, and half a dozen sets
			// of warnings would bury the one being decided about.
			this.addHazards(plan.path, hazards);
		}
		// A rebuild throws away the styling, and the pointer has not moved.
		this.applyHover();

		if (this.layer !== null) this.setLayer(this.layer);
	}

	/**
	 * Lay each hazard's stretch under the plan, and mark where it starts.
	 *
	 * A hazard names dates, never places — so the stretch is cut out of the drawn
	 * arcs by date and the marker is placed by asking where the craft is on that
	 * date.
	 *
	 * Every one of them is named. An earlier cut labelled only the worse two
	 * levels to keep the line from being crowded, which stopped making sense once
	 * the two hazards that are *most* about a particular place — a conjunction is
	 * a fortnight, a perihelion a few weeks — were also the mildest. They start at
	 * different points on the arc by construction, so crowding is a coincidence
	 * rather than the rule.
	 */
	private addHazards(path: TrajectoryPath, hazards: readonly Hazard[]): void {
		const ordered = [...hazards].sort(
			(a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity)
		);

		for (const hazard of ordered) {
			const color = HAZARD_COLORS[hazard.severity];
			// Painted tier by tier, so the arc reddens into the worst of it. A hazard
			// with no bands is one that holds for the whole crossing rather than for
			// a part of it, and says so by giving the map nothing to draw.
			for (const band of hazard.bands) {
				path.arcs.forEach((arc, index) => {
					this.addBand(
						spanPoints(arc, band.startJd, band.endJd, crossingWindow(path, index)),
						HAZARD_COLORS[band.severity],
						HAZARD_RENDER_ORDER[band.severity]
					);
				});
			}

			// An arrival hazard can start where the arc ends, and one whose geometry
			// was never rebuilt has nowhere to go at all: no point, no marker.
			const at = craftPositionAt(path, hazard.startJd);
			if (!at) continue;
			const local = eclipticToScene(at) as Vec3;
			const sprite = makeSprite(warningTexture(color), HAZARD_MARKER_SIZE);
			this.group.add(sprite);
			this.markers.push({ sprite, local });

			const element = document.createElement('div');
			element.className = 'scene-hazard-label';
			element.style.color = color;
			element.textContent = hazardChip(hazard);
			const object = new CSS2DObject(element);
			// Anchored on the point with the text running off to its side, the way an
			// end label is.
			object.center.set(0, 0.5);
			this.group.add(object);
			// `faint` keeps it out of the end labels' cull, and a null owner out of
			// the hover styling: a chip is neither a candidate for screen space nor
			// part of the link with the launch-window field.
			this.labels.push({
				object,
				local,
				owner: null,
				width: 0,
				height: 0,
				dimmed: false,
				faint: true
			});
		}
	}

	/** One coloured band along a stretch of a drawn arc, under the line it names. */
	private addBand(points: readonly TravelVec3[], color: string, renderOrder: number): void {
		const count = points.length;
		if (count < 2) return;
		const local = new Float64Array(count * 3);
		for (let i = 0; i < count; i++) {
			const [x, y, z] = eclipticToScene(points[i]);
			local[i * 3] = x;
			local[i * 3 + 1] = y;
			local[i * 3 + 2] = z;
		}
		const positions = new Float32Array(count * 3);
		const alphas = new Float32Array(count).fill(1);
		const line = buildFatLineFromThin(
			count,
			positions,
			alphas,
			alphas,
			count,
			color,
			HAZARD_LINE_WIDTH,
			HAZARD_BRIGHTNESS
		);
		line.frustumCulled = false;
		line.renderOrder = renderOrder;
		this.group.add(line);
		this.arcs.push({
			line,
			// No owner: a band belongs to the plan, which is not something the hover
			// link picks out.
			owner: null,
			color,
			brightness: HAZARD_BRIGHTNESS,
			width: HAZARD_LINE_WIDTH,
			local,
			positions,
			alphas,
			count
		});
	}

	/** The chosen trajectory: its arcs at full strength, its ends named, the points
	 *  it is spent at, and the dot that rides it. */
	private addPlan(plan: LabelledPath): void {
		const path = plan.path;
		this.addArcs(path, LINE_WIDTH, LINE_BRIGHTNESS, null, true);
		this.addEndOrbits(path);
		// A labelled end already wears a ring, so it takes the marker's place rather
		// than sitting inside one.
		const labelled = this.addEndLabels(plan);

		// Where the destination will be when the craft gets there. Skipped when the
		// destination is the body everything is measured from — it is already at the
		// centre and does not move in its own frame.
		const meets = path.meeting.bodyId !== path.centerId;
		if (meets && !labelled.arrival) {
			this.markers.push({
				sprite: makeSprite(ringTexture(ARC_COLORS.cruise), MEETING_SIZE),
				local: eclipticToScene(path.meeting.r) as Vec3
			});
		}
		for (const stop of path.stops) {
			// The ring already marks the arrival, and it sits on the same point; a dot
			// under it would only thicken the circle's centre.
			if (stop.kind === 'arrival' && meets) continue;
			if (stop.kind === 'departure' && labelled.departure) continue;
			this.markers.push({
				sprite: makeSprite(dotTexture(ARC_COLORS.cruise), STOP_SIZE),
				local: eclipticToScene(stop.r) as Vec3
			});
		}
		for (const marker of this.markers) this.group.add(marker.sprite);

		// Added last so it draws over the burn it is sitting on when the two meet.
		this.craft = { sprite: makeSprite(dotTexture(CRAFT_COLOR), CRAFT_SIZE), local: [0, 0, 0] };
		this.craft.sprite.visible = false;
		this.group.add(this.craft.sprite);
	}

	/**
	 * Label a trajectory at both ends, and answer which ends got one.
	 *
	 * The arrival goes on the *meeting* point — where the destination will be when
	 * the craft gets there — because that is where the arc actually ends, and a
	 * date written against where the planet is today would be a different claim.
	 *
	 * Each end takes the colour of the arc it caps, so the two differ on a
	 * trajectory flown differently at each end: a drive held all the way leaves
	 * under boost and arrives under braking.
	 */
	private addEndLabels(
		trajectory: LabelledPath,
		faint = false
	): { departure: boolean; arrival: boolean } {
		const { path, onSelect } = trajectory;
		const first = path.arcs[0];
		const last = path.arcs[path.arcs.length - 1];
		const departure = path.stops.find((stop) => stop.kind === 'departure');
		const ends: { local: Vec3; end: PathEndLabel; color: string; at: 'departure' | 'arrival' }[] = [
			{
				local: eclipticToScene(path.meeting.r) as Vec3,
				end: trajectory.arrival,
				color: ARC_COLORS[last?.kind ?? 'cruise'],
				at: 'arrival'
			}
		];
		if (departure) {
			ends.push({
				local: eclipticToScene(departure.r) as Vec3,
				end: trajectory.departure,
				color: ARC_COLORS[first?.kind ?? 'cruise'],
				at: 'departure'
			});
		}
		const drawn = { departure: false, arrival: false };
		for (const { local, end, color, at } of ends) {
			if (!end.name) continue;
			const object = makeEndLabel(end, color, trajectory, this.canvas);
			if (faint) object.element.classList.add('scene-path-label--faint');
			this.group.add(object);
			this.labels.push({
				object,
				local,
				owner: onSelect ? trajectory.id : null,
				width: 0,
				height: 0,
				dimmed: false,
				faint
			});
			drawn[at] = true;
		}
		return drawn;
	}

	/**
	 * Pick one trajectory out of the rest, or none.
	 *
	 * The other half of the link with the launch-window field: pointing at a mark
	 * there lights the arc out here, and pointing at a label out here lights the
	 * mark. Nothing is rebuilt — the line's colour and width are uniforms.
	 */
	setHovered(id: string | null): void {
		if (this.hovered === id) return;
		this.hovered = id;
		this.applyHover();
	}

	private applyHover(): void {
		for (const arc of this.arcs) {
			if (arc.owner === null) continue;
			const lit = arc.owner === this.hovered;
			const material = arc.line.material as ShaderMaterial;
			(material.uniforms.uColor.value as Color)
				.set(arc.color)
				.multiplyScalar(lit ? LINE_BRIGHTNESS : arc.brightness);
			material.uniforms.uLineWidth.value = lit ? LINE_WIDTH : arc.width;
		}
		for (const label of this.labels) {
			if (label.owner === null) continue;
			label.object.element.classList.toggle('scene-path-label--lit', label.owner === this.hovered);
		}
	}

	/**
	 * Lay one trajectory's arcs down, centre-relative and unplaced.
	 *
	 * An end with a passage hands the last of its crossing over: the arc stops
	 * where the craft crosses into the sphere of influence and the passage carries
	 * on from there, so the samples it replaces are left out here. Only the plan
	 * is drawn that way — an alternative is a shape and gets none of the
	 * body-scale detail — so an option keeps its whole arc.
	 */
	private addArcs(
		path: TrajectoryPath,
		width: number,
		brightness: number,
		owner: string | null = null,
		patched = false
	): void {
		path.arcs.forEach((arc, index) => {
			const { from, to } = patched
				? crossingWindow(path, index)
				: { from: 0, to: arc.points.length };
			this.addLine(arc.points.slice(from, to), ARC_COLORS[arc.kind], width, brightness, owner);
		});
	}

	/**
	 * The orbits the trip starts in and ends in, and the passages down to them.
	 *
	 * The passage is a piece of the trip and is drawn at every zoom: it is where
	 * the crossing stops, so it has to be, and it is drawn in the crossing's own
	 * frame at that end, so it can be. The orbit is different — it is where the
	 * trip ends up rather than part of getting there, and it is the one thing here
	 * at a body's own scale, a few hundred km over a planet the map draws at
	 * system scale. So it is kept in its own list and waits for the camera.
	 */
	private addEndOrbits(path: TrajectoryPath): void {
		for (const orbit of path.endOrbits) {
			this.addLine(orbit.approach, ARC_COLORS.cruise, LINE_WIDTH, LINE_BRIGHTNESS, null);
			const ring = this.addLine(orbit.points, ARC_COLORS.cruise, RING_WIDTH, RING_BRIGHTNESS, null);
			if (!ring) continue;
			const local = eclipticToScene(orbit.center) as Vec3;
			// Its size, off the drawn vertices rather than converted again — an ellipse
			// is widest somewhere other than where it starts.
			let radius = 0;
			for (let i = 0; i < ring.count; i++) {
				const dx = ring.local[i * 3] - local[0];
				const dy = ring.local[i * 3 + 1] - local[1];
				const dz = ring.local[i * 3 + 2] - local[2];
				radius = Math.max(radius, Math.hypot(dx, dy, dz));
			}
			ring.line.visible = false;
			this.rings.push({ arc: ring, local, radius, world: new Vector3() });
		}
	}

	/** One line of the plan, centre-relative and unplaced. */
	private addLine(
		points: readonly TravelVec3[],
		color: string,
		width: number,
		brightness: number,
		owner: string | null
	): DrawnArc | null {
		const count = points.length;
		if (count < 2) return null;
		const local = new Float64Array(count * 3);
		for (let i = 0; i < count; i++) {
			const [x, y, z] = eclipticToScene(points[i]);
			local[i * 3] = x;
			local[i * 3 + 1] = y;
			local[i * 3 + 2] = z;
		}
		const positions = new Float32Array(count * 3);
		// A plan is not a trail: it is equally real along its whole length, so
		// there is no fade from a live head to an old tail.
		const alphas = new Float32Array(count).fill(1);
		const line = buildFatLineFromThin(
			count,
			positions,
			alphas,
			alphas,
			count,
			color,
			width,
			brightness
		);
		line.frustumCulled = false;
		line.renderOrder = PATH_RENDER_ORDER;
		this.group.add(line);
		const arc: DrawnArc = {
			line,
			owner,
			color,
			brightness,
			width,
			local,
			positions,
			alphas,
			count
		};
		this.arcs.push(arc);
		return arc;
	}

	/**
	 * Put the craft marker where the clock says the craft is.
	 *
	 * Call before {@link reposition}, which is what actually places it. Outside
	 * the trip the marker goes away rather than parking on an end — the craft has
	 * not left, or is no longer flying.
	 */
	setClock(jd: number): void {
		const craft = this.craft;
		if (!craft || !this.path) return;
		const position = craftPositionAt(this.path, jd);
		craft.sprite.visible = position !== null;
		if (position) craft.local = eclipticToScene(position) as Vec3;
	}

	/**
	 * Place the path against the scene as it currently stands.
	 *
	 * `centerScenePos` is where the centre body is this frame and `basis` is what
	 * the scene is drawn relative to; both are in scene units. Call whenever
	 * either moves — which is every frame the clock runs, and on every focus
	 * change.
	 */
	reposition(centerScenePos: Vec3, basis: Vec3): void {
		if (this.center === null) return;
		const dx = centerScenePos[0] - basis[0];
		const dy = centerScenePos[1] - basis[1];
		const dz = centerScenePos[2] - basis[2];

		for (const arc of this.arcs) {
			for (let i = 0; i < arc.count; i++) {
				arc.positions[i * 3] = arc.local[i * 3] + dx;
				arc.positions[i * 3 + 1] = arc.local[i * 3 + 1] + dy;
				arc.positions[i * 3 + 2] = arc.local[i * 3 + 2] + dz;
			}
			writeFatTrailVertices(arc.line.geometry, arc.positions, arc.alphas, arc.alphas, arc.count);
		}
		for (const marker of this.markers) {
			marker.sprite.position.set(marker.local[0] + dx, marker.local[1] + dy, marker.local[2] + dz);
		}
		for (const label of this.labels) {
			label.object.position.set(label.local[0] + dx, label.local[1] + dy, label.local[2] + dz);
		}
		if (this.craft) {
			const { sprite, local } = this.craft;
			sprite.position.set(local[0] + dx, local[1] + dy, local[2] + dz);
		}
		for (const ring of this.rings) {
			ring.world.set(ring.local[0] + dx, ring.local[1] + dy, ring.local[2] + dz);
		}
	}

	/**
	 * Hand the line shader the camera, which is what its vertices are ultimately
	 * drawn relative to. Same contract as the trails' own per-frame update.
	 *
	 * Also where the end orbits decide whether they are a ring or a speck this
	 * frame, since the camera is the only thing that answers it.
	 */
	updateCameraOffset(cameraPosition: Vector3): void {
		if (this.arcs.length === 0) return;
		this.offset.set(-cameraPosition.x, -cameraPosition.y, -cameraPosition.z);
		for (const arc of this.arcs) {
			const material = arc.line.material as ShaderMaterial;
			material.uniforms.uCenterOffset.value.copy(this.offset);
		}
		for (const ring of this.rings) {
			const distance = ring.world.distanceTo(cameraPosition);
			ring.arc.line.visible = distance < ring.radius * RING_VISIBLE_RADII;
		}
	}

	setVisible(visible: boolean): void {
		this.group.visible = visible;
	}

	/**
	 * Settle the end labels against each other, and claim the screen space the
	 * survivors take so nothing else is drawn over them.
	 *
	 * A trajectory being chosen is what the map is *for* at that moment, so these
	 * outrank every body and feature label rather than competing with them —
	 * but not each other. Two of them stacked in the same place is exactly the
	 * mess the cull exists to prevent, so among themselves the nearest to the
	 * camera wins and the ones behind it fall back to their ring, the way a body
	 * label falls back to its halo.
	 *
	 * They are projected here rather than measured off the DOM:
	 * `getBoundingClientRect` on every label every frame is a forced layout, and
	 * this is the same projection the labels are drawn by.
	 *
	 * Call once per frame, before the culls run. With nothing drawn it releases
	 * the space it was holding.
	 */
	reserveLabelSpace(camera: PerspectiveCamera, screenWidth: number, screenHeight: number): void {
		if (!this.group.visible || this.labels.length === 0) {
			reserveLabelRects(this.rects, 0);
			return;
		}

		// Nearest first, so the label for the place the camera is closest to is the
		// one that keeps its text.
		this.order.length = 0;
		for (const label of this.labels) {
			// A faint end is a ring and nothing else — small enough to sit under
			// anything, so it neither claims space nor competes for it.
			if (label.faint) continue;
			const element = label.object.element;
			// Zero until the CSS2D renderer has put the element in the document; a
			// cached zero would hold no space for the rest of the session. Only ever
			// measured while the label has its text, so a dimmed one keeps the width
			// it will have again when it wins.
			if (!label.width && !label.dimmed) {
				label.width = element.offsetWidth;
				label.height = element.offsetHeight;
			}
			if (!label.width) continue;
			this.projected.copy(label.object.position).project(camera);
			if (!ndcZVisible(this.projected.z)) continue;
			this.order.push({
				label,
				// Anchored on the point with the halo pulled back over it, so the box
				// starts a halo radius to the left and runs right from there.
				left: (this.projected.x * 0.5 + 0.5) * screenWidth - HALO_RADIUS_PX,
				y: (-this.projected.y * 0.5 + 0.5) * screenHeight,
				distance: label.object.position.distanceTo(camera.position)
			});
		}
		this.order.sort((a, b) => a.distance - b.distance);

		let count = 0;
		for (const { label, left, y } of this.order) {
			const right = left + HALO_RADIUS_PX + label.width;
			let overlaps = false;
			for (let i = 0; i < count; i++) {
				const a = this.rects[i];
				if (left < a.right && right > a.left && Math.abs(y - a.y) < (label.height + a.h) / 2) {
					overlaps = true;
					break;
				}
			}
			this.setLabelDimmed(label, overlaps);
			if (overlaps) continue;
			let rect = this.rects[count];
			if (!rect) {
				rect = { left: 0, right: 0, y: 0, h: 0 };
				this.rects[count] = rect;
			}
			rect.left = left;
			rect.right = right;
			rect.y = y;
			rect.h = label.height;
			count++;
		}
		reserveLabelRects(this.rects, count);
	}

	/** Down to its ring, or back to its full self. Written only on the change —
	 *  this runs every frame. */
	private setLabelDimmed(label: DrawnLabel, dimmed: boolean): void {
		if (label.dimmed === dimmed) return;
		label.dimmed = dimmed;
		label.object.element.classList.toggle('scene-path-label--dim', dimmed);
	}

	private clear(): void {
		for (const arc of this.arcs) {
			this.group.remove(arc.line);
			arc.line.geometry.dispose();
			(arc.line.material as ShaderMaterial).dispose();
		}
		for (const marker of [...this.markers, ...(this.craft ? [this.craft] : [])]) {
			this.group.remove(marker.sprite);
			const material = marker.sprite.material as SpriteMaterial;
			material.map?.dispose();
			material.dispose();
		}
		for (const label of this.labels) {
			this.group.remove(label.object);
			// The CSS2D renderer parents the element to its own container, so removing
			// the object is not enough to take the DOM node with it.
			label.object.element.remove();
		}
		this.arcs = [];
		this.rings = [];
		this.markers = [];
		this.labels = [];
		this.craft = null;
		this.path = null;
		this.center = null;
	}

	dispose(): void {
		this.clear();
		this.scene.remove(this.group);
	}
}
