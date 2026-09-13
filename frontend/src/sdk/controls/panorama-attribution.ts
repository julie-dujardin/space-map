/**
 * The credit line a panorama carries: spacemap, then whose picture is on
 * screen, linked to the terms it is reused under. It follows the panorama
 * and cannot be turned off; the archives' terms require it.
 */

import { host } from '$lib/host';
import type { PanoramaView } from '$lib/panorama/view';
import { safeHttpUrl } from '$lib/safe-url';
import type { Control, ControlPosition } from '$lib/scene/controls';
import { bar, group, link, CREDITS_URL, HOME_URL } from './attribution-bar';
import './attribution.css';

export class PanoramaAttributionControl implements Control<PanoramaView> {
	private off: (() => void) | null = null;

	onAdd(view: PanoramaView): HTMLElement {
		const root = bar();
		const imagery = group();
		root.append(
			link(HOME_URL, 'spacemap', 'sm-attribution__home'),
			imagery,
			link(CREDITS_URL, host().messages.credits_see_all())
		);
		const fill = (): void => {
			const entry = view.getCurrent();
			imagery.hidden = !entry?.credit;
			if (!entry?.credit) return;
			const tag = document.createElement('span');
			tag.className = 'sm-attribution__label';
			tag.textContent = `${host().messages.attribution_imagery()}:`;
			const url = safeHttpUrl(entry.credit_url);
			const credit = url ? link(url, entry.credit) : entry.credit;
			imagery.replaceChildren(tag, ' ', credit);
		};
		fill();
		this.off = view.on('load', fill);
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
