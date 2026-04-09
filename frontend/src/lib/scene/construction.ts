import {
	CanvasTexture,
	Float32BufferAttribute,
	Group,
	Mesh,
	MeshBasicMaterial,
	MeshStandardMaterial,
	type Object3D,
	Points,
	PointLight,
	PointsMaterial,
	Scene,
	SphereGeometry,
	type Sprite
} from 'three';
import type { Lensflare } from 'three/addons/objects/Lensflare.js';
import { resolveBodyColor } from '$lib/utils';
import { kmToScene } from '$lib/math/units';
import { ObjectType, effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { TextureLoader, type Texture } from 'three';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import { createLabel, getLabelVariant } from './label/factory';
import {
	makeCircleTexture,
	makeOrbitLine,
	makePointCloud,
	makeStarGlow,
	makeStarPoint
} from './builders';
import type { BodyObjects } from './types';

const F32_MAX = 3.4028235e38;
function isF32Safe(v: number): boolean {
	return isFinite(v) && Math.abs(v) <= F32_MAX;
}

function filterFinitePositions(bodies: PositionedBody[]): PositionedBody[] {
	return bodies.filter((b) => {
		const [x, y, z] = b.position;
		if (isF32Safe(x) && isF32Safe(y) && isF32Safe(z)) return true;
		console.warn(
			`Skipping body with non-finite position: id=${b.data.id} name=${b.data.name}`,
			b.position
		);
		return false;
	});
}

function excludePromoted(bodies: PositionedBody[], promotedIds?: Set<string>): PositionedBody[] {
	if (!promotedIds || promotedIds.size === 0) return bodies;
	return bodies.filter((b) => !promotedIds.has(b.data.id));
}

function positionsArray(
	bodies: PositionedBody[],
	basisPos: [number, number, number] = [0, 0, 0]
): Float32Array {
	const arr = new Float32Array(bodies.length * 3);
	for (let i = 0; i < bodies.length; i++) {
		arr[i * 3] = bodies[i].position[0] - basisPos[0];
		arr[i * 3 + 1] = bodies[i].position[1] - basisPos[1];
		arr[i * 3 + 2] = bodies[i].position[2] - basisPos[2];
	}
	return arr;
}

export function buildMajorBodies(
	bodies: PositionedBody[],
	scene: Scene,
	clickables: Mesh[],
	meshToBody: Map<Mesh, PositionedBody>,
	bodyObjects: Map<string, BodyObjects>,
	circleTexture: CanvasTexture,
	rendererElement: HTMLCanvasElement,
	handleFocus: (body: PositionedBody) => void
): void {
	for (const body of bodies) {
		const id = body.data.id;
		const isVirtual =
			body.data.objectType === ObjectType.BARYCENTER ||
			body.data.objectType === ObjectType.LAGRANGE_POINT;
		const color = resolveBodyColor(id, body.data.objectType);
		const radius = kmToScene(effectiveRadiusKm(body.data));
		const isStar = body.data.objectType === ObjectType.STAR;

		const group = new Group();
		// Position set to origin — repositionAll() applies focus-relative offset each frame
		group.position.set(0, 0, 0);

		let mesh: Mesh | null = null;
		let starPoint: Points | null = null;
		let coronaSprite: Sprite | null = null;
		let lensflareObj: Lensflare | null = null;
		const extraObjects: Object3D[] = [];
		if (!isVirtual) {
			if (isStar) {
				const light = new PointLight(0xffffff, 2, 0, 0);
				scene.add(light);
				const { corona, lensflare } = makeStarGlow(radius, color);
				coronaSprite = corona;
				lensflareObj = lensflare;
				scene.add(corona);
				scene.add(lensflare);
				starPoint = makeStarPoint(color, circleTexture);
				scene.add(starPoint);
				extraObjects.push(light, corona, lensflare, starPoint);
			}

			const segments = isStar ? 96 : 64;
			const geometry = new SphereGeometry(radius, segments, segments);
			const material = isStar
				? new MeshBasicMaterial({ color })
				: new MeshStandardMaterial({ color });
			mesh = new Mesh(geometry, material);
			if (!isStar) {
				mesh.receiveShadow = true;
				const canCast =
					body.data.objectType === ObjectType.PLANET ||
					body.data.objectType === ObjectType.DWARF_PLANET ||
					body.data.objectType === ObjectType.MOON;
				mesh.castShadow = canCast;
			}
			scene.add(mesh);
			extraObjects.push(mesh);

			clickables.push(mesh);
			meshToBody.set(mesh, body);
		}

		// CSS2D label
		const variant = getLabelVariant(body);
		const isLarge = isStar || body.data.objectType === ObjectType.PLANET;
		const label = createLabel(
			color,
			body.data.name ?? '',
			variant,
			() => handleFocus(body),
			isLarge
		);
		if (label) {
			// Forward wheel events so OrbitControls zoom still works when hovering a label
			label.element.addEventListener(
				'wheel',
				(e: Event) => {
					const we = e as WheelEvent;
					rendererElement.dispatchEvent(
						new WheelEvent('wheel', {
							deltaY: we.deltaY,
							deltaMode: we.deltaMode,
							bubbles: true,
							cancelable: true
						})
					);
					we.preventDefault();
				},
				{ passive: false }
			);
			// Forward pointer events so OrbitControls can pan/pinch from labels.
			// Defer until pointer moves >3px so taps still fire click on
			// the label. Once forwarded, setPointerCapture on the canvas steals
			// subsequent events, which suppresses the label's click
			label.element.addEventListener('pointerdown', (e: PointerEvent) => {
				const downX = e.clientX;
				const downY = e.clientY;
				const savedDown = e; // keep the original event for deferred forwarding
				const onMove = (me: PointerEvent) => {
					const dx = me.clientX - downX;
					const dy = me.clientY - downY;
					if (dx * dx + dy * dy > 9) {
						cleanup();
						rendererElement.dispatchEvent(new PointerEvent('pointerdown', savedDown));
						rendererElement.dispatchEvent(new PointerEvent('pointermove', me));
					}
				};
				const onUp = () => cleanup();
				const cleanup = () => {
					window.removeEventListener('pointermove', onMove);
					window.removeEventListener('pointerup', onUp);
				};
				window.addEventListener('pointermove', onMove);
				window.addEventListener('pointerup', onUp);
			});
			group.add(label);
		}

		// Orbit line — built later in buildOrbitLines() to defer 100K+ Kepler solves
		const orbitLine = null;

		scene.add(group);
		const labelHalo = label ? (label.element.firstElementChild as HTMLElement) : null;
		if (labelHalo) {
			labelHalo.dataset.origBorder = labelHalo.style.border;
		}
		bodyObjects.set(id, {
			body,
			group,
			mesh,
			label,
			labelHalo,
			extraObjects,
			corona: coronaSprite,
			lensflare: lensflareObj,
			starPoint,
			orbitLine,
			radiusScene: radius
		});
	}
}

export function buildOrbitLines(
	bodyObjects: Map<string, BodyObjects>,
	scene: Scene,
	basisPos: [number, number, number] = [0, 0, 0]
): void {
	for (const [, bo] of bodyObjects) {
		if (bo.orbitLine !== null) continue;
		const { body } = bo;
		if (!body.orbitElements || body.data.objectType === ObjectType.STAR) continue;
		const color = resolveBodyColor(body.data.id, body.data.objectType);
		const line = makeOrbitLine(body, color, basisPos);
		scene.add(line);
		bo.orbitLine = line;
	}
}

export function buildPointClouds(
	ctx: ContextManager,
	scene: Scene,
	circleTexture: CanvasTexture,
	basisPos: [number, number, number] = [0, 0, 0],
	promotedIds?: Set<string>
): {
	asteroidPoints: Map<string, Points>;
	spacecraftPoints: Map<string, Points>;
	moonPoints: Map<string, Points>;
} {
	const asteroidPoints = new Map<string, Points>();
	const spacecraftPoints = new Map<string, Points>();
	const moonPoints = new Map<string, Points>();

	// Asteroid point clouds (one per zone)
	for (const [zone, bodies] of ctx.asteroidBodiesByZone) {
		const filtered = excludePromoted(bodies, promotedIds);
		if (filtered.length > 0) {
			const pts = makePointCloud(filtered, circleTexture, basisPos);
			asteroidPoints.set(zone, pts);
			scene.add(pts);
		}
	}

	// Spacecraft point clouds (one per parent body)
	for (const [groupParentId, bodies] of ctx.spacecraftByParent.entries()) {
		const filtered = excludePromoted(bodies, promotedIds);
		if (filtered.length === 0) continue;
		const points = makePointCloud(filtered, circleTexture, basisPos);
		spacecraftPoints.set(groupParentId, points);
		scene.add(points);
	}

	// Moon point clouds (one per parent body, initially hidden)
	const moonsByParent = new Map<string, PositionedBody[]>();
	for (const body of ctx.majorBodies) {
		if (body.data.objectType === ObjectType.MOON) {
			const list = moonsByParent.get(body.data.parentId) ?? [];
			list.push(body);
			moonsByParent.set(body.data.parentId, list);
		}
	}
	for (const [parentId, moons] of moonsByParent) {
		const pts = makePointCloud(moons, circleTexture, basisPos);
		(pts.material as PointsMaterial).depthTest = true;
		pts.visible = false;
		moonPoints.set(parentId, pts);
		scene.add(pts);
	}

	return { asteroidPoints, spacecraftPoints, moonPoints };
}

/**
 * Rebuilds only the dirty asteroid and spacecraft point clouds.
 * Returns new Points objects that need to be added to the scene (caller
 * should stagger these across frames to avoid GPU-upload hitches).
 */
export function rebuildMinorPointClouds(
	ctx: ContextManager,
	circleTexture: CanvasTexture,
	asteroidPoints: Map<string, Points>,
	spacecraftPoints: Map<string, Points>,
	basisPos: [number, number, number] = [0, 0, 0],
	promotedIds?: Set<string>
): Points[] {
	const pendingAdd: Points[] = [];

	// Asteroid clouds — only dirty zones
	for (const zone of ctx.dirtyAsteroidZones) {
		const bodies = ctx.asteroidBodiesByZone.get(zone);
		if (!bodies || bodies.length === 0) continue;
		const valid = filterFinitePositions(excludePromoted(bodies, promotedIds));
		const existing = asteroidPoints.get(zone);
		if (existing) {
			existing.geometry.setAttribute(
				'position',
				new Float32BufferAttribute(positionsArray(valid, basisPos), 3)
			);
		} else {
			const pts = makePointCloud(valid, circleTexture, basisPos);
			asteroidPoints.set(zone, pts);
			pendingAdd.push(pts);
		}
	}

	// Spacecraft clouds — only dirty groups
	for (const groupParentId of ctx.dirtySpacecraftGroups) {
		const bodies = ctx.spacecraftByParent.get(groupParentId);
		if (!bodies || bodies.length === 0) continue;
		const valid = filterFinitePositions(excludePromoted(bodies, promotedIds));
		const existing = spacecraftPoints.get(groupParentId);
		if (existing) {
			existing.geometry.setAttribute(
				'position',
				new Float32BufferAttribute(positionsArray(valid, basisPos), 3)
			);
		} else {
			const points = makePointCloud(valid, circleTexture, basisPos);
			spacecraftPoints.set(groupParentId, points);
			pendingAdd.push(points);
		}
	}

	ctx.dirtyAsteroidZones.clear();
	ctx.dirtySpacecraftGroups.clear();

	return pendingAdd;
}

export async function loadBodyTexture(
	fileId: string,
	material: MeshStandardMaterial,
	textureLoader: TextureLoader,
	objectFileFlag = 1
): Promise<void> {
	if (objectFileFlag === 0) return;
	const detail = await fetchObjectDetail(fileId, objectFileFlag);
	if (!detail.global?.map_texture_available) return;
	const texture = await new Promise<Texture>((resolve, reject) => {
		textureLoader.load(`/data/v1/textures/${fileId}/low.webp`, resolve, undefined, reject);
	});
	material.map = texture;
	material.color.set(0xffffff);
	material.needsUpdate = true;
}

/**
 * Fetch the system texture metadata and preload low-res textures for all bodies in that system.
 * The metadata file is keyed by barycenter ID (e.g. naif-3, naif-5).
 */
export async function loadSystemTextures(
	barycenterId: string,
	bodyObjects: Map<string, BodyObjects>,
	textureLoader: TextureLoader,
	textureLoaded: Set<string>
): Promise<void> {
	let meta: Record<string, { tiers: string[] }>;
	try {
		const resp = await fetch(`/data/v1/textures/systems/${barycenterId}.json`);
		if (!resp.ok) return;
		meta = await resp.json();
	} catch {
		return;
	}

	const promises: Promise<void>[] = [];
	for (const bodyId of Object.keys(meta)) {
		if (textureLoaded.has(bodyId)) continue;
		textureLoaded.add(bodyId);
		const bo = bodyObjects.get(bodyId);
		if (!bo?.mesh) continue;
		const material = bo.mesh.material as MeshStandardMaterial;
		promises.push(
			new Promise<Texture>((resolve, reject) => {
				textureLoader.load(`/data/v1/textures/${bodyId}/low.webp`, resolve, undefined, reject);
			}).then((texture) => {
				material.map = texture;
				material.color.set(0xffffff);
				material.needsUpdate = true;
			})
		);
	}
	await Promise.allSettled(promises);
}

export { makeCircleTexture };
