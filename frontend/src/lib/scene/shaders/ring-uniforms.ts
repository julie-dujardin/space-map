import { Vector3 } from 'three';
import type { Vec3 } from '$lib/scene/animation/math';
import type { BodyObjects } from '$lib/scene/types';
import { SUN_ID } from '$lib/constants';
import { sunIrradianceFactor } from '$lib/scene/lighting';
import { kmToScene } from '$lib/math/units';
import {
	RING_MIN_VISIBLE_ALPHA,
	RING_THICKNESS_LAYERS_MAX
} from '$lib/scene/objects/surface/rings';

// IAU nominal solar radius; over the ring-planet distance this gives the
// sun's angular radius, which sets the penumbra widths of both ring-shadow
// ray-marches.
const SUN_RADIUS_SCENE = kmToScene(695_700);

const SHEETS_PER_PX = 2;

const tmp = new Vector3();

/** How the nearest part of a ring annulus sits relative to the camera: `dist`
 *  in scene units, `sinToPole` = how edge-on the sheet stack reads onscreen.
 *  Measured from the annulus's closest point, not its centre — from just
 *  above Saturn's B ring the centre is face-on but the material underfoot is edge-on. */
function annulusView(
	camPos: Vector3,
	center: Vector3,
	poleDir: Vector3,
	innerScene: number,
	outerScene: number
): { dist: number; sinToPole: number } {
	tmp.subVectors(camPos, center);
	const axial = tmp.dot(poleDir);
	// Radial distance in the ring plane, after removing the out-of-plane part.
	const radial = Math.sqrt(Math.max(tmp.lengthSq() - axial * axial, 0));
	const clamped = Math.min(Math.max(radial, innerScene), outerScene);
	// Camera → closest point, split into its in-plane and along-pole legs.
	const gap = radial - clamped;
	const dist = Math.sqrt(gap * gap + axial * axial);
	return { dist, sinToPole: dist > 0 ? Math.abs(gap) / dist : 1 };
}

/**
 * Refresh per-frame ring + planet-ring-shadow uniforms for every bundle of
 * every ringed body. `realistic` scales pre-lit albedo by inverse-square solar
 * distance (scene lights never touch the ring ShaderMaterial). `overexpose`
 * renders peak-normalised channel values unscaled, lifting faint systems to
 * full visibility. `pxPerRad` drives the sheet-stack LOD.
 */
export function updateRingShaders(
	bodyObjects: Map<string, BodyObjects>,
	focusTruePos: Vec3,
	realistic: boolean,
	overexpose: boolean,
	camPos: Vector3,
	pxPerRad: number
): void {
	const sunPos = bodyObjects.get(SUN_ID)?.body.position;
	if (!sunPos) return;
	const [fx, fy, fz] = focusTruePos;
	for (const bo of bodyObjects.values()) {
		if (!bo.rings.length) continue;
		const [bx, by, bz] = bo.body.position;

		for (const ring of bo.rings) {
			// Bundles whose peak opacity can't reach a displayable value are
			// skipped rather than drawn into nothing — they still cost a
			// full-screen fill and a shadow march. Zeroing the intensity (not
			// just hiding the mesh) also short-circuits the ring-shadow
			// marches in the planet and atmosphere shaders.
			const visible = overexpose || ring.intensityScale >= RING_MIN_VISIBLE_ALPHA;
			ring.mesh.visible = visible;
			const intensity = overexpose ? 1 : visible ? ring.intensityScale : 0;
			ring.material.uniforms.uIntensityScale.value = intensity;

			// Body → sun direction (the focus offset cancels, so world == scene-rel).
			const ringSunDir = ring.material.uniforms.uSunDir.value as Vector3;
			ringSunDir.set(sunPos[0] - bx, sunPos[1] - by, sunPos[2] - bz);
			const sunDist = ringSunDir.length();
			const sunAngularRadius = SUN_RADIUS_SCENE / sunDist;
			ring.material.uniforms.uSunAngularRadius.value = sunAngularRadius;
			ring.material.uniforms.uLightScale.value = realistic ? sunIrradianceFactor(sunDist) : 1;
			ringSunDir.normalize();

			// Shared by both ray-marches: planet-shadow-on-ring (always present)
			// and ring-shadow-on-planet (present once attachRingShadowToPlanet runs).
			const psOnRing = ring.planetShadowOnRing;
			psOnRing.uPlanetCenter.value.set(bx - fx, by - fy, bz - fz);
			if (bo.mesh) {
				psOnRing.uPlanetPoleDir.value.set(0, 1, 0).applyQuaternion(bo.mesh.quaternion);
			}

			// One sheet per pixel the stack spreads across the screen. Seen
			// face-on the sheets project onto each other and one draws the
			// same picture; seen edge-on they need to be a pixel apart or
			// they read as separate lines instead of a filled band. Opacity
			// is re-split to match, so the composite is unchanged either way.
			if (ring.layers) {
				const { dist, sinToPole } = annulusView(
					camPos,
					psOnRing.uPlanetCenter.value,
					psOnRing.uPlanetPoleDir.value,
					ring.innerScene,
					ring.outerScene
				);
				const spreadPx = ((ring.thicknessScene * sinToPole) / Math.max(dist, 1e-9)) * pxPerRad;
				// Two sheets per pixel of spread: at one they alias against the
				// pixel grid and the band reads as stripes again.
				const count = Math.min(
					Math.max(Math.ceil(spreadPx * SHEETS_PER_PX), 1),
					RING_THICKNESS_LAYERS_MAX
				);
				if (ring.layers.count !== count) {
					ring.layers.count = count;
					ring.material.uniforms.uLayerCount.value = count;
					ring.material.uniforms.uLayerAlphaExp.value = 1 / count;
				}
			}

			const ps = ring.planetShadow;
			if (!ps) continue;
			// Shared refs with the atmosphere shell's ring-shadow uniforms.
			ps.uRingShadowIntensity.value = intensity;
			ps.uRingShadowSunAngularRadius.value = sunAngularRadius;
			ps.uRingShadowSunDir.value.copy(ringSunDir);
			ps.uRingShadowPoleDir.value.copy(psOnRing.uPlanetPoleDir.value);
			ps.uRingShadowCenter.value.copy(psOnRing.uPlanetCenter.value);
		}
	}
}
