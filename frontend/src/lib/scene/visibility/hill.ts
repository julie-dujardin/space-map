import type { BodyData } from '$lib/types/objects';
import { AU_KM } from '$lib/math/units';
import { getGmKm3s2 } from '$lib/fetch/systems-global';
import { GM_SUN_KM3_S2 } from '$lib/math/travel/constants';
import { isTopLevelParent } from '$lib/scene/state/bodies.svelte';

/** Hill radius (AU) of a system root about the Sun, from its heliocentric
 *  orbit. A barycenter root (`naif-N`) borrows its planet's GM (`N99`). */
export function hillRadiusAU(root: BodyData): number | undefined {
	if (!isTopLevelParent(root.parentId)) return undefined;
	const naif = Number(root.id.replace(/^naif-/, ''));
	if (!Number.isFinite(naif)) return undefined;
	const mu = getGmKm3s2(naif >= 1 && naif <= 9 ? naif * 100 + 99 : naif);
	const aKm = root.a * AU_KM;
	if (!mu || !(mu > 0) || !(aKm > 0)) return undefined;
	const e = Number.isFinite(root.e) ? Math.min(Math.max(root.e, 0), 0.99) : 0;
	return (aKm * (1 - e) * Math.cbrt(mu / (3 * GM_SUN_KM3_S2))) / AU_KM;
}
