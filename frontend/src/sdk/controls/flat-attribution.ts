/**
 * The credit line a flat map carries. Same bar as the scene's, but driven by
 * which layers are switched on rather than by where the camera is — turning
 * the clouds off takes EUMETSAT off the line with them.
 */

import type { FlatMap } from '$lib/flatmap/flat-map';
import { host } from '$lib/host';
import type { Control, ControlPosition } from '$lib/scene/controls';
import { bar, group, link, CREDITS_URL, HOME_URL } from './attribution-bar';
import './attribution.css';

export class FlatAttributionControl implements Control<FlatMap> {
	private off: (() => void) | null = null;

	onAdd(map: FlatMap): HTMLElement {
		const root = bar();
		const imagery = group();
		root.append(
			link(HOME_URL, 'spacemap', 'sm-attribution__home'),
			imagery,
			link(CREDITS_URL, host().messages.credits_see_all())
		);
		const fill = (): void => {
			const names = [...new Set(map.credits.map((credit) => credit.organisation))].filter(Boolean);
			imagery.hidden = names.length === 0;
			if (imagery.hidden) return;
			const tag = document.createElement('span');
			tag.className = 'sm-attribution__label';
			tag.textContent = `${host().messages.attribution_imagery()}:`;
			imagery.replaceChildren(tag, ` ${names.join(' · ')}`);
		};
		fill();
		this.off = map.on('layerschange', fill);
		return root;
	}

	onRemove(): void {
		this.off?.();
		this.off = null;
	}

	getDefaultPosition(): ControlPosition {
		return 'bottom-right';
	}
}
