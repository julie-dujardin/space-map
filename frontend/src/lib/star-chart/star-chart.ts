/**
 * The star chart of the SDK: one figure of a sky culture drawn into a
 * container, with the sky behind it, its lines, and the names of its stars.
 * It needs no Solar System map. The drawer's chart draws from the same core.
 *
 * It is a canvas under an SVG under a layer of names. The canvas holds the
 * painted sky, the SVG the lines and rings, and each name is a button. One
 * frame places all three.
 */

import { fetchFigureChart, type LoadedChart } from '$lib/fetch/extrasolar/figures';
import { fetchMetadata } from '$lib/fetch/metadata';
import { RetryBackoff } from '$lib/fetch/retry-backoff';
import { host } from '$lib/host';
import { holdChartSky } from '$lib/scene/objects/sky/chart-sky';
import { ControlHost, type Control, type ControlPosition } from '$lib/scene/controls';
import type { SpaceMap } from '$lib/scene/space-map.svelte';
import { constellationCreditName } from '$lib/scene/state/attribution';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { project, type ChartFrame } from './frame';
import type { LabelBox } from './labels';
import {
	chartPoints,
	chooseFrame,
	FILL_LABEL_MAX,
	LABEL_MAX,
	LABEL_MIN_PX,
	layoutNames,
	linePath,
	nameWidth,
	noNames,
	rememberNames,
	STAND_IN_RING_PX,
	type ChartNames,
	type ChartPoints,
	type MeasuredStar,
	type PlacedName
} from './overlay';
import { ChartPainter } from './painter';
import type { ChartSky } from './sky';
import './star-chart.css';

/** `fit`: as wide as the container, as tall as the figure's own shape. `fill`:
 *  the container's whole box, with the sky around the figure. */
export type StarChartFraming = 'fit' | 'fill';

/** What a chart draws, and how. */
export interface StarChartOptions {
	/** The sky culture, as the map's `constellationselect` event names it:
	 *  `"culture-modern_iau"` for the IAU's constellations. */
	slug: string;
	/** The figure in that culture, as the same event names it: `"Ori"`. */
	figure: string;
	/** `fit` when left out. */
	framing?: StarChartFraming;
	/** Draw the names of the stars. The overlay holds them either way. */
	names?: boolean;
	/** Name the bright stars around the figure too. */
	neighbours?: boolean;
	/** Paint the sky. False draws the lines and rings alone and downloads no sky. */
	sky?: boolean;
	/** A Solar System map on the page. The chart reads its sky, so the star map
	 *  is not downloaded twice. */
	map?: SpaceMap;
}

/** A star on the chart. */
export interface StarChartStar {
	/** Its id in the map: `"x-…"`. */
	id: string;
	/** Null for a star that readers do not know and that no culture names. */
	name: string | null;
	/** Degrees, ICRS. */
	ra: number;
	dec: number;
	/** CSS pixels from the top left of the chart. */
	x: number;
	y: number;
	/** A star of the figure, not one near it. */
	member: boolean;
}

/** A member of the figure that is no star of the catalogue: a cluster, a nebula. */
export interface StarChartStandIn {
	name: string | null;
	ra: number;
	dec: number;
	x: number;
	y: number;
}

/** A name in its place, in CSS pixels from the top left of the chart. */
export interface StarChartLabel {
	left: number;
	top: number;
	width: number;
	height: number;
	name: string;
	/** The star it names; absent on a stand-in. */
	id?: string;
	member: boolean;
}

/** What the chart draws over its sky, where a host can draw its own. */
export interface StarChartOverlay {
	frame: ChartFrame;
	/** The stars of the figure, the brightest in the painted sky first. */
	stars: StarChartStar[];
	/** The named stars around it that stand out as much. */
	neighbours: StarChartStar[];
	standIns: StarChartStandIn[];
	/** The lines of the figure, from star to star. */
	lines: [x1: number, y1: number, x2: number, y2: number][];
	/** The names as the chart lays them out. Empty until they are known, and on
	 *  a chart under 150 CSS pixels on its short side, which shows no names. */
	labels: StarChartLabel[];
	/** The sky is painted. */
	sky: boolean;
}

/** A work the chart draws from, as its credit line names it. */
export interface StarChartCredit {
	/** `sky`: the star map behind it. `constellations`: the figure, and the
	 *  catalogues that place its stars and name them. */
	section: 'sky' | 'constellations';
	organisation: string;
	source: string;
	license?: string;
}

/** What a chart tells its page. */
export interface StarChartEvents {
	/** A name was clicked. The chart goes nowhere: what follows is the page's. */
	select: (star: StarChartStar) => void;
	/** The chart drew: after each paint, and as its names are found. */
	overlay: (overlay: StarChartOverlay) => void;
	/** A paint or a later read failed. The chart keeps what it shows. */
	error: (error: Error) => void;
}

const SVG_NS = 'http://www.w3.org/2000/svg';
const DEG = Math.PI / 180;
/** The hero's limits on the shape of a figure. */
const MIN_ASPECT = 1;
const MAX_ASPECT = 1.6;

const onceTarget = new WeakMap<object, unknown>();

function raDec([x, y, z]: readonly number[]): { ra: number; dec: number } {
	return { ra: (((Math.atan2(y, x) / DEG) % 360) + 360) % 360, dec: Math.asin(z) / DEG };
}

/** A place of the sky in CSS pixels from the top left of a chart's frame. It
 *  can be outside the chart. */
export function projectStarChart(frame: ChartFrame, ra: number, dec: number): [number, number] {
	const c = Math.cos(dec * DEG);
	return project(frame, [c * Math.cos(ra * DEG), c * Math.sin(ra * DEG), Math.sin(dec * DEG)]);
}

/** A chart of one figure. Made by {@link createStarChart}. */
export class StarChart {
	private readonly root = document.createElement('div');
	private readonly canvas = document.createElement('canvas');
	private readonly svg = document.createElementNS(SVG_NS, 'svg');
	private readonly nameLayer = document.createElement('div');
	private readonly options: Required<Omit<StarChartOptions, 'map'>>;
	private readonly map: SpaceMap | undefined;
	private controls: ControlHost<StarChart> | null = null;
	private resizeObserver: ResizeObserver | null = null;
	private held: { sky: ChartSky; release: () => void } | null = null;
	private painter: ChartPainter | null = null;
	private readonly listeners = new Map<keyof StarChartEvents, Set<(...args: never[]) => void>>();
	/** @internal The credit line, which no host may take back off. */
	attribution: Control<StarChart> | null = null;

	private loaded: LoadedChart | null = null;
	private figureName = '';
	private skyCredit: Omit<StarChartCredit, 'section'> | null = null;
	private frame: ChartFrame | null = null;
	private points: ChartPoints | null = null;
	private names: ChartNames | null = null;
	private placed: PlacedName[] = [];
	/** A picture is on the canvas, with a sky or without. */
	private shown = false;
	private painted = false;
	/** A paint ended with no sky. */
	private skyless = false;
	private family = '';
	private readonly textWidth = nameWidth();
	private disposed = false;
	private firstPaint: (() => void) | null = null;
	private readonly retry = new RetryBackoff<null>(() => void this.readNames());

	constructor(options: StarChartOptions) {
		const { map, ...rest } = options;
		this.map = map;
		this.options = {
			slug: rest.slug,
			figure: rest.figure,
			framing: rest.framing ?? 'fit',
			names: rest.names ?? true,
			neighbours: rest.neighbours ?? true,
			sky: rest.sky ?? true
		};
		const fill = this.options.framing === 'fill';
		this.root.className = `sm-chart${fill ? ' sm-chart--fill' : ''}${this.options.sky ? ' sm-chart--sky' : ''}`;
		// The sky has its own left and right: east is on the left in every language.
		this.root.dir = 'ltr';
		this.root.setAttribute('role', 'figure');
		this.canvas.className = 'sm-chart__sky';
		this.canvas.setAttribute('aria-hidden', 'true');
		this.svg.setAttribute('class', 'sm-chart__lines');
		this.svg.setAttribute('aria-hidden', 'true');
		this.nameLayer.className = 'sm-chart__names';
		this.nameLayer.addEventListener('click', this.onNameClick);
		this.root.append(this.canvas, this.svg, this.nameLayer);
	}

	// -- lifecycle ------------------------------------------------------------

	/** @internal Put the chart inside `container`. {@link createStarChart} does
	 *  this; a host never has to. */
	mount(container: HTMLElement): void {
		container.append(this.root);
		this.controls = new ControlHost(this, this.root);
		this.held = this.options.sky ? holdChartSky(this.map?.ctx) : null;
		this.painter = new ChartPainter(this.held?.sky ?? null, {
			painted: (frame, sky) => this.onPainted(frame, sky),
			named: (names) => this.onNamed(names),
			failed: (e) => {
				this.report(e);
				this.settle();
			}
		});
		this.resizeObserver = new ResizeObserver(() => this.resize());
		this.resizeObserver.observe(this.root);
	}

	/** @internal Load the figure and paint it once. Rejects with a
	 *  `StarChartError` when the figure has no chart. */
	async load(): Promise<void> {
		const [{ name, chart }, metadata] = await Promise.all([
			fetchFigureChart(this.options.slug, this.options.figure),
			this.options.sky ? fetchMetadata() : null
		]);
		if (this.disposed) return;
		const skybox = metadata?.skybox;
		this.skyCredit = skybox
			? { organisation: skybox.organisation, source: skybox.source, license: skybox.license }
			: null;
		this.figureName = name;
		this.root.setAttribute('aria-label', host().messages.star_chart_label({ name }));
		const painted = new Promise<void>((resolve) => (this.firstPaint = resolve));
		this.adopt(chart);
		// A chart with no size yet paints when it gets one.
		if (this.frame) await painted;
	}

	/** Hang a control in one of the chart's corners; top-right unless the
	 *  control or the caller names another. */
	addControl(control: Control<StarChart>, position?: ControlPosition): this {
		if (!this.controls) throw new Error('spacemap: the chart is not mounted');
		this.controls.add(control, position);
		return this;
	}

	/** Take a control back off. The credit line is not one a host may remove:
	 *  the terms of the works it names require it. */
	removeControl(control: Control<StarChart>): this {
		if (control === this.attribution)
			throw new Error('spacemap: the attribution control cannot be removed');
		this.controls?.remove(control);
		return this;
	}

	/** Take the chart out of its container and free what it holds. It is
	 *  finished afterwards; open another with {@link createStarChart}. */
	remove(): void {
		if (this.disposed) return;
		this.disposed = true;
		this.painter?.dispose();
		this.painter = null;
		this.retry.clear(null);
		this.resizeObserver?.disconnect();
		this.resizeObserver = null;
		this.controls?.clear();
		this.controls = null;
		this.held?.release();
		this.held = null;
		this.nameLayer.removeEventListener('click', this.onNameClick);
		this.listeners.clear();
		this.root.remove();
		this.settle();
	}

	// -- what it shows --------------------------------------------------------

	/** The figure's name in the host's language. */
	get name(): string {
		return this.figureName;
	}

	/** The works behind what the chart draws now, as its credit line names them. */
	get credits(): StarChartCredit[] {
		const out: StarChartCredit[] = [];
		if (this.painted && this.skyCredit) out.push({ section: 'sky', ...this.skyCredit });
		const seen = new Set<string>();
		for (const credit of this.loaded?.credits ?? []) {
			const organisation = constellationCreditName(credit);
			if (!credit.license || seen.has(organisation)) continue;
			seen.add(organisation);
			out.push({
				section: 'constellations',
				organisation,
				source: credit.source,
				license: credit.license
			});
		}
		return out;
	}

	/** Where the chart's stars, lines and names are, or null before its first paint. */
	getOverlay(): StarChartOverlay | null {
		const { frame, points, loaded } = this;
		if (!frame || !points || !loaded || !this.shown) return null;
		const names = this.names?.frame === frame ? this.names : noNames(frame, points);
		const star = (measured: MeasuredStar, member: boolean): StarChartStar => ({
			id: extrasolarObjectId(measured.star.id),
			name: measured.name,
			...raDec(measured.star.direction),
			x: measured.x,
			y: measured.y,
			member
		});
		return {
			frame,
			stars: names.members.map((measured) => star(measured, true)),
			neighbours: names.neighbours.map((measured) => star(measured, false)),
			standIns: loaded.chart.standIns.map(({ direction, name }, i) => ({
				name: name ?? null,
				...raDec(direction),
				x: points.standIns[i][0],
				y: points.standIns[i][1]
			})),
			lines: points.segments.map((segment) => [...segment]),
			labels: this.placed.map(({ neighbour, ...label }) => ({ ...label, member: !neighbour })),
			sky: this.painted
		};
	}

	/** A place of the sky in CSS pixels from the top left of the chart, or null
	 *  before the chart has a size. It can be outside the chart. */
	project(ra: number, dec: number): [number, number] | null {
		return this.frame ? projectStarChart(this.frame, ra, dec) : null;
	}

	// -- events ---------------------------------------------------------------

	/** Listen for `event`. The returned function stops listening. */
	on<K extends keyof StarChartEvents>(event: K, listener: StarChartEvents[K]): () => void {
		let set = this.listeners.get(event);
		if (!set) {
			set = new Set();
			this.listeners.set(event, set);
		}
		set.add(listener as (...args: never[]) => void);
		return () => set.delete(listener as (...args: never[]) => void);
	}

	/** Listen for the next `event` only. */
	once<K extends keyof StarChartEvents>(event: K, listener: StarChartEvents[K]): () => void {
		const wrapped = ((...args: Parameters<StarChartEvents[K]>) => {
			off();
			(listener as (...a: Parameters<StarChartEvents[K]>) => void)(...args);
		}) as StarChartEvents[K];
		onceTarget.set(wrapped, listener);
		const off = this.on(event, wrapped);
		return off;
	}

	off<K extends keyof StarChartEvents>(event: K, listener: StarChartEvents[K]): void {
		const set = this.listeners.get(event);
		if (!set) return;
		set.delete(listener as (...args: never[]) => void);
		for (const held of set) if (onceTarget.get(held) === listener) set.delete(held);
	}

	/** A listener that throws stops neither the chart nor the other listeners. */
	private emit<K extends keyof StarChartEvents>(
		event: K,
		...args: Parameters<StarChartEvents[K]>
	): void {
		for (const listener of [...(this.listeners.get(event) ?? [])]) {
			try {
				(listener as (...a: unknown[]) => void)(...args);
			} catch (e) {
				console.error(`[star-chart] a listener of ${event} threw:`, e);
			}
		}
	}

	/** To the `error` listeners, or to the console when there are none. */
	private report(e: unknown): void {
		const error = e instanceof Error ? e : new Error(String(e));
		if (this.listeners.get('error')?.size) this.emit('error', error);
		else console.warn('[star-chart] draw failed:', error);
	}

	/** `createStarChart` resolves. */
	private settle(): void {
		this.firstPaint?.();
		this.firstPaint = null;
	}

	private emitOverlay(): void {
		const overlay = this.getOverlay();
		if (overlay) this.emit('overlay', overlay);
	}

	// -- painting -------------------------------------------------------------

	private adopt(chart: LoadedChart): void {
		this.loaded = { ...chart, name: rememberNames(chart.name) };
		this.names = null;
		// A chart with no neighbours yet draws now and reads them again later.
		if (chart.more) this.retry.fail(null);
		else this.retry.clear(null);
		this.frame = null;
		this.resize();
	}

	/** Read the international names again. New neighbours are named on the
	 *  picture that is shown, with no new paint. */
	private async readNames(): Promise<void> {
		const of = this.loaded;
		if (!of?.more) return;
		const fuller = await of.more();
		if (this.disposed || this.loaded !== of) return;
		this.loaded = { ...fuller, name: of.name };
		if (fuller.more) this.retry.fail(null);
		else this.retry.clear(null);
		this.painter?.extend(this.loaded);
	}

	/** A new size of the box, or a new figure: a new frame, painted soon. */
	private resize(): void {
		const chart = this.loaded?.chart ?? null;
		const fill = this.options.framing === 'fill';
		const width = this.root.clientWidth;
		const height = fill ? this.root.clientHeight : 0;
		const choice = chooseFrame(chart, {
			width,
			height,
			fill,
			labels: true,
			minAspect: MIN_ASPECT,
			maxAspect: MAX_ASPECT
		});
		if (!fill) this.root.style.aspectRatio = String(choice.ratio);
		const was = this.frame;
		const at = choice.frame;
		if (at && was && at.width === was.width && at.height === was.height) return;
		this.frame = at;
		this.points = at && chart ? chartPoints(at, chart) : null;
		// The names of another size are not at their stars.
		this.placed = [];
		this.drawOver();
		const { loaded, points } = this;
		this.painter?.show(
			at && loaded && points
				? {
						frame: at,
						points,
						chart: loaded,
						canvas: this.canvas,
						fill,
						// The overlay holds the stars on a chart of any size.
						search: true,
						most: fill ? FILL_LABEL_MAX : LABEL_MAX,
						neighbours: this.options.neighbours
					}
				: null
		);
	}

	private onPainted(frame: ChartFrame, sky: boolean): void {
		this.shown = true;
		this.painted = sky;
		this.skyless = !sky;
		this.canvas.classList.toggle('sm-chart__sky--painted', sky);
		if (this.names?.frame !== frame && this.points) {
			this.names = noNames(frame, this.points);
			this.placed = [];
		}
		this.family = getComputedStyle(this.nameLayer).fontFamily;
		this.drawOver();
		this.emitOverlay();
		this.settle();
	}

	private onNamed(names: ChartNames): void {
		this.names = names;
		const { width, height } = names.frame;
		// A chart this small shows no names of its own. The overlay still holds the stars.
		this.placed =
			Math.min(width, height) >= LABEL_MIN_PX
				? layoutNames(names, (text) => this.textWidth(text, this.family), this.covered())
				: [];
		this.drawNames();
		this.emitOverlay();
	}

	/** The boxes of the controls, which no name may cover. */
	private covered(): LabelBox[] {
		const origin = this.root.getBoundingClientRect();
		return [...this.root.querySelectorAll<HTMLElement>(':scope > .sm-ctrl > *')].map((element) => {
			const box = element.getBoundingClientRect();
			return {
				left: box.left - origin.left,
				top: box.top - origin.top,
				width: box.width,
				height: box.height
			};
		});
	}

	/** The lines and rings of the frame. */
	private drawOver(): void {
		const { frame, points, loaded } = this;
		if (!frame || !points || !loaded) {
			this.svg.replaceChildren();
			this.nameLayer.replaceChildren();
			return;
		}
		this.svg.setAttribute('viewBox', `0 0 ${frame.width} ${frame.height}`);
		const path = document.createElementNS(SVG_NS, 'path');
		path.setAttribute('d', linePath(points.segments, true));
		path.setAttribute('class', 'sm-chart__line');
		const ring = ([x, y]: [number, number], r: number): SVGCircleElement => {
			const circle = document.createElementNS(SVG_NS, 'circle');
			circle.setAttribute('cx', String(x));
			circle.setAttribute('cy', String(y));
			circle.setAttribute('r', String(r));
			circle.setAttribute('class', 'sm-chart__ring');
			return circle;
		};
		// A figure with no lines shows its stars by a ring. So does one with no sky.
		const ringed = loaded.chart.lines.length === 0 || this.skyless;
		this.svg.replaceChildren(
			path,
			...(ringed ? points.stars.map((at) => ring(at, 3.5)) : []),
			...points.standIns.map((at) => ring(at, STAND_IN_RING_PX))
		);
		this.drawNames();
	}

	private drawNames(): void {
		if (!this.options.names) return;
		this.nameLayer.replaceChildren(
			...this.placed.map((label) => {
				const element = document.createElement(label.id ? 'button' : 'span');
				element.className = `sm-chart__name${label.neighbour ? ' sm-chart__name--neighbour' : ''}`;
				if (element instanceof HTMLButtonElement) {
					element.type = 'button';
					element.dataset.id = label.id;
				}
				element.style.left = `${label.left}px`;
				element.style.top = `${label.top}px`;
				element.style.height = `${label.height}px`;
				const text = document.createElement('bdi');
				text.textContent = label.name;
				element.append(text);
				return element;
			})
		);
	}

	private readonly onNameClick = (event: MouseEvent): void => {
		const id = (event.target as Element | null)?.closest<HTMLElement>('[data-id]')?.dataset.id;
		const overlay = id ? this.getOverlay() : null;
		const star = overlay && [...overlay.stars, ...overlay.neighbours].find((s) => s.id === id);
		if (star) this.emit('select', star);
	};
}
