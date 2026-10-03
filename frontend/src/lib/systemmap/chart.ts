/**
 * The system map as DOM: a minimap that doubles as a picker — click a body, a
 * moon stack or a band to follow what it links to. Built by hand rather than
 * as a component so the embeddable core can carry it.
 */

import { createScrub } from '$lib/charts/scrub';
import {
	BAND_H,
	BAND_Y,
	CY,
	HIT_MARGIN,
	RING_FORESHORTEN,
	VIEW_H,
	VIEW_W,
	X_RIGHT,
	hitTest,
	layout,
	tipFor,
	type Hover,
	type Layout,
	type MoonZone,
	type PlacedBody
} from './layout';
import type { MapLink, SystemMapModel } from './model';
import './system-map.css';

export interface ChartOptions {
	ariaLabel: string;
	/** `background` strips axis, labels, links and tooltips and fills and crops
	 *  its box: a static decorative diagram behind something else. */
	variant?: 'hero' | 'background';
}

const SVG_NS = 'http://www.w3.org/2000/svg';
/** px of limb shading, fixed so a wall-sized primary keeps an edge. */
const PRIMARY_RIM = 10;
/** deg, a ringed body's apparent ring tilt. */
const RING_TILT = -18;
const CLOUD_R = 1.2;
const TIP_H = 28;
const TIP_MARGIN = 6;
/** Viewbox px a band label keeps clear of the chart's edges. */
const LABEL_MARGIN = 4;
const LABEL_SIZE = 18;
const LABEL_MIN_SIZE = 12;
/** Viewbox px a band label may run to before it is set smaller. */
const LABEL_MAX_W = 190;

type Attrs = Record<string, string | number | undefined>;

function svg<K extends keyof SVGElementTagNameMap>(
	tag: K,
	attrs: Attrs = {},
	...children: (SVGElement | null | undefined)[]
): SVGElementTagNameMap[K] {
	const el = document.createElementNS(SVG_NS, tag);
	for (const [name, value] of Object.entries(attrs)) {
		if (value !== undefined) el.setAttribute(name, String(value));
	}
	for (const child of children) if (child) el.append(child);
	return el;
}

function sameHover(a: Hover | null, b: Hover | null): boolean {
	return JSON.stringify(a) === JSON.stringify(b);
}

/** Where everything that leads somewhere leads, by the hover it answers to. */
function linksOf(model: SystemMapModel, l: Layout): Map<string, MapLink> {
	const links = new Map<string, MapLink>();
	const add = (hover: Hover, link: MapLink | undefined) => {
		if (link?.href || link?.onclick) links.set(JSON.stringify(hover), link);
	};
	for (const band of l.bands) add({ kind: 'band', key: band.key }, band);
	add({ kind: 'primary' }, model.primary.link);
	for (const b of l.bodies) add({ kind: 'body', id: b.id }, b.link);
	for (const z of l.moonZones) {
		if (z.parent.grouped) continue;
		if (!z.perMoon) add({ kind: 'stack', id: z.parent.id }, z.parent.satellitesLink);
		else for (const mn of z.moons) add({ kind: 'moon', parent: z.parent.id, id: mn.id }, mn.link);
	}
	return links;
}

// Gradient and pattern ids are document-global; two maps on one page must not
// share the primary's userSpaceOnUse gradient.
let nextUid = 0;

export class SystemMapChart {
	readonly root = document.createElement('div');
	private readonly svg = svg('svg');
	private readonly tip = document.createElement('div');
	private readonly tipTitle = document.createElement('span');
	private readonly tipSub = document.createElement('span');
	private readonly uid = `sm-system-map-${nextUid++}`;
	private readonly resize = new ResizeObserver(() => {
		this.fitLabels();
		this.placeTip();
	});
	private model: SystemMapModel | null = null;
	private placed: Layout | null = null;
	private background = false;
	private hover: Hover | null = null;
	/** Shown while their target is hovered or focused, keyed by the hover. */
	private highlights = new Map<string, SVGElement[]>();
	/** What a click on each hover lands on. */
	private targets = new Map<string, SVGElement>();
	/** Where each target leads, read at the click so a swapped link is followed. */
	private links = new Map<string, MapLink>();
	/** What is drawn, as a string to tell a new picture from new links. */
	private shape = '';
	private labels: SVGTextElement[] = [];

	constructor() {
		this.tip.className = 'sm-system-map__tip';
		this.tipTitle.className = 'sm-system-map__tip-title';
		this.tipSub.className = 'sm-system-map__tip-sub';
		this.tip.append(this.tipTitle, this.tipSub);
		this.tip.hidden = true;
		this.root.append(this.svg, this.tip);
		this.resize.observe(this.root);

		// Touch drags preview whatever is under the finger; a tap keeps its click.
		const scrub = createScrub({
			onScrub: (x, y) => this.setHover(this.hitAt(x, y)),
			onEnd: () => this.setHover(null)
		});
		this.svg.addEventListener('pointerdown', scrub.onpointerdown);
		this.svg.addEventListener('pointermove', scrub.onpointermove);
		this.svg.addEventListener('pointerup', scrub.onpointerup);
		this.svg.addEventListener('pointercancel', scrub.onpointercancel);
		this.svg.addEventListener('pointerleave', scrub.onpointerleave);

		// A click reports whole pixels and a pointer fractions of one, which
		// tells two crowded bodies apart: the click is read where the pointer was.
		let at: [number, number] = [0, 0];
		const track = (e: PointerEvent) => {
			at = [e.clientX, e.clientY];
		};
		this.svg.addEventListener('pointerdown', track);
		this.svg.addEventListener('pointerup', track);
		this.svg.addEventListener('pointermove', (e) => {
			track(e);
			if (e.pointerType === 'mouse') this.setHover(this.hitAt(e.clientX, e.clientY));
		});
		this.svg.addEventListener('pointerleave', (e) => {
			if (e.pointerType === 'mouse') this.setHover(null);
		});
		this.svg.addEventListener(
			'click',
			(e) => {
				// A tap has no hover to route it, so the target on top takes it: pass
				// it on to the nearest. A key press or a passed-on click has no place.
				if (e.detail === 0) return;
				const near = Math.abs(at[0] - e.clientX) < 1 && Math.abs(at[1] - e.clientY) < 1;
				const hit = near ? this.hitAt(...at) : this.hitAt(e.clientX, e.clientY);
				if (!hit) return;
				const meant = this.targets.get(JSON.stringify(hit));
				if (meant?.contains(e.target as Node)) return;
				e.stopPropagation();
				e.preventDefault();
				meant?.dispatchEvent(
					new MouseEvent('click', {
						bubbles: true,
						cancelable: true,
						ctrlKey: e.ctrlKey,
						metaKey: e.metaKey,
						shiftKey: e.shiftKey,
						altKey: e.altKey,
						button: e.button
					})
				);
			},
			true
		);
	}

	destroy(): void {
		this.resize.disconnect();
		this.root.remove();
	}

	update(model: SystemMapModel, options: ChartOptions): void {
		this.model = model;
		this.placed = layout(model);
		// A host whose links follow its own state hands over a new model for every
		// change of it. The picture is then the same one, and redrawing it would
		// drop the reader's hover and keyboard focus: only the links are swapped.
		const links = linksOf(model, this.placed);
		const shape = JSON.stringify([
			JSON.stringify(model, (key, value: unknown) => (key === 'href' ? undefined : value)),
			options,
			[...links].map(([key, link]) => [key, !!link.href, !!link.onclick])
		]);
		this.links = links;
		if (shape === this.shape) {
			for (const [key, el] of this.targets) {
				const href = links.get(key)?.href;
				if (href) el.setAttribute('href', href);
			}
			return;
		}
		this.shape = shape;
		this.background = options.variant === 'background';
		this.hover = null;
		this.root.className = this.background
			? 'sm-system-map sm-system-map--background'
			: 'sm-system-map';
		this.draw(model, this.placed, options.ariaLabel);
		this.fitLabels();
		this.placeTip();
	}

	private draw(model: SystemMapModel, l: Layout, ariaLabel: string): void {
		const bg = this.background;
		this.highlights = new Map();
		this.targets = new Map();
		this.labels = [];
		const root = this.svg;
		root.replaceChildren();
		root.setAttribute('viewBox', (bg && model.backgroundView) || `0 0 ${VIEW_W} ${VIEW_H}`);
		// A cropped background is anchored left so it keeps the primary's limb and
		// the inner bodies rather than the empty middle of the axis.
		root.setAttribute(
			'preserveAspectRatio',
			bg
				? model.backgroundFit === 'fit'
					? 'xMidYMid meet'
					: model.backgroundView
						? 'xMinYMid slice'
						: 'xMidYMid slice'
				: 'xMidYMid meet'
		);
		root.setAttribute('class', 'sm-system-map__svg');
		root.setAttribute('role', 'group');
		root.setAttribute('aria-label', ariaLabel);
		// The site's drawer would otherwise take a scrub for a drag.
		root.setAttribute('data-vaul-no-drag', '');

		// Limb darkening of the primary's own tint: only the outer edge is on
		// screen for a big primary, so the rim is what gives the sliver its curve.
		const stop = (offset: string | number, opacity: number) =>
			svg('stop', { offset, 'stop-color': model.primary.color, 'stop-opacity': opacity });
		root.append(
			svg(
				'defs',
				{},
				svg(
					'radialGradient',
					{
						id: `${this.uid}-primary`,
						gradientUnits: 'userSpaceOnUse',
						cx: l.primaryCx,
						cy: CY,
						r: l.primaryR
					},
					stop('0%', 1),
					stop(Math.max(0, 1 - PRIMARY_RIM / l.primaryR), 0.85),
					stop('100%', 0.35)
				),
				svg(
					'pattern',
					{ id: `${this.uid}-band`, width: 9, height: 9, patternUnits: 'userSpaceOnUse' },
					svg('circle', { cx: 2, cy: 2, r: 0.9, fill: 'currentColor', opacity: 0.55 }),
					svg('circle', { cx: 6.5, cy: 6, r: 0.9, fill: 'currentColor', opacity: 0.55 })
				)
			)
		);

		if (!bg) this.drawAxis(model, l);

		// The anonymous population, under everything: it is the backdrop the bands
		// and bodies are read against, never a target.
		if (l.cloudPath)
			root.append(
				svg('path', {
					d: l.cloudPath,
					stroke: model.cloud?.color,
					'stroke-width': CLOUD_R * 2,
					'stroke-linecap': 'round',
					fill: 'none',
					opacity: 0.45,
					'pointer-events': 'none'
				})
			);

		for (const band of l.bands) {
			const fill = svg('rect', {
				x: band.x,
				y: BAND_Y,
				width: band.width,
				height: BAND_H,
				fill: `url(#${this.uid}-band)`,
				class: `sm-system-map__band sm-system-map__band--${band.tone}`
			});
			if (bg) {
				root.append(fill);
				continue;
			}
			const label = svg('text', {
				x: band.x + band.width / 2,
				y: VIEW_H - 8,
				'text-anchor': 'middle',
				'font-size': LABEL_SIZE,
				class: `sm-system-map__band-label sm-system-map__band-label--${band.tone}`
			});
			label.textContent = band.label;
			this.labels.push(label);
			root.append(
				this.target(
					band,
					band.name ?? band.label,
					{ kind: 'band', key: band.key },
					fill,
					svg('rect', {
						x: band.hitX,
						y: BAND_Y,
						width: band.hitWidth,
						height: BAND_H,
						fill: 'transparent'
					}),
					label
				)
			);
		}

		const disc = svg('circle', {
			cx: l.primaryCx,
			cy: CY,
			r: l.primaryR,
			fill: `url(#${this.uid}-primary)`
		});
		root.append(
			bg ? disc : this.target(model.primary.link, model.primary.name, { kind: 'primary' }, disc)
		);

		// Ringed bodies: a tilted, foreshortened band behind the dot. The stroke
		// width is the ring's thickness, the radius its mid-line.
		for (const b of l.bodies) {
			if (!b.rings) continue;
			const mid = (b.r * (b.rings.inner + b.rings.outer)) / 2;
			root.append(
				svg('ellipse', {
					cx: b.cx,
					cy: b.cy,
					rx: mid,
					ry: mid * RING_FORESHORTEN,
					transform: `rotate(${RING_TILT} ${b.cx} ${b.cy})`,
					fill: 'none',
					stroke: '#d9c89f',
					'stroke-width': b.r * (b.rings.outer - b.rings.inner),
					opacity: 0.45
				})
			);
		}

		const zoneOf = new Map(l.moonZones.map((z) => [z.parent.id, z]));
		for (const b of l.bodies) root.append(this.body(b, zoneOf.get(b.id)));
		for (const z of l.moonZones) if (!z.parent.grouped) this.stack(z);
	}

	/** Faint gridlines and log ticks along the top. */
	private drawAxis(model: SystemMapModel, l: Layout): void {
		for (const t of model.ticks) {
			const x = l.xOf(t * model.unitKm);
			const tick = svg('text', {
				x,
				y: 16,
				'text-anchor': 'middle',
				'font-size': 16,
				fill: 'currentColor',
				opacity: 0.85
			});
			tick.textContent = String(t);
			this.svg.append(
				svg('line', {
					x1: x,
					x2: x,
					y1: 20,
					y2: VIEW_H - 28,
					stroke: 'currentColor',
					'stroke-width': 0.5,
					opacity: 0.12
				}),
				tick
			);
		}
		const unit = svg('text', {
			x: X_RIGHT,
			y: 16,
			'text-anchor': 'end',
			'font-size': 14,
			fill: 'currentColor',
			opacity: 0.65
		});
		unit.textContent = model.axisLabel;
		this.svg.append(unit);
	}

	private body(b: PlacedBody, zone: MoonZone | undefined): SVGElement {
		// A landmark is a ring, so it does not read as one more thing to pick.
		const dot = b.reference
			? svg('circle', {
					cx: b.cx,
					cy: b.cy,
					r: b.r + 1,
					fill: 'none',
					stroke: b.color,
					'stroke-width': 1.2,
					class: 'sm-system-map__reference'
				})
			: svg('circle', { cx: b.cx, cy: b.cy, r: b.r, fill: b.color });
		if (this.background) {
			if (!zone || !b.grouped) return dot;
			return svg('g', {}, dot, ...this.moonDots(zone));
		}
		const hover: Hover = { kind: 'body', id: b.id };
		const ring = this.highlight(
			hover,
			svg('circle', {
				cx: b.cx,
				cy: b.cy,
				r: b.r + 3.5,
				fill: 'none',
				stroke: 'currentColor',
				'stroke-width': 1,
				opacity: 0.8
			})
		);
		const hit = svg('circle', { cx: b.cx, cy: b.cy, r: b.r + HIT_MARGIN, fill: 'transparent' });
		if (!zone || !b.grouped) return this.target(b.link, b.name, hover, ring, dot, hit);
		return this.target(
			b.link,
			b.name,
			hover,
			this.highlight(hover, this.zoneWash(zone)),
			ring,
			dot,
			hit,
			...this.moonDots(zone),
			this.zoneHit(zone)
		);
	}

	/** A stack that is not part of its body's target: one target for the whole
	 *  stack, or one per moon. */
	private stack(z: MoonZone): void {
		if (this.background) {
			this.svg.append(...this.moonDots(z));
			return;
		}
		const p = z.parent;
		if (z.perMoon) {
			this.svg.append(...this.moonDots(z));
			for (const mn of z.moons) {
				const hover: Hover = { kind: 'moon', parent: p.id, id: mn.id };
				this.svg.append(
					this.target(
						mn.link,
						mn.name,
						hover,
						this.highlight(
							hover,
							svg('circle', {
								cx: mn.cx,
								cy: mn.cy,
								r: mn.r + 2.5,
								fill: 'none',
								stroke: 'currentColor',
								'stroke-width': 1,
								opacity: 0.8
							})
						),
						svg('rect', {
							x: z.x,
							y: mn.hitY,
							width: z.width,
							height: mn.hitHeight,
							fill: 'transparent'
						})
					)
				);
			}
			return;
		}
		const hover: Hover = { kind: 'stack', id: p.id };
		const first = z.moons[0];
		this.svg.append(
			this.highlight(hover, this.zoneWash(z)),
			...this.moonDots(z),
			this.target(
				p.satellitesLink,
				p.satellitesTab
					? `${p.name} · ${this.model!.text.moons(p.satelliteCount ?? z.moons.length)}`
					: first.name,
				hover,
				this.zoneHit(z)
			)
		);
	}

	private moonDots(z: MoonZone): SVGElement[] {
		return z.moons.map((mn) => svg('circle', { cx: mn.cx, cy: mn.cy, r: mn.r, fill: mn.color }));
	}

	private zoneWash(z: MoonZone): SVGElement {
		return svg('rect', {
			x: z.x,
			y: z.y,
			width: z.width,
			height: z.height,
			rx: 4,
			fill: 'currentColor',
			opacity: 0.1,
			'pointer-events': 'none'
		});
	}

	private zoneHit(z: MoonZone): SVGElement {
		return svg('rect', { x: z.x, y: z.y, width: z.width, height: z.height, fill: 'transparent' });
	}

	private highlight(hover: Hover, el: SVGElement): SVGElement {
		const key = JSON.stringify(hover);
		const list = this.highlights.get(key);
		if (list) list.push(el);
		else this.highlights.set(key, [el]);
		el.style.display = 'none';
		return el;
	}

	/** Something that can be hovered, and followed if it has a link: a real
	 *  anchor when it leads to a URL, so a modified click opens it. */
	private target(
		link: MapLink | undefined,
		label: string,
		hover: Hover,
		...children: SVGElement[]
	): SVGElement {
		const linked = !!(link?.href || link?.onclick);
		const el = link?.href
			? svg('a', { href: link.href, 'aria-label': label })
			: linked
				? svg('g', {
						role: 'button',
						tabindex: 0,
						'aria-label': label,
						class: 'sm-system-map__button'
					})
				: svg('g');
		el.append(...children);
		if (!linked) return el;
		const key = JSON.stringify(hover);
		this.targets.set(key, el);
		el.addEventListener('focus', () => this.setHover(hover));
		el.addEventListener('blur', () => {
			if (sameHover(this.hover, hover)) this.setHover(null);
		});
		el.addEventListener('click', (e) => this.links.get(key)?.onclick?.(e as MouseEvent));
		if (!link?.href)
			el.addEventListener('keydown', (e) => {
				const key = (e as KeyboardEvent).key;
				if (key !== 'Enter' && key !== ' ') return;
				e.preventDefault();
				el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
			});
		return el;
	}

	private setHover(hover: Hover | null): void {
		if (sameHover(this.hover, hover)) return;
		for (const el of this.highlights.get(JSON.stringify(this.hover)) ?? [])
			el.style.display = 'none';
		this.targets.get(JSON.stringify(this.hover))?.removeAttribute('data-near');
		this.hover = hover;
		for (const el of this.highlights.get(JSON.stringify(hover)) ?? []) el.style.display = '';
		// The hit targets overlap where bodies crowd. Only the nearest takes the
		// pointer, so a middle click or a context menu opens the link the hover shows.
		const near = this.targets.get(JSON.stringify(hover));
		near?.setAttribute('data-near', '');
		this.svg.classList.toggle('sm-system-map__svg--near', !!near);
		this.placeTip();
	}

	private hitAt(clientX: number, clientY: number): Hover | null {
		if (!this.placed || this.background) return null;
		const rect = this.svg.getBoundingClientRect();
		if (!rect.width || !rect.height) return null;
		// Aspect ratios match (auto height, xMidYMid meet), so the map is uniform.
		const vx = ((clientX - rect.left) / rect.width) * VIEW_W;
		const vy = ((clientY - rect.top) / rect.height) * VIEW_H;
		return hitTest(this.placed, vx, vy);
	}

	/** A label is usually wider than its band: from a band near the edge it
	 *  would run off the chart, so it is pulled back inside, and a long one
	 *  would run into its neighbour's, so it is set smaller. */
	private fitLabels(): void {
		for (const label of this.labels) {
			let width = 0;
			label.setAttribute('font-size', String(LABEL_SIZE));
			try {
				width = label.getComputedTextLength();
			} catch {
				// Not laid out yet; the resize observer comes back to it.
			}
			if (!width) continue;
			if (width > LABEL_MAX_W) {
				const size = Math.max(LABEL_MIN_SIZE, (LABEL_SIZE * LABEL_MAX_W) / width);
				label.setAttribute('font-size', String(size));
				width *= size / LABEL_SIZE;
			}
			const centre = Number(label.dataset.centre ?? label.getAttribute('x'));
			label.dataset.centre = String(centre);
			const half = width / 2;
			const x = Math.min(
				Math.max(centre, half + LABEL_MARGIN),
				Math.max(half, VIEW_W - half - LABEL_MARGIN)
			);
			label.setAttribute('x', String(x));
		}
	}

	/** The hover readout: one line centred on its target and seated above it,
	 *  clamped by its measured width so a long one is never clipped. */
	private placeTip(): void {
		const tip =
			this.model && this.placed && !this.background
				? tipFor(this.model, this.placed, this.hover)
				: null;
		this.tip.hidden = !tip;
		if (!tip) return;
		this.tipTitle.textContent = tip.title;
		this.tipSub.textContent = tip.sub ? ` · ${tip.sub}` : '';
		// The aspect is fixed, so a viewBox unit maps to width / VIEW_W px.
		const containerW = this.root.clientWidth;
		const scale = containerW / VIEW_W;
		this.tip.style.maxWidth = `${Math.max(0, containerW - 2 * TIP_MARGIN)}px`;
		const half = this.tip.offsetWidth / 2;
		const left = Math.min(
			Math.max(tip.cx * scale, half + TIP_MARGIN),
			Math.max(half, containerW - half - TIP_MARGIN)
		);
		this.tip.style.left = `${left}px`;
		this.tip.style.top = `${Math.max(4, tip.cy * scale - TIP_H)}px`;
	}
}
