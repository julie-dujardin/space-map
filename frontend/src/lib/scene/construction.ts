import {
	CanvasTexture,
	Float32BufferAttribute,
	Group,
	Mesh,
	MeshBasicMaterial,
	MeshStandardMaterial,
	Points,
	PointLight,
	PointsMaterial,
	Scene,
	SphereGeometry
} from 'three';
import { BODY_COLORS, DEFAULT_BODY_COLOR, DEFAULT_BODY_RADIUS_KM } from '$lib/constants';
import { kmToScene } from '$lib/math/units';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { TextureLoader, type Texture } from 'three';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import { createLabel, getLabelVariant } from './label/factory';
import { makeCircleTexture, makeOrbitLine, makePointCloud } from './builders';
import type { BodyObjects } from './types';

export function buildMajorBodies(
	bodies: PositionedBody[],
	scene: Scene,
	clickables: Mesh[],
	meshToBody: Map<Mesh, PositionedBody>,
	bodyObjects: Map<string, BodyObjects>,
	rendererElement: HTMLCanvasElement,
	handleFocus: (body: PositionedBody) => void
): void {
	for (const body of bodies) {
		const id = body.data.id;
		const color = BODY_COLORS[id] ?? DEFAULT_BODY_COLOR;
		const rawRadiusKm = Number.isFinite(body.data.radiusKm)
			? body.data.radiusKm
			: DEFAULT_BODY_RADIUS_KM;
		const radius = kmToScene(rawRadiusKm);
		const isStar = body.data.objectType === ObjectType.STAR;

		const group = new Group();
		group.position.set(...body.position);

		if (isStar) {
			group.add(new PointLight(0xffffff, 3, 0, 0));
		}

		const segments = isStar ? 32 : 64;
		const geometry = new SphereGeometry(radius, segments, segments);
		const material = isStar
			? new MeshBasicMaterial({ color })
			: new MeshStandardMaterial({ color });
		const mesh = new Mesh(geometry, material);
		group.add(mesh);

		clickables.push(mesh);
		meshToBody.set(mesh, body);

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
			// Forward touch pointerdown events so OrbitControls sees every finger for pinch-zoom.
			// Both fingers must reach the canvas — in crowded areas both may land on labels.
			// Mouse events are NOT forwarded: setPointerCapture would steal the pointerup from
			// the label and prevent its click from firing. Touch-taps are fine because the
			// browser synthesizes click from touch location regardless of pointer capture.
			label.element.addEventListener('pointerdown', (e: PointerEvent) => {
				if (e.pointerType === 'touch') {
					rendererElement.dispatchEvent(new PointerEvent('pointerdown', e));
				}
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
			orbitLine,
			radiusScene: radius
		});
	}
}

export function buildOrbitLines(bodyObjects: Map<string, BodyObjects>, scene: Scene): void {
	for (const [, bo] of bodyObjects) {
		if (bo.orbitLine !== null) continue;
		const { body } = bo;
		if (!body.orbitElements || body.data.objectType === ObjectType.STAR) continue;
		const color = BODY_COLORS[body.data.id] ?? DEFAULT_BODY_COLOR;
		const line = makeOrbitLine(body, color);
		scene.add(line);
		bo.orbitLine = line;
	}
}

export function buildPointClouds(
	ctx: ContextManager,
	scene: Scene,
	circleTexture: CanvasTexture
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
		if (bodies.length > 0) {
			const pts = makePointCloud(bodies, circleTexture);
			asteroidPoints.set(zone, pts);
			scene.add(pts);
		}
	}

	// Spacecraft point clouds (one per parent body)
	for (const [groupParentId, bodies] of ctx.spacecraftByParent.entries()) {
		const points = makePointCloud(bodies, circleTexture);
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
		const pts = makePointCloud(moons, circleTexture);
		(pts.material as PointsMaterial).depthTest = true;
		pts.visible = false;
		moonPoints.set(parentId, pts);
		scene.add(pts);
	}

	return { asteroidPoints, spacecraftPoints, moonPoints };
}

/**
 * Rebuilds the asteroid and spacecraft point clouds from updated context data.
 */
export function rebuildMinorPointClouds(
	ctx: ContextManager,
	circleTexture: CanvasTexture,
	asteroidPoints: Map<string, Points>,
	spacecraftPoints: Map<string, Points>,
	scene: Scene
): void {
	// Asteroid clouds — per zone, reuse existing Points or create new ones
	for (const [zone, bodies] of ctx.asteroidBodiesByZone) {
		if (bodies.length === 0) continue;
		const posArr = new Float32Array(bodies.length * 3);
		for (let i = 0; i < bodies.length; i++) {
			posArr[i * 3] = bodies[i].position[0];
			posArr[i * 3 + 1] = bodies[i].position[1];
			posArr[i * 3 + 2] = bodies[i].position[2];
		}
		const existing = asteroidPoints.get(zone);
		if (existing) {
			existing.geometry.setAttribute('position', new Float32BufferAttribute(posArr, 3));
		} else {
			const pts = makePointCloud(bodies, circleTexture);
			asteroidPoints.set(zone, pts);
			scene.add(pts);
		}
	}

	// Spacecraft clouds — update existing groups, create new ones
	for (const [groupParentId, bodies] of ctx.spacecraftByParent.entries()) {
		const existing = spacecraftPoints.get(groupParentId);
		if (existing) {
			const posArr = new Float32Array(bodies.length * 3);
			for (let i = 0; i < bodies.length; i++) {
				posArr[i * 3] = bodies[i].position[0];
				posArr[i * 3 + 1] = bodies[i].position[1];
				posArr[i * 3 + 2] = bodies[i].position[2];
			}
			existing.geometry.setAttribute('position', new Float32BufferAttribute(posArr, 3));
		} else {
			const points = makePointCloud(bodies, circleTexture);
			spacecraftPoints.set(groupParentId, points);
			scene.add(points);
		}
	}
}

export async function loadBodyTexture(
	fileId: string,
	material: MeshStandardMaterial,
	textureLoader: TextureLoader
): Promise<void> {
	const detail = await fetchObjectDetail(fileId);
	if (!detail.global?.map_texture_available) return;
	const texture = await new Promise<Texture>((resolve, reject) => {
		textureLoader.load(`/data/v1/textures/${fileId}/low.webp`, resolve, undefined, reject);
	});
	material.map = texture;
	material.color.set(0xffffff);
	material.needsUpdate = true;
}

export { makeCircleTexture };
