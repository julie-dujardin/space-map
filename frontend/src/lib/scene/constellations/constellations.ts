/**
 * The figures of one sky culture as lines between stars, with their names. Each line
 * ends on the star's 3D position, so from another star the figures distort as
 * the sky does.
 */

import {
	AdditiveBlending,
	BufferAttribute,
	BufferGeometry,
	Color,
	DynamicDrawUsage,
	Group,
	LineSegments,
	ShaderMaterial,
	Vector3,
	type PerspectiveCamera,
	type Scene
} from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { ExtrasolarCredit } from '$lib/fetch/extrasolar/files';
import {
	fetchSkyCulture,
	labelOf,
	type LoadedSkyCulture,
	type SkyCultureFile
} from '$lib/fetch/extrasolar/skycultures';
import { SKY_CULTURE_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import { DEFAULT_SKY_CULTURE } from '$lib/constants';
import { getLocale, host } from '$lib/host';
import {
	acceptedBodyLabelRects,
	dimmedHaloRects,
	isScreenOccluded,
	type AcceptedRect
} from '$lib/scene/label/culling';
import { RetryBackoff } from '$lib/fetch/retry-backoff';
import { attachCanvasForwarders } from '$lib/scene/label/forward';
import { onLinkTap } from '$lib/scene/objects/tap-not-drag';
import { clampToFarGlsl } from '$lib/scene/setup/depth-mode';
import { constellationsWanted, sceneSettings, type PageSky } from '$lib/scene/settings.svelte';
import { STAR_RENDER_ORDER } from '$lib/scene/starfield/starfield';
import { sceneToTree, treeMatrixElements, treeToScene } from '$lib/scene/starfield/tree';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { SwitchFade } from '$lib/scene/visibility/switch-fade';
import { liveScreenOccluders } from '$lib/scene/visibility/update';
import '$lib/scene/label/label.css';

const LINE_COLOUR = new Color(0.16, 0.24, 0.38);
/** Added on top of the lines of a hovered label's figure. */
const HOVER_COLOUR = new Color(0.26, 0.32, 0.4);
/** Float32 would put a line end some AU off a far star, so the lines are
 *  stored from a point this close to the camera. */
const REBASE_PC = 1e-3;
/** Longest fade step: an idle map's first frame must not skip the fade. */
const MAX_STEP_MS = 50;
/** The text box of a 12px label. */
const LABEL_HALF_HEIGHT_PX = 7;
const UNMEASURED_LABEL_PX = 60;
/** Under this share, a label is not worth a DOM element on screen. */
const LABEL_MIN_SHARE = 0.02;
/** Under this share, a label is too faint to take a click from the map. */
const LABEL_CLICK_SHARE = 0.2;

const NO_CREDITS: readonly ExtrasolarCredit[] = [];

type Vec3 = [number, number, number];

export interface ConstellationLabel {
	name: string;
	/** The figure's segment in its URL; null with no page. */
	figure: string | null;
	/** pc, in the frame of the render tree. */
	anchor: Vec3;
	/** Lines of the figure: where two labels meet, the larger figure keeps its name. */
	weight: number;
	/** The figure's first vertex in `positions`. */
	firstVertex: number;
}

/** A label's place on screen. `shown` is the answer of {@link cullLabels}. */
export interface LabelBox {
	left: number;
	right: number;
	top: number;
	bottom: number;
	inView: boolean;
	/** A body stands in front of the label. */
	occluded: boolean;
	shown: boolean;
}

export interface ConstellationShape {
	/** Two points per line, in the frame of the render tree. */
	positions: Float64Array;
	labels: ConstellationLabel[];
}

/** The middle of the stars as the Sun sees them, at their median distance: a
 *  mean of positions or distances would lean to one far member. */
function anchorOf(stars: readonly Vec3[]): Vec3 {
	const sum: Vec3 = [0, 0, 0];
	const distances: number[] = [];
	for (const [x, y, z] of stars) {
		const r = Math.hypot(x, y, z);
		distances.push(r);
		sum[0] += x / r;
		sum[1] += y / r;
		sum[2] += z / r;
	}
	distances.sort((a, b) => a - b);
	const middle = stars.length >> 1;
	const median =
		stars.length % 2 ? distances[middle] : (distances[middle - 1] + distances[middle]) / 2;
	const scale = median / Math.hypot(...sum);
	return [sum[0] * scale, sum[1] * scale, sum[2] * scale];
}

/** The stars of the largest connected part of a figure: Serpens is in two,
 *  and a label between them lands in Ophiuchus. */
function largestPart(lines: readonly (readonly [Vec3, Vec3])[]): Vec3[] {
	const parts: Set<Vec3>[] = [];
	for (const line of lines) {
		const part = new Set<Vec3>(line);
		for (let i = parts.length - 1; i >= 0; i--) {
			if (!line.some((star) => parts[i].has(star))) continue;
			for (const star of parts[i]) part.add(star);
			parts.splice(i, 1);
		}
		parts.push(part);
	}
	return [...parts.reduce((a, b) => (b.size > a.size ? b : a))];
}

function placedMembers(file: SkyCultureFile, indexes: readonly number[]): Vec3[] {
	return indexes.map((index) => file.members[index].position).filter((star) => star !== undefined);
}

/** The lines and labels of a culture. A ray helper is a pointer, no figure. A
 *  line to a member with no position is left out, and a star group has a label
 *  and no lines. */
export function constellationShape(file: SkyCultureFile, locale: string): ConstellationShape {
	const points: number[] = [];
	const labels: ConstellationLabel[] = [];
	for (const figure of file.figures) {
		if (figure.ray_helper) continue;
		const lines: [Vec3, Vec3][] = [];
		const firstVertex = points.length / 3;
		for (const chain of figure.lines) {
			for (let i = 1; i < chain.length; i++) {
				const a = file.members[chain[i - 1]].position;
				const b = file.members[chain[i]].position;
				if (!a || !b) continue;
				points.push(...a, ...b);
				lines.push([a, b]);
			}
		}
		const name = labelOf(figure, locale);
		const stars = lines.length > 0 ? largestPart(lines) : placedMembers(file, figure.group ?? []);
		if (!name || stars.length === 0) continue;
		labels.push({
			name,
			figure: figure.slug ?? null,
			anchor: anchorOf(stars),
			weight: lines.length,
			firstVertex
		});
	}
	labels.sort((a, b) => b.weight - a.weight);
	return { positions: new Float64Array(points), labels };
}

/** A label lies past every body, so any corner of its text can reach a limb. */
function behindBody({ left, right, top, bottom }: LabelBox): boolean {
	const hides = (x: number, y: number) => isScreenOccluded(x, y, Infinity, '', liveScreenOccluders);
	return hides(left, top) || hides(right, top) || hides(left, bottom) || hides(right, bottom);
}

function boxesMeet(a: LabelBox, b: LabelBox): boolean {
	return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function meetsBodyRect(box: LabelBox, rect: AcceptedRect): boolean {
	return (
		box.left < rect.right &&
		box.right > rect.left &&
		box.top < rect.y + rect.h / 2 &&
		box.bottom > rect.y - rect.h / 2
	);
}

/** Set `shown` on boxes given most important first: a box goes when it meets a
 *  body's rect or a box kept before it. */
export function cullLabels(
	boxes: readonly LabelBox[],
	bodies: readonly { rects: readonly AcceptedRect[]; count: number }[]
): void {
	for (let i = 0; i < boxes.length; i++) {
		const box = boxes[i];
		box.shown = box.inView && !box.occluded;
		for (const { rects, count } of bodies) {
			for (let j = 0; box.shown && j < count; j++) {
				if (meetsBodyRect(box, rects[j])) box.shown = false;
			}
		}
		for (let j = 0; box.shown && j < i; j++) {
			if (boxes[j].shown && boxesMeet(box, boxes[j])) box.shown = false;
		}
	}
}

function lineMaterial(colour: Color): ShaderMaterial {
	return new ShaderMaterial({
		uniforms: { uColour: { value: colour }, uGain: { value: 0 } },
		vertexShader: /* glsl */ `
void main() {
	gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
	// Past the far plane a line stays on it, behind everything else.
	${clampToFarGlsl()}
}
`,
		fragmentShader: /* glsl */ `
uniform vec3 uColour;
uniform float uGain;

void main() {
	gl_FragColor = vec4(uColour * uGain, 1.0);
}
`,
		blending: AdditiveBlending,
		transparent: true,
		depthTest: true,
		depthWrite: false
	});
}

/** A link where the host has pages. Every label takes the mouse, which lights
 *  its figure, and hands a drag on to the map. */
function makeLabel(
	{ name, figure }: ConstellationLabel,
	culture: string,
	mapLayer: number,
	canvas: HTMLCanvasElement,
	onSelect: ConstellationSelect,
	onHover: (hovered: boolean) => void
): CSS2DObject {
	const element = document.createElement('a');
	element.className = 'scene-constellation-label';
	element.dir = 'auto';
	element.textContent = name;
	element.draggable = false;
	const slug = `${SKY_CULTURE_SLUG_PREFIX}${culture}`;
	const href = figure && host().groupHref(slug, name, figure);
	// With no page, a click belongs to what lies under the label.
	attachCanvasForwarders(element, canvas, !href);
	if (figure && href) {
		element.href = href;
		element.tabIndex = -1;
		onLinkTap(element, () => onSelect(slug, figure, name));
	}
	// A touch has no hover: its enter and leave wrap a tap.
	element.addEventListener('pointerenter', (event) => {
		if (event.pointerType !== 'touch') onHover(true);
	});
	element.addEventListener('pointerleave', () => onHover(false));
	const object = new CSS2DObject(element);
	object.layers.set(mapLayer);
	return object;
}

interface ConstellationLabelState {
	object: CSS2DObject;
	figure: string | null;
	anchor: Vec3;
	firstVertex: number;
	/** Vertices of the figure's lines. */
	vertices: number;
	width: number;
	box: LabelBox;
}

export type ConstellationSelect = (slug: string, figure: string, name: string) => void;
/** Turn the camera to a direction of the sky, or back to the focus with null. */
export type ConstellationAim = (direction: Vector3 | null, instant: boolean) => void;

/** Whether `page` has a turn to start now. A turn replaces a running flight,
 *  so it waits for the camera to land. */
export function pageAimDue(
	page: PageSky,
	aimed: string | null,
	shown: string | null,
	flying: boolean
): boolean {
	return (
		!!page.figure && !page.hidden && page.figure !== aimed && page.culture === shown && !flying
	);
}

export class ConstellationSystem {
	private readonly lines = new Group();
	private readonly names = new Group();
	private readonly material = lineMaterial(LINE_COLOUR);
	private readonly geometry = new BufferGeometry();
	/** The lines of the hovered figure, a range of the same vertices. */
	private readonly hoverMaterial = lineMaterial(HOVER_COLOUR);
	private readonly hoverGeometry = new BufferGeometry();
	private readonly hoverLines = new LineSegments(this.hoverGeometry, this.hoverMaterial);
	private readonly fade = new SwitchFade(false);
	private readonly matrix: number[] = [];
	private positions: Float64Array = new Float64Array(0);
	private readonly origin: Vec3 = [Infinity, 0, 0];
	private readonly direction = new Vector3();
	private labels: ConstellationLabelState[] = [];
	private hovered: ConstellationLabelState | null = null;
	private boxes: LabelBox[] = [];
	private readonly forward = new Vector3();
	private readonly retry: RetryBackoff<string>;
	private credits: readonly ExtrasolarCredit[] = [];
	/** The culture on show, and the one on its way: only the newest pick lands. */
	private shown: string | null = null;
	private pending: string | null = null;
	/** The figure the camera was last asked to turn to. */
	private aimed: string | null = null;
	/** The camera is turned away from the focus for a page. */
	private turned = false;
	private labelOpacity = '';
	private lastFrameMs = 0;
	private disposed = false;

	constructor(
		private readonly ctx: ContextManager,
		private readonly scene: Scene,
		private readonly mapLayer: number,
		private readonly invalidate: () => void,
		private readonly canvas: HTMLCanvasElement,
		private readonly onSelect: ConstellationSelect,
		private readonly aim: ConstellationAim,
		private readonly flying: () => boolean
	) {
		this.retry = new RetryBackoff<string>(invalidate);
		this.lines.name = 'constellations';
		this.lines.matrixAutoUpdate = false;
		this.lines.visible = false;
		this.names.name = 'constellation-labels';
		this.names.visible = false;
		const segments = new LineSegments(this.geometry, this.material);
		segments.frustumCulled = false;
		segments.renderOrder = STAR_RENDER_ORDER + 1;
		segments.layers.set(mapLayer);
		this.hoverLines.frustumCulled = false;
		this.hoverLines.renderOrder = segments.renderOrder + 1;
		this.hoverLines.layers.set(mapLayer);
		this.hoverLines.visible = false;
		this.lines.add(segments, this.hoverLines);
		scene.add(this.lines, this.names);
	}

	get fading(): boolean {
		return this.fade.fading;
	}

	wanted(): boolean {
		return constellationsWanted(sceneSettings(), (id) => this.ctx.layers.isVisible(id));
	}

	/** Follow the page in view: turn to its figure once the figures are
	 *  in and the camera has landed, and back to the focus when the reader
	 *  leaves the sky pages. With no sky to see, the camera stays, and a later
	 *  dawn does not move it. */
	private followPage(camera: PerspectiveCamera, focus: Vec3, gain: number): void {
		const page = sceneSettings().pageSky;
		if (!page) {
			if (this.turned) this.aim(null, false);
			this.turned = false;
			this.aimed = null;
			return;
		}
		if (!page.figure) this.aimed = null;
		if (!pageAimDue(page, this.aimed, this.shown, this.flying())) return;
		const label = this.labels.find(({ figure }) => figure === page.figure);
		if (!label) return;
		this.aimed = page.figure;
		if (gain <= 0 || !this.wanted()) return;
		const [cx, cy, cz] = sceneToTree(
			camera.position.x + focus[0],
			camera.position.y + focus[1],
			camera.position.z + focus[2]
		);
		const [x, y, z] = label.anchor;
		this.aim(treeToScene(x - cx, y - cy, z - cz, this.direction).normalize(), page.opening);
		this.turned = true;
	}

	private request(key: string): void {
		if (key === this.shown) this.pending = null;
		else if (key !== this.pending && !this.retry.waiting(key)) void this.load(key);
	}

	private async load(key: string): Promise<void> {
		this.pending = key;
		try {
			const culture = await fetchSkyCulture(key);
			if (key !== this.pending || this.disposed) return;
			this.show(culture, key);
		} catch (err) {
			console.warn('[constellations] the figures did not load:', err);
			this.retry.fail(key);
		} finally {
			if (key === this.pending) this.pending = null;
		}
	}

	private show(culture: LoadedSkyCulture | null, key: string): void {
		this.shown = key;
		for (const { object } of this.labels) {
			object.removeFromParent();
			object.element.remove();
		}
		const shape = culture
			? constellationShape(culture.file, getLocale())
			: { positions: new Float64Array(0), labels: [] };
		this.positions = shape.positions;
		// Frees the old buffer: a size change needs a new one.
		this.geometry.dispose();
		this.hoverGeometry.dispose();
		const attribute = new BufferAttribute(new Float32Array(shape.positions.length), 3);
		this.geometry.setAttribute('position', attribute.setUsage(DynamicDrawUsage));
		this.hoverGeometry.setAttribute('position', attribute);
		this.setHovered(null);
		// The new buffer holds zeros until it is rebased.
		this.origin[0] = Infinity;
		this.labelOpacity = '';
		this.labels = shape.labels.map((label) => {
			const state: ConstellationLabelState = {
				object: makeLabel(
					label,
					culture?.file.key ?? key,
					this.mapLayer,
					this.canvas,
					this.onSelect,
					(hovered) => {
						if (hovered) this.setHovered(state);
						else if (this.hovered === state) this.setHovered(null);
					}
				),
				figure: label.figure,
				anchor: label.anchor,
				firstVertex: label.firstVertex,
				vertices: 2 * label.weight,
				width: 0,
				box: {
					left: 0,
					right: 0,
					top: 0,
					bottom: 0,
					inView: false,
					occluded: false,
					shown: false
				}
			};
			return state;
		});
		this.boxes = this.labels.map((label) => label.box);
		for (const { object } of this.labels) this.names.add(object);
		this.credits = culture?.credits ?? NO_CREDITS;
		this.invalidate();
	}

	private setHovered(label: ConstellationLabelState | null): void {
		if (label === this.hovered) return;
		this.hovered = label;
		this.hoverLines.visible = label !== null;
		if (label) this.hoverGeometry.setDrawRange(label.firstVertex, label.vertices);
		this.invalidate();
	}

	private rebase(x: number, y: number, z: number): void {
		const attribute = this.geometry.getAttribute('position') as BufferAttribute;
		const out = attribute.array;
		for (let i = 0; i < out.length; i += 3) {
			out[i] = this.positions[i] - x;
			out[i + 1] = this.positions[i + 1] - y;
			out[i + 2] = this.positions[i + 2] - z;
		}
		attribute.needsUpdate = true;
		this.origin[0] = x;
		this.origin[1] = y;
		this.origin[2] = z;
	}

	/** Per drawn frame. `focus` is the floating origin (scene units from the
	 *  barycentre); `gain` dims the lines with the sky. */
	update(
		camera: PerspectiveCamera,
		focus: Vec3,
		gain: number,
		nowMs: number,
		viewportH: number
	): void {
		const dtMs = this.lastFrameMs ? Math.min(nowMs - this.lastFrameMs, MAX_STEP_MS) : 0;
		this.lastFrameMs = nowMs;
		const wanted = this.wanted();
		const settings = sceneSettings();
		if (wanted) {
			this.request(
				settings.pageSky?.culture ?? settings.constellationCulture ?? DEFAULT_SKY_CULTURE
			);
		}
		this.followPage(camera, focus, gain);
		const ready = this.labels.length > 0 || this.positions.length > 0;
		this.fade.step(wanted && ready, dtMs);
		const share = this.fade.share;
		if (share === 0 && !this.lines.visible) return;

		const wx = camera.position.x + focus[0];
		const wy = camera.position.y + focus[1];
		const wz = camera.position.z + focus[2];
		const [cx, cy, cz] = sceneToTree(wx, wy, wz);
		const drawn = share * gain > 0;
		this.ctx.credits.setConstellations(drawn ? this.credits : NO_CREDITS);

		this.lines.visible = drawn;
		this.material.uniforms.uGain.value = share * gain;
		this.hoverMaterial.uniforms.uGain.value = share * gain;
		if (drawn) {
			const [ox, oy, oz] = this.origin;
			if (Math.hypot(cx - ox, cy - oy, cz - oz) > REBASE_PC) this.rebase(cx, cy, cz);
			const shift = treeToScene(this.origin[0], this.origin[1], this.origin[2], this.direction);
			const shifted: Vec3 = [focus[0] - shift.x, focus[1] - shift.y, focus[2] - shift.z];
			this.lines.matrix.fromArray(treeMatrixElements(shifted, this.matrix));
			this.lines.matrixWorldNeedsUpdate = true;
		}

		const labelShare = this.ctx.layers.isVisible('labels') ? share * gain : 0;
		this.names.visible = labelShare >= LABEL_MIN_SHARE;
		if (!this.names.visible) {
			this.setHovered(null);
			return;
		}
		const opacity = labelShare.toFixed(2);
		if (opacity !== this.labelOpacity) {
			this.labelOpacity = opacity;
			const pointerEvents = labelShare < LABEL_CLICK_SHARE ? 'none' : '';
			for (const { object } of this.labels) {
				object.element.style.opacity = opacity;
				object.element.style.pointerEvents = pointerEvents;
			}
		}
		// Inside the depth range, or the label pass drops them.
		const reach = Math.sqrt(camera.near * camera.far);
		camera.getWorldDirection(this.forward);
		const screenW = viewportH * camera.aspect;
		for (const label of this.labels) {
			const { object, anchor, box } = label;
			treeToScene(anchor[0] - cx, anchor[1] - cy, anchor[2] - cz, this.direction).normalize();
			object.position.copy(camera.position).addScaledVector(this.direction, reach);
			// Forward depth loses the sign of a far point behind the camera.
			box.inView = this.direction.dot(this.forward) > 0;
			if (!box.inView) continue;
			// An element measures 0 until the label pass first lays it out.
			label.width ||= object.element.offsetWidth;
			const halfWidth = (label.width || UNMEASURED_LABEL_PX) / 2;
			this.direction.copy(object.position).project(camera);
			const x = (this.direction.x * 0.5 + 0.5) * screenW;
			const y = (-this.direction.y * 0.5 + 0.5) * viewportH;
			box.left = x - halfWidth;
			box.right = x + halfWidth;
			box.top = y - LABEL_HALF_HEIGHT_PX;
			box.bottom = y + LABEL_HALF_HEIGHT_PX;
			box.occluded = behindBody(box);
		}
		cullLabels(this.boxes, [acceptedBodyLabelRects, dimmedHaloRects]);
		for (const { object, box, width } of this.labels) {
			// Laid out once whatever it meets, or a hidden label is never measured.
			object.visible = box.shown || (box.inView && !box.occluded && width === 0);
		}
		// A hidden element sends no leave event.
		if (this.hovered && !this.hovered.box.shown) this.setHovered(null);
	}

	dispose(): void {
		this.disposed = true;
		this.ctx.credits.setConstellations(NO_CREDITS);
		for (const { object } of this.labels) object.element.remove();
		this.geometry.dispose();
		this.material.dispose();
		this.hoverGeometry.dispose();
		this.hoverMaterial.dispose();
		this.lines.removeFromParent();
		this.names.removeFromParent();
	}
}
