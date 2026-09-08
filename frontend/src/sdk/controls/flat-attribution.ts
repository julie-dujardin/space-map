/**
 * The credit line a flat map carries. Same bar as the scene's, but driven by
 * which layers are switched on rather than by where the camera is — turning
 * the clouds off takes EUMETSAT off the line with them.
 */

import { host } from '$lib/host';
import type { FlatMap } from '$lib/flatmap/flat-map';
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

/** Adds the control to `container` and keeps it in step with the layers.
 *  Returns the teardown. */
export function mountFlatAttribution(map: FlatMap, container: HTMLElement): () => void {
	const bar = document.createElement('div');
	bar.className = 'sm-attribution';
	const imagery = document.createElement('span');
	imagery.className = 'sm-attribution__group';
	bar.append(
		link(HOME_URL, 'spacemap', 'sm-attribution__home'),
		imagery,
		link(CREDITS_URL, host().messages.credits_see_all())
	);
	container.append(bar);

	const fill = () => {
		const names = [...new Set(map.credits.map((credit) => credit.organisation))].filter(Boolean);
		imagery.hidden = names.length === 0;
		if (imagery.hidden) return;
		const tag = document.createElement('span');
		tag.className = 'sm-attribution__label';
		tag.textContent = `${host().messages.attribution_imagery()}:`;
		imagery.replaceChildren(tag, ` ${names.join(' · ')}`);
	};

	fill();
	const off = map.on('layerschange', fill);
	return () => {
		off();
		bar.remove();
	};
}
