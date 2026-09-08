/**
 * Where the projected world sits in a box of pixels. A viewport is an
 * immutable reading of a projection at one size, zoom and centre — moving the
 * map builds another one, which costs nothing, so nothing downstream has to
 * watch a mutable transform.
 */

import type { Extent, Projection } from './projection';

export interface ViewState {
	/** 1 fits the whole world in the frame; 2 shows half of it. */
	zoom: number;
	/** Point of the plane the frame is centred on. */
	centerX: number;
	centerY: number;
}

export const DEFAULT_VIEW: ViewState = { zoom: 1, centerX: 0, centerY: 0 };

/** Plane point a screen pixel would fall on, and back again. */
export class Viewport {
	readonly projection: Projection;
	readonly width: number;
	readonly height: number;
	readonly view: ViewState;
	/** Pixels per unit of the projection's plane. */
	readonly scale: number;

	constructor(projection: Projection, width: number, height: number, view: ViewState) {
		this.projection = projection;
		this.width = width;
		this.height = height;
		this.view = view;
		const { minX, maxX, minY, maxY } = projection.extent;
		// Contain: the whole world is visible at zoom 1 whatever the frame's shape.
		const fit = Math.min(width / (maxX - minX), height / (maxY - minY));
		this.scale = fit * view.zoom;
	}

	toScreen(x: number, y: number): [number, number] {
		return [
			this.width / 2 + (x - this.view.centerX) * this.scale,
			// The plane's north is up, so the pixel axis runs the other way.
			this.height / 2 - (y - this.view.centerY) * this.scale
		];
	}

	fromScreen(px: number, py: number): [number, number] {
		return [
			this.view.centerX + (px - this.width / 2) / this.scale,
			this.view.centerY - (py - this.height / 2) / this.scale
		];
	}

	/** Screen pixel for a place, or null where it is not on the map. */
	project(lon: number, lat: number): [number, number] | null {
		const plane = this.projection.forward(lon, lat);
		return plane ? this.toScreen(plane[0], plane[1]) : null;
	}

	/** Place under a screen pixel, or null where the pixel is off the world. */
	unproject(px: number, py: number): [number, number] | null {
		const [x, y] = this.fromScreen(px, py);
		return this.projection.inverse(x, y);
	}

	/** How wide the whole world is in pixels — the distance a cyclic map repeats
	 *  over, which is what tells a drawn line it has crossed the seam. */
	get worldWidthPx(): number {
		const { minX, maxX } = this.projection.extent;
		return (maxX - minX) * this.scale;
	}

	/** Whether a cyclic map should be drawn again either side of itself. It
	 *  should wherever that only ever fills a gap — which is while one copy of
	 *  the world is still at least as wide as the frame. Once the frame is the
	 *  wider of the two, a copy set beside the first would stand apart from it
	 *  and read as a second world rather than the same one carrying on. */
	get repeatsHorizontally(): boolean {
		return this.projection.cyclic && coversFrame(this.worldWidthPx, this.width);
	}
}

/** Whether one copy of the world still spans the frame it is drawn in. Both
 *  the wrap-around and the copies either side of it turn on this, and they
 *  have to agree: panning a map that cannot be repeated only slides it off. */
function coversFrame(worldWidthPx: number, width: number): boolean {
	return worldWidthPx >= width - 0.5;
}

/**
 * A view held inside what there is to look at: never zoomed out past the whole
 * world, and never panned so far that the frame runs off the map. A cyclic
 * projection wraps east–west instead of stopping, the way a world map should.
 */
export function clampView(
	view: ViewState,
	projection: Projection,
	width: number,
	height: number,
	maxZoom: number
): ViewState {
	const zoom = Math.min(Math.max(view.zoom, 1), maxZoom);
	const extent: Extent = projection.extent;
	const worldW = extent.maxX - extent.minX;
	const worldH = extent.maxY - extent.minY;
	const fit = Math.min(width / worldW, height / worldH);
	const scale = fit * zoom;
	// Half the frame in plane units: how far the centre may sit from an edge
	// before the map stops covering the frame.
	const halfW = width / 2 / scale;
	const halfH = height / 2 / scale;
	const midX = (extent.minX + extent.maxX) / 2;
	const midY = (extent.minY + extent.maxY) / 2;

	const axis = (v: number, mid: number, half: number, world: number) => {
		// Zoomed out far enough that the world no longer fills the frame: pin it
		// to the middle rather than let it drift into a corner.
		if (half >= world / 2) return mid;
		return Math.min(mid + world / 2 - half, Math.max(mid - world / 2 + half, v));
	};

	const centerX =
		projection.cyclic && coversFrame(worldW * scale, width)
			? // Wrapped, not clamped: panning east past the seam comes round again.
				((((view.centerX - extent.minX) % worldW) + worldW) % worldW) + extent.minX
			: axis(view.centerX, midX, halfW, worldW);
	return { zoom, centerX, centerY: axis(view.centerY, midY, halfH, worldH) };
}
