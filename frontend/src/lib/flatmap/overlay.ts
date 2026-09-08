/**
 * What a host draws on the flat map. Shapes are given in longitude and
 * latitude and kept that way: the map holds the geometry, not the pixels, so a
 * track drawn once is redrawn correctly when the projection changes, the view
 * moves, or the frame is resized.
 *
 * Lines and areas are SVG, which is what makes them crisp at any zoom and
 * clickable without hit-testing arithmetic. Markers are the host's own
 * elements, placed over the map and left otherwise alone.
 */

import { boxRing, pathFor, smallCircle, type Interpolation, type LonLat } from './geometry';
import { SVG_NS } from './layers';
import type { Viewport } from './view';

export interface ShapeStyle {
	/** Stroke colour: any CSS colour. White when left out. */
	color?: string;
	/** Stroke width in screen pixels, held at every zoom. */
	widthPx?: number;
	/** 0 to 1, over the whole shape. */
	opacity?: number;
	/** Fill colour for an area. Unfilled when left out. */
	fill?: string;
	fillOpacity?: number;
	/** SVG dash pattern, e.g. `"4 3"`. */
	dash?: string;
	/** Added to the element, for styling from the host's own stylesheet. */
	className?: string;
	/** Take pointer events. Off by default, so drawings never get in the way of
	 *  panning the map under them. */
	interactive?: boolean;
	onclick?: (event: PointerEvent) => void;
	onpointerenter?: (event: PointerEvent) => void;
	onpointerleave?: (event: PointerEvent) => void;
	/** Names the shape for a screen reader, which also makes it focusable. */
	ariaLabel?: string;
}

export interface PolylineOptions extends ShapeStyle {
	points: readonly LonLat[];
	/** How the space between the given points is filled: along the parallels
	 *  and meridians, or the short way over the sphere. */
	interpolate?: Interpolation;
	/** Join the last point back to the first. */
	closed?: boolean;
}

export interface PolygonOptions extends Omit<PolylineOptions, 'closed'> {
	points: readonly LonLat[];
}

export interface BoxOptions extends ShapeStyle {
	latMin: number;
	latMax: number;
	lonMin: number;
	/** Degrees of longitude the box covers, east from `lonMin`. */
	lonSpan: number;
}

export interface CircleOptions extends ShapeStyle {
	center: LonLat;
	/** Radius as an angle at the body's centre. */
	radiusDeg?: number;
	/** Radius along the surface. Needs the body's radius to be known — see
	 *  `FlatMap.bodyRadiusKm`; ignored when it is not. */
	radiusKm?: number;
}

/** A drawing on the map, for as long as the host keeps it. */
export interface FlatShape {
	/** The element itself, for a host that wants to style or animate it. */
	readonly node: SVGPathElement;
	/** Replace the geometry, keeping the styling. */
	setPoints(points: readonly LonLat[]): void;
	setVisible(visible: boolean): void;
	remove(): void;
}

export interface MarkerOptions {
	at: LonLat;
	/** The host's element, placed over the map as it is. A plain dot when left
	 *  out. */
	element?: HTMLElement;
	/** Which point of the element sits on the place, 0 to 1 in its own box.
	 *  Its centre by default. */
	align?: readonly [number, number];
	className?: string;
	/** Take pointer events. Off by default, as for a shape: the map is dragged
	 *  through the marker layer unless a marker opts back in. */
	interactive?: boolean;
}

export interface FlatMarker {
	readonly element: HTMLElement;
	setPosition(at: LonLat): void;
	setVisible(visible: boolean): void;
	remove(): void;
}

/** Anything the overlay redraws when the view changes. */
interface Drawing {
	redraw(viewport: Viewport): void;
	detach(): void;
}

function applyStyle(node: SVGPathElement, style: ShapeStyle): void {
	node.setAttribute('fill', style.fill ?? 'none');
	if (style.fill && style.fillOpacity !== undefined) {
		node.setAttribute('fill-opacity', String(style.fillOpacity));
	}
	node.setAttribute('stroke', style.color ?? '#ffffff');
	node.setAttribute('stroke-width', String(style.widthPx ?? 2));
	node.setAttribute('stroke-linejoin', 'round');
	node.setAttribute('stroke-linecap', 'round');
	if (style.opacity !== undefined) node.setAttribute('opacity', String(style.opacity));
	if (style.dash) node.setAttribute('stroke-dasharray', style.dash);
	if (style.className) node.setAttribute('class', style.className);
	// Pointer events off by default: a drawing should not stop the map being
	// dragged through it.
	node.style.pointerEvents = style.interactive ? 'auto' : 'none';
	if (style.ariaLabel) {
		node.setAttribute('role', 'img');
		node.setAttribute('aria-label', style.ariaLabel);
	}
}

function bindEvents(node: SVGElement, style: ShapeStyle): void {
	if (style.onclick) node.addEventListener('click', style.onclick as EventListener);
	if (style.onpointerenter) {
		node.addEventListener('pointerenter', style.onpointerenter as EventListener);
	}
	if (style.onpointerleave) {
		node.addEventListener('pointerleave', style.onpointerleave as EventListener);
	}
}

class PathDrawing implements Drawing, FlatShape {
	readonly node: SVGPathElement;
	private points: readonly LonLat[];
	private visible = true;

	constructor(
		points: readonly LonLat[],
		style: ShapeStyle,
		private readonly closed: boolean,
		private readonly interpolate: Interpolation,
		private readonly onRemove: (drawing: Drawing) => void,
		private readonly onChange: () => void
	) {
		this.points = points;
		this.node = document.createElementNS(SVG_NS, 'path');
		applyStyle(this.node, style);
		bindEvents(this.node, style);
	}

	redraw(viewport: Viewport): void {
		if (!this.visible) return;
		this.node.setAttribute(
			'd',
			pathFor(this.points, viewport, { closed: this.closed, interpolate: this.interpolate })
		);
	}

	setPoints(points: readonly LonLat[]): void {
		this.points = points;
		this.onChange();
	}

	setVisible(visible: boolean): void {
		this.visible = visible;
		this.node.style.display = visible ? '' : 'none';
		this.onChange();
	}

	detach(): void {
		this.node.remove();
	}

	remove(): void {
		this.onRemove(this);
	}
}

class MarkerDrawing implements Drawing, FlatMarker {
	readonly element: HTMLElement;
	private at: LonLat;
	private visible = true;
	private readonly align: readonly [number, number];

	constructor(
		options: MarkerOptions,
		private readonly onRemove: (drawing: Drawing) => void,
		private readonly onChange: () => void
	) {
		this.at = options.at;
		this.align = options.align ?? [0.5, 0.5];
		this.element = options.element ?? document.createElement('div');
		if (!options.element) this.element.className = 'sm-flat__marker-dot';
		if (options.className) this.element.classList.add(options.className);
		this.element.style.position = 'absolute';
		this.element.style.left = '0';
		this.element.style.top = '0';
		// The marker layer takes no pointer events, so the element has to opt in
		// for its own listeners to ever fire.
		this.element.style.pointerEvents = options.interactive ? 'auto' : 'none';
	}

	redraw(viewport: Viewport): void {
		const screen = this.visible ? viewport.project(this.at.lon, this.at.lat) : null;
		// A place on the far side of a globe has nowhere to be.
		this.element.style.display = screen ? '' : 'none';
		if (!screen) return;
		this.element.style.transform =
			`translate(${screen[0]}px, ${screen[1]}px) ` +
			`translate(${-this.align[0] * 100}%, ${-this.align[1] * 100}%)`;
	}

	setPosition(at: LonLat): void {
		this.at = at;
		this.onChange();
	}

	setVisible(visible: boolean): void {
		this.visible = visible;
		this.onChange();
	}

	detach(): void {
		this.element.remove();
	}

	remove(): void {
		this.onRemove(this);
	}
}

/**
 * The host's drawings, in one SVG group and one element layer. Redrawn as a
 * set whenever the map moves — every shape is geometry until then.
 */
export class Overlay {
	private readonly drawings = new Set<Drawing>();

	constructor(
		private readonly shapes: SVGGElement,
		private readonly markers: HTMLElement,
		/** Asks for a redraw: a drawing changed after the map last painted, and
		 *  nothing else would bring it back round. */
		private readonly onChange: () => void = () => {},
		/** The body's radius, so a circle can be given in kilometres. */
		private radiusKm: number | null = null
	) {}

	setBodyRadiusKm(radiusKm: number | null): void {
		this.radiusKm = radiusKm;
	}

	private track<T extends Drawing>(drawing: T, node: Element | HTMLElement): T {
		this.drawings.add(drawing);
		if (node instanceof HTMLElement) this.markers.append(node);
		else this.shapes.append(node);
		return drawing;
	}

	private readonly drop = (drawing: Drawing): void => {
		if (!this.drawings.delete(drawing)) return;
		drawing.detach();
	};

	addPolyline(options: PolylineOptions): FlatShape {
		const shape = new PathDrawing(
			options.points,
			options,
			options.closed ?? false,
			options.interpolate ?? 'linear',
			this.drop,
			this.onChange
		);
		return this.track(shape, shape.node);
	}

	addPolygon(options: PolygonOptions): FlatShape {
		const shape = new PathDrawing(
			options.points,
			{ fill: 'rgb(255 255 255 / 25%)', ...options },
			true,
			options.interpolate ?? 'linear',
			this.drop,
			this.onChange
		);
		return this.track(shape, shape.node);
	}

	/** A longitude and latitude box — a chart sheet, a coverage footprint, an
	 *  area of interest. Its edges follow the parallels, so it bends with the
	 *  projection instead of staying a rectangle. */
	addBox(options: BoxOptions): FlatShape {
		const shape = new PathDrawing(
			boxRing(options.latMin, options.latMax, options.lonMin, options.lonSpan),
			{ fill: 'rgb(255 255 255 / 15%)', ...options },
			true,
			'linear',
			this.drop,
			this.onChange
		);
		return this.track(shape, shape.node);
	}

	/** A circle on the globe, which is a circle on the map only by accident. */
	addCircle(options: CircleOptions): FlatShape {
		const radiusDeg = this.circleRadiusDeg(options);
		const shape = new PathDrawing(
			smallCircle(options.center, radiusDeg),
			{ fill: 'rgb(255 255 255 / 20%)', ...options },
			true,
			'linear',
			this.drop,
			this.onChange
		);
		return this.track(shape, shape.node);
	}

	private circleRadiusDeg(options: CircleOptions): number {
		if (options.radiusDeg !== undefined) return options.radiusDeg;
		if (options.radiusKm !== undefined && this.radiusKm) {
			return (options.radiusKm / this.radiusKm) * (180 / Math.PI);
		}
		return 1;
	}

	addMarker(options: MarkerOptions): FlatMarker {
		const marker = new MarkerDrawing(options, this.drop, this.onChange);
		return this.track(marker, marker.element);
	}

	redraw(viewport: Viewport): void {
		for (const drawing of this.drawings) drawing.redraw(viewport);
	}

	clear(): void {
		for (const drawing of this.drawings) drawing.detach();
		this.drawings.clear();
	}
}
