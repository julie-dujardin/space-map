/**
 * The credit line every embed carries: spacemap first, then who the positions
 * and imagery on screen belong to. It follows the camera, since the sources
 * change with the system in view, and it cannot be turned off — the imagery
 * terms the data ships under require it.
 */

import { host } from '$lib/host';
import type { MapController } from '$lib/scene/map-controller.svelte';
import { attributionChips } from '$lib/scene/state/attribution';
import './attribution.css';

const HOME_URL = 'https://spacemap.co';
const CREDITS_URL = 'https://spacemap.co/credits';

function link(href: string, text: string, className?: string): HTMLAnchorElement {
	const a = document.createElement('a');
	a.href = href;
	a.target = '_blank';
	a.rel = 'noopener noreferrer';
	a.textContent = text;
	if (className) a.className = className;
	return a;
}

/** Adds the control to `container` and keeps it in step with the map.
 *  Returns the teardown. */
export function mountAttribution(map: MapController, container: HTMLElement): () => void {
	const bar = document.createElement('div');
	bar.className = 'sm-attribution';
	const home = link(HOME_URL, 'spacemap', 'sm-attribution__home');
	const orbits = document.createElement('span');
	orbits.className = 'sm-attribution__group';
	const imagery = document.createElement('span');
	imagery.className = 'sm-attribution__group';
	bar.append(home, orbits, imagery, link(CREDITS_URL, host().messages.credits_see_all()));
	container.append(bar);

	const fill = (el: HTMLElement, label: string, names: string[]): void => {
		el.hidden = names.length === 0;
		if (el.hidden) return;
		el.replaceChildren();
		const tag = document.createElement('span');
		tag.className = 'sm-attribution__label';
		tag.textContent = `${label}:`;
		el.append(tag, ` ${names.join(' · ')}`);
	};

	const stop = $effect.root(() => {
		$effect(() => {
			const chips = attributionChips(map.ctx);
			fill(orbits, host().messages.attribution_orbits(), chips.orbits);
			fill(imagery, host().messages.attribution_imagery(), chips.imagery);
		});
	});

	return () => {
		stop();
		bar.remove();
	};
}
