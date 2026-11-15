/**
 * The credit line a star chart carries: spacemap, the star map behind it while
 * it is painted, then the figure's culture and the catalogues that place and
 * name its stars. It cannot be turned off; the terms of those works require it.
 */

import { host } from '$lib/host';
import type { Control, ControlPosition } from '$lib/scene/controls';
import type { StarChart, StarChartCredit } from '$lib/star-chart/star-chart';
import { bar, fillGroup, group, link, CREDITS_URL, HOME_URL } from './attribution-bar';
import './attribution.css';

/** The credit line of a star chart. Every chart has one. */
export class StarChartAttributionControl implements Control<StarChart> {
	private off: (() => void) | null = null;

	onAdd(chart: StarChart): HTMLElement {
		const root = bar();
		root.classList.add('sm-attribution--wrap');
		const sky = group();
		const figures = group();
		root.append(
			link(HOME_URL, 'spacemap', 'sm-attribution__home'),
			sky,
			figures,
			link(CREDITS_URL, host().messages.credits_see_all())
		);
		const names = (section: StarChartCredit['section']): string[] =>
			chart.credits.filter((credit) => credit.section === section).map((c) => c.organisation);
		const fill = (): void => {
			fillGroup(sky, host().messages.attribution_section_skybox(), names('sky'));
			fillGroup(figures, host().messages.attribution_constellations(), names('constellations'));
		};
		fill();
		this.off = chart.on('overlay', fill);
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
