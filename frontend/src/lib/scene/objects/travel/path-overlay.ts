/**
 * The planned trajectory, drawn on the map.
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
 */

import {
	CanvasTexture,
	Group,
	Mesh,
	Scene,
	Sprite,
	SpriteMaterial,
	Vector3,
	type ShaderMaterial
} from 'three';
// Deep imports, not the kernel's index: the renderer holds this overlay from the
// first frame, and the index re-exports Lambert, the porkchop and the vehicle
// catalogue — a chunk only `/nav` should ever pull in.
import type { PathArcKind, TrajectoryPath } from '$lib/math/travel/path';
import { eclipticToScene } from '$lib/math/travel/state';
import { buildFatLineFromThin, writeFatTrailVertices } from '$lib/scene/objects/trail/geometry';
import type { Vec3 } from '$lib/scene/animation/math';

/**
 * How each stretch of the trip is drawn. A coast is the plan itself; a drive
 * held all the way is a different kind of flying and reads warm to say so.
 */
const ARC_COLORS: Record<PathArcKind, string> = {
	cruise: '#7fdbff',
	boost: '#ffb454',
	brake: '#ff8c69'
};

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

/** Screen size of the markers, in the units an unattenuated sprite scales by. */
const STOP_SIZE = 0.018;
const MEETING_SIZE = 0.045;

/** Drawn after trails so the plan sits on top of the orbits it crosses. */
const PATH_RENDER_ORDER = 4;

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
	/** Scene units, relative to the path's centre body. */
	local: Float64Array;
	/** Scratch the rebase writes into before the fat geometry is expanded. */
	positions: Float32Array;
	alphas: Float32Array;
	count: number;
}

/** A marker and where it sits, in scene units relative to the centre body. */
interface DrawnMarker {
	sprite: Sprite;
	local: Vec3;
}

export class TravelPathOverlay {
	private readonly group = new Group();
	private arcs: DrawnArc[] = [];
	private markers: DrawnMarker[] = [];
	private path: TrajectoryPath | null = null;
	private layer: number | null = null;
	private readonly offset = new Vector3();

	constructor(private readonly scene: Scene) {
		// The arcs carry their own world offsets, so the group never moves.
		this.group.frustumCulled = false;
		this.scene.add(this.group);
	}

	/** The body every vertex is measured from; null when nothing is drawn. */
	get centerId(): string | null {
		return this.path?.centerId ?? null;
	}

	get isEmpty(): boolean {
		return this.path === null;
	}

	/** Hide the whole plan with the rest of the map furniture in immersive mode. */
	setLayer(layer: number): void {
		this.layer = layer;
		this.group.traverse((object) => object.layers.set(layer));
	}

	/**
	 * Draw `path`, replacing whatever was drawn before. Passing null clears it.
	 *
	 * The vertices land centre-relative; nothing is placed until `reposition`
	 * says where the centre body currently is.
	 */
	set(path: TrajectoryPath | null): void {
		this.clear();
		this.path = path;
		if (!path) return;

		for (const arc of path.arcs) {
			const count = arc.points.length;
			if (count < 2) continue;
			const local = new Float64Array(count * 3);
			for (let i = 0; i < count; i++) {
				const [x, y, z] = eclipticToScene(arc.points[i]);
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
				ARC_COLORS[arc.kind],
				LINE_WIDTH,
				LINE_BRIGHTNESS
			);
			line.frustumCulled = false;
			line.renderOrder = PATH_RENDER_ORDER;
			this.group.add(line);
			this.arcs.push({ line, local, positions, alphas, count });
		}

		// Where the destination will be when the craft gets there. Skipped when the
		// destination is the body everything is measured from — it is already at the
		// centre and does not move in its own frame.
		const meets = path.meeting.bodyId !== path.centerId;
		if (meets) {
			this.markers.push({
				sprite: makeSprite(ringTexture(ARC_COLORS.cruise), MEETING_SIZE),
				local: eclipticToScene(path.meeting.r) as Vec3
			});
		}
		for (const stop of path.stops) {
			// The ring already marks the arrival, and it sits on the same point; a dot
			// under it would only thicken the circle's centre.
			if (stop.kind === 'arrival' && meets) continue;
			this.markers.push({
				sprite: makeSprite(dotTexture(ARC_COLORS.cruise), STOP_SIZE),
				local: eclipticToScene(stop.r) as Vec3
			});
		}
		for (const marker of this.markers) this.group.add(marker.sprite);

		if (this.layer !== null) this.setLayer(this.layer);
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
		if (!this.path) return;
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
	}

	/**
	 * Hand the line shader the camera, which is what its vertices are ultimately
	 * drawn relative to. Same contract as the trails' own per-frame update.
	 */
	updateCameraOffset(cameraPosition: Vector3): void {
		if (this.arcs.length === 0) return;
		this.offset.set(-cameraPosition.x, -cameraPosition.y, -cameraPosition.z);
		for (const arc of this.arcs) {
			const material = arc.line.material as ShaderMaterial;
			material.uniforms.uCenterOffset.value.copy(this.offset);
		}
	}

	setVisible(visible: boolean): void {
		this.group.visible = visible;
	}

	private clear(): void {
		for (const arc of this.arcs) {
			this.group.remove(arc.line);
			arc.line.geometry.dispose();
			(arc.line.material as ShaderMaterial).dispose();
		}
		for (const marker of this.markers) {
			this.group.remove(marker.sprite);
			const material = marker.sprite.material as SpriteMaterial;
			material.map?.dispose();
			material.dispose();
		}
		this.arcs = [];
		this.markers = [];
		this.path = null;
	}

	dispose(): void {
		this.clear();
		this.scene.remove(this.group);
	}
}
