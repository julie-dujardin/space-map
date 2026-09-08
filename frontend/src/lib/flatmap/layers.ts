/**
 * What the flat map is made of. A layer is either a picture wrapped round the
 * body — the surface, the clouds over it, the lights on its night side — or a
 * set of lines drawn from coordinates, like the graticule and the named
 * features. Both kinds are listed and switched the same way, which is what
 * lets a host offer them as a row of checkboxes without knowing which is
 * which.
 */

import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
import { graticule, pathFor, worldOutline } from './geometry';
import type { BundleMeta } from './sources';
import type { Viewport } from './view';

export const SVG_NS = 'http://www.w3.org/2000/svg';

/** Who a layer's imagery belongs to. Carried up to the credit line, which the
 *  data's terms require an embed to show. */
export interface LayerCredit {
	organisation: string;
	source: string;
	attribution?: string;
}

/** A layer as a host sees it. */
export interface LayerInfo {
	id: string;
	label: string;
	kind: 'raster' | 'vector';
	visible: boolean;
	credit?: LayerCredit;
}

export interface RasterLayer {
	readonly kind: 'raster';
	id: string;
	label: string;
	visible: boolean;
	opacity: number;
	blend: 'normal' | 'add';
	credit?: LayerCredit;
	/** The picture to draw for a moment in time, at a resolution tier. Bundles
	 *  that do not change with either ignore both. */
	url(jd: number, tier: string): string;
	/** Tiers the bundle was actually written at. */
	tiers: readonly string[];
}

export interface VectorLayer {
	readonly kind: 'vector';
	id: string;
	label: string;
	visible: boolean;
	credit?: LayerCredit;
	/** Fill `group` with what this layer looks like in this view. The group is
	 *  emptied first, so a layer only ever adds. */
	render(viewport: Viewport, group: SVGGElement): void;
	/** Loading anything it needs. Re-rendered when it resolves. */
	prepare?(): Promise<void>;
	dispose?(): void;
}

export type Layer = RasterLayer | VectorLayer;

export function layerInfo(layer: Layer): LayerInfo {
	return {
		id: layer.id,
		label: layer.label,
		kind: layer.kind,
		visible: layer.visible,
		credit: layer.credit
	};
}

export function creditOf(bundle: BundleMeta): LayerCredit {
	return {
		organisation: bundle.organisation,
		source: bundle.source,
		attribution: bundle.attribution
	};
}

function pathElement(d: string, className: string): SVGPathElement {
	const path = document.createElementNS(SVG_NS, 'path');
	path.setAttribute('d', d);
	path.setAttribute('class', className);
	return path;
}

/** Meridians and parallels. Nothing else shows what a projection is doing to
 *  the world, so it is the one layer that earns its place on every body. */
export function graticuleLayer(label: string, stepDeg = 30): VectorLayer {
	return {
		kind: 'vector',
		id: 'graticule',
		label,
		visible: false,
		render(viewport, group) {
			for (const line of graticule(stepDeg)) {
				const d = pathFor(line, viewport, { stepDeg: 2 });
				if (d) group.append(pathElement(d, 'sm-flat__graticule'));
			}
			// The edge of the world: the limb on a globe, and on a flat map the
			// outline the projection actually fills, which is only a rectangle for
			// some of them.
			if (viewport.projection.azimuthal) {
				const centre = viewport.toScreen(0, 0);
				const edge = viewport.toScreen(viewport.projection.extent.maxX, 0);
				const circle = document.createElementNS(SVG_NS, 'circle');
				circle.setAttribute('cx', String(centre[0]));
				circle.setAttribute('cy', String(centre[1]));
				circle.setAttribute('r', String(Math.abs(edge[0] - centre[0])));
				circle.setAttribute('class', 'sm-flat__frame');
				group.append(circle);
			} else {
				const d = worldOutline(viewport);
				if (d) group.append(pathElement(d, 'sm-flat__frame'));
			}
		}
	};
}

/** How many named features to draw at once. The Moon has thousands; past a
 *  screenful the map is illegible and the labels are all overlapping anyway. */
const NOMENCLATURE_LIMIT = 120;

/** The IAU's names for what is on the surface — craters, maria, valleys —
 *  drawn largest first, so a zoomed-out map carries the ones worth reading. */
export function nomenclatureLayer(bodyId: string, label: string): VectorLayer {
	let features: { lon: number; lat: number; name: string; diameterM: number }[] = [];
	return {
		kind: 'vector',
		id: 'nomenclature',
		label,
		visible: false,
		credit: {
			organisation: 'IAU',
			source: 'https://planetarynames.wr.usgs.gov/'
		},
		async prepare() {
			if (features.length) return;
			const all = await fetchBodyNomenclature(bodyId);
			features = [...all].sort((a, b) => b.diameterM - a.diameterM).slice(0, NOMENCLATURE_LIMIT);
		},
		render(viewport, group) {
			for (const feature of features) {
				const at = viewport.project(feature.lon, feature.lat);
				if (!at) continue;
				if (at[0] < 0 || at[1] < 0 || at[0] > viewport.width || at[1] > viewport.height) continue;
				const dot = document.createElementNS(SVG_NS, 'circle');
				dot.setAttribute('cx', at[0].toFixed(1));
				dot.setAttribute('cy', at[1].toFixed(1));
				dot.setAttribute('r', '1.6');
				dot.setAttribute('class', 'sm-flat__feature-dot');
				const text = document.createElementNS(SVG_NS, 'text');
				text.setAttribute('x', (at[0] + 4).toFixed(1));
				text.setAttribute('y', (at[1] + 3).toFixed(1));
				text.setAttribute('class', 'sm-flat__feature-label');
				text.textContent = feature.name;
				group.append(dot, text);
			}
		}
	};
}
