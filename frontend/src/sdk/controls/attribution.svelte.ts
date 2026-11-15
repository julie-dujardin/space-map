/**
 * The credit line every embed carries: spacemap first, then who the positions
 * and imagery on screen belong to. It follows the camera, since the sources
 * change with the system in view, and it cannot be turned off — the imagery
 * terms the data ships under require it.
 */

import { host } from '$lib/host';
import type { Control, ControlPosition } from '$lib/scene/controls';
import type { SpaceMap } from '$lib/scene/space-map.svelte';
import { attributionChips } from '$lib/scene/state/attribution';
import { bar, fillGroup, group, link, CREDITS_URL, HOME_URL } from './attribution-bar';
import './attribution.css';

export class AttributionControl implements Control<SpaceMap> {
	private stop: (() => void) | null = null;

	onAdd(map: SpaceMap): HTMLElement {
		const root = bar();
		const orbits = group();
		const imagery = group();
		const stars = group();
		const constellations = group();
		const galaxy = group();
		root.append(
			link(HOME_URL, 'spacemap', 'sm-attribution__home'),
			orbits,
			imagery,
			constellations,
			galaxy,
			stars,
			link(CREDITS_URL, host().messages.credits_see_all())
		);
		this.stop = $effect.root(() => {
			$effect(() => {
				const chips = attributionChips(map.ctx);
				fillGroup(orbits, host().messages.attribution_orbits(), chips.orbits);
				fillGroup(imagery, host().messages.attribution_imagery(), chips.imagery);
				fillGroup(
					constellations,
					host().messages.attribution_constellations(),
					chips.constellations
				);
				const model = chips.galaxyModel ? [host().messages.attribution_galaxy_model()] : [];
				fillGroup(galaxy, host().messages.attribution_galaxy(), model);
				fillGroup(stars, host().messages.attribution_stars(), chips.stars);
			});
		});
		return root;
	}

	onRemove(): void {
		this.stop?.();
		this.stop = null;
	}

	getDefaultPosition(): ControlPosition {
		return 'bottom-right';
	}
}
