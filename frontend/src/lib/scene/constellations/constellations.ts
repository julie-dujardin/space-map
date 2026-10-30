/**
 * The IAU constellations as lines between stars, with their names. Each line
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
	type SkyCultureFigure,
	type SkyCultureFile
} from '$lib/fetch/extrasolar/skycultures';
import { getLocale } from '$lib/host';
import {
	acceptedBodyLabelRects,
	dimmedHaloRects,
	type AcceptedRect
} from '$lib/scene/label/culling';
import { RetryBackoff } from '$lib/fetch/retry-backoff';
import { clampToFarGlsl } from '$lib/scene/setup/depth-mode';
import { sceneSettings } from '$lib/scene/settings.svelte';
import { STAR_RENDER_ORDER } from '$lib/scene/starfield/starfield';
import { sceneToTree, treeMatrixElements, treeToScene } from '$lib/scene/starfield/tree';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { SwitchFade } from '$lib/scene/visibility/switch-fade';
import '$lib/scene/label/label.css';

/** Same stars and lines as the IAU's own charts. */
const CULTURE = 'modern_iau';
const LINE_COLOUR = new Color(0.16, 0.24, 0.38);
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

const NO_CREDITS: readonly ExtrasolarCredit[] = [];

type Vec3 = [number, number, number];

export interface ConstellationLabel {
	name: string;
	/** pc, in the frame of the render tree. */
	anchor: Vec3;
	/** Lines of the figure: where two labels meet, the larger figure keeps its name. */
	weight: number;
}

/** A label's place on screen. `shown` is the answer of {@link cullLabels}. */
export interface LabelBox {
	left: number;
	right: number;
	top: number;
	bottom: number;
	inView: boolean;
	shown: boolean;
}

export interface ConstellationShape {
	/** Two points per line, in the frame of the render tree. */
	positions: Float64Array;
	labels: ConstellationLabel[];
}

function labelOf(figure: SkyCultureFigure, locale: string): string {
	const name = figure.names[0];
	return figure.labels?.[locale] ?? name?.native ?? name?.english ?? figure.id;
}

/** The middle of the stars as the Sun sees them, at their mean distance: a
 *  mean of positions would lean to the farthest stars. */
function anchorOf(stars: readonly Vec3[]): Vec3 {
	const sum: Vec3 = [0, 0, 0];
	let distance = 0;
	for (const [x, y, z] of stars) {
		const r = Math.hypot(x, y, z);
		distance += r;
		sum[0] += x / r;
		sum[1] += y / r;
		sum[2] += z / r;
	}
	const scale = distance / stars.length / Math.hypot(...sum);
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

/** The lines and labels of a culture's constellations. A line to a member
 *  with no position is left out. */
export function constellationShape(file: SkyCultureFile, locale: string): ConstellationShape {
	const points: number[] = [];
	const labels: ConstellationLabel[] = [];
	for (const figure of file.figures) {
		if (figure.kind !== 'constellation') continue;
		const lines: [Vec3, Vec3][] = [];
		for (const chain of figure.lines) {
			for (let i = 1; i < chain.length; i++) {
				const a = file.members[chain[i - 1]].position;
				const b = file.members[chain[i]].position;
				if (!a || !b) continue;
				points.push(...a, ...b);
				lines.push([a, b]);
			}
		}
		if (lines.length === 0) continue;
		labels.push({
			name: labelOf(figure, locale),
			anchor: anchorOf(largestPart(lines)),
			weight: lines.length
		});
	}
	labels.sort((a, b) => b.weight - a.weight);
	return { positions: new Float64Array(points), labels };
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
		box.shown = box.inView;
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

function lineMaterial(): ShaderMaterial {
	return new ShaderMaterial({
		uniforms: { uColour: { value: LINE_COLOUR }, uGain: { value: 0 } },
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

function makeLabel(name: string, mapLayer: number): CSS2DObject {
	const element = document.createElement('div');
	element.className = 'scene-constellation-label';
	element.dir = 'auto';
	element.textContent = name;
	const object = new CSS2DObject(element);
	object.layers.set(mapLayer);
	return object;
}

export class ConstellationSystem {
	private readonly lines = new Group();
	private readonly names = new Group();
	private readonly material = lineMaterial();
	private readonly geometry = new BufferGeometry();
	private readonly fade = new SwitchFade(false);
	private readonly matrix: number[] = [];
	private positions: Float64Array = new Float64Array(0);
	private readonly origin: Vec3 = [Infinity, 0, 0];
	private readonly direction = new Vector3();
	private labels: { object: CSS2DObject; anchor: Vec3; width: number; box: LabelBox }[] = [];
	private boxes: LabelBox[] = [];
	private readonly forward = new Vector3();
	private readonly retry: RetryBackoff<string>;
	private credits: readonly ExtrasolarCredit[] = [];
	private loaded = false;
	private loading = false;
	private labelOpacity = '';
	private lastFrameMs = 0;
	private disposed = false;

	constructor(
		private readonly ctx: ContextManager,
		private readonly scene: Scene,
		private readonly mapLayer: number,
		private readonly invalidate: () => void
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
		this.lines.add(segments);
		scene.add(this.lines, this.names);
	}

	get fading(): boolean {
		return this.fade.fading;
	}

	private wanted(): boolean {
		const settings = sceneSettings();
		// The sky is the skybox near the Sun and the starfield past it.
		const sky = this.ctx.layers.isVisible('stars') || this.ctx.layers.isVisible('starfield');
		return settings.showConstellations && settings.viewMode !== 'immersive' && sky;
	}

	private async load(): Promise<void> {
		this.loading = true;
		try {
			const culture = await fetchSkyCulture(CULTURE);
			this.loaded = true;
			if (!culture || this.disposed) return;
			const shape = constellationShape(culture.file, getLocale());
			this.positions = shape.positions;
			const attribute = new BufferAttribute(new Float32Array(shape.positions.length), 3);
			this.geometry.setAttribute('position', attribute.setUsage(DynamicDrawUsage));
			this.labels = shape.labels.map(({ name, anchor }) => ({
				object: makeLabel(name, this.mapLayer),
				anchor,
				width: 0,
				box: { left: 0, right: 0, top: 0, bottom: 0, inView: false, shown: false }
			}));
			this.boxes = this.labels.map((label) => label.box);
			for (const { object } of this.labels) this.names.add(object);
			this.credits = culture.credits;
			this.invalidate();
		} catch (err) {
			console.warn('[constellations] the figures did not load:', err);
			this.retry.fail(CULTURE);
		} finally {
			this.loading = false;
		}
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
		if (wanted && !this.loaded && !this.loading && !this.retry.waiting(CULTURE)) void this.load();
		const ready = this.labels.length > 0;
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
		if (!this.names.visible) return;
		const opacity = labelShare.toFixed(2);
		if (opacity !== this.labelOpacity) {
			this.labelOpacity = opacity;
			for (const { object } of this.labels) object.element.style.opacity = opacity;
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
		}
		cullLabels(this.boxes, [acceptedBodyLabelRects, dimmedHaloRects]);
		for (const { object, box, width } of this.labels) {
			// Laid out once whatever it meets, or a hidden label is never measured.
			object.visible = box.shown || (box.inView && width === 0);
		}
	}

	dispose(): void {
		this.disposed = true;
		this.ctx.credits.setConstellations(NO_CREDITS);
		for (const { object } of this.labels) object.element.remove();
		this.geometry.dispose();
		this.material.dispose();
		this.lines.removeFromParent();
		this.names.removeFromParent();
	}
}
