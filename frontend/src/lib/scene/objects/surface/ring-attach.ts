/**
 * Build a body's ring annuli and wire the two shadow directions.
 *
 * Shared because ring bundles reach the renderer by two routes. The giants
 * get theirs from their system's metadata file, loaded for every body in the
 * system at once; the four ringed small bodies belong to no system, so theirs
 * ride their own global JSON and arrive when that body is focused. What
 * happens after the bundles are in hand is identical, and lives here.
 */
import type { Material, MeshStandardMaterial, Scene } from 'three';
import { kmToScene } from '$lib/math/units';
import type { BodyObjects } from '../../types';
import type { ContextManager } from '../../state/context-manager.svelte';
import { attachRingShadowToAtmosphere } from './atmosphere';
import { attachRingShadowToPlanet, loadRingNode, type RingMeta } from './rings';

/** SPICE/occultation triaxial semi-axes, km along body-fixed X, Y, Z. */
export interface BodyRadii {
	a: number;
	b: number;
	c: number;
}

export function attachRingBundles(
	bodyId: string,
	/** Barycentre for a system body, the body itself otherwise — credits only. */
	systemId: string,
	rings: RingMeta[],
	radii: BodyRadii | undefined,
	bo: BodyObjects,
	scene: Scene,
	maxTextureSize: number,
	ctx?: ContextManager
): Promise<void>[] {
	// Idempotent: a second call with `bo.rings` already populated is a no-op,
	// which is what makes re-entering a system (or re-focusing a body) free.
	if (!rings.length || bo.rings.length) return [];

	// Only the densest bundle casts a shadow worth ray-marching, and the
	// shader marches one annulus: Saturn's main rings reach τ~5 while its D
	// and E rings are τ~1e-3 and τ~5e-6, which would darken nothing.
	// intensity_scale is each bundle's peak physical opacity, so it ranks them
	// directly.
	const shadowCaster = rings.reduce((best, meta) =>
		meta.intensity_scale > best.intensity_scale ? meta : best
	);

	const promises: Promise<void>[] = [];
	for (const ringMeta of rings) {
		if (ctx) {
			// A bundle mixes works (Saturn: Björn Jónsson's photometry, NSSDCA's
			// vertical extents) — credit each for its own part.
			for (const src of ringMeta.sources) {
				ctx.credits.registerRing({
					bodyId,
					systemId,
					source: src.source,
					organisation: src.organisation,
					license: src.license,
					attribution: src.attribution,
					description: ringMeta.description
				});
			}
		}
		promises.push(
			loadRingNode(bodyId, ringMeta, maxTextureSize).then((node) => {
				if (!node) return;
				if (bo.rings.some((r) => r.mesh.userData.ringBundle === ringMeta.bundle)) {
					// A concurrent reload finished first — drop ours.
					node.mesh.geometry.dispose();
					(node.mesh.material as Material).dispose();
					return;
				}
				node.mesh.userData.ringBundle = ringMeta.bundle;
				bo.rings.push(node);
				scene.add(node.mesh);
				bo.extraObjects.push(node.mesh);
				// Analytical ring shadow on the body itself. The material is built
				// as a MeshStandardMaterial in `buildMajorBodies`; this swaps in an
				// onBeforeCompile that adds a ray-march to the ring plane after the
				// standard lighting calc.
				if (bo.mesh && ringMeta === shadowCaster) {
					node.planetShadow = attachRingShadowToPlanet(
						bo.mesh.material as MeshStandardMaterial,
						node.innerScene,
						node.outerScene,
						node.transparency,
						node.intensityScale
					);
					// The rings shade the scattering shell's air column too, sharing
					// the same per-frame uniform refs.
					if (bo.atmosphere) {
						attachRingShadowToAtmosphere(
							bo.atmosphere,
							node.planetShadow,
							node.transparency,
							node.innerScene,
							node.outerScene
						);
					}
				}
				// Reverse direction: configure the ring's own analytical body-shadow
				// with the body's oblate-spheroid extent. Saturn is essentially
				// biaxial (a ≈ b), so collapsing the two equatorial axes to their
				// mean is exact enough for the limb of the cast shadow. Haumea is
				// not, and its shadow limb is correspondingly approximate.
				if (radii) {
					node.planetShadowOnRing.uPlanetEquatorialScene.value = kmToScene((radii.a + radii.b) / 2);
					node.planetShadowOnRing.uPlanetPolarScene.value = kmToScene(radii.c);
				}
			})
		);
	}
	return promises;
}
