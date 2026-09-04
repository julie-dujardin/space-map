import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { ObjectType, isAsteroid, isMajorBody, type PositionedBody } from '$lib/types/objects';
import { isModifiedClick } from '$lib/state/focus-link';
import type { BodyObjects } from '../types';
import { syncLabelAria } from './annotations';
import './label.css';
import { forgetLabelStyle } from './culling';

export type LabelVariant = 'major' | 'spacecraft' | 'debris' | 'none';

/** Lucide `package` — the flying spacecraft glyph. */
const SPACECRAFT_ICON_D =
	'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z';

/** Lucide `octagon` — used for probes once they're landed on a body. */
const LANDED_PROBE_ICON_D =
	'M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z';

/** Swap a spacecraft halo's SVG path between the flying and landed glyphs.
 *  Called from the probe position branch when isLandedAt transitions. */
export function setSpacecraftLanded(halo: HTMLElement | null, landed: boolean): void {
	if (!halo) return;
	const path = halo.querySelector('path');
	if (!path) return;
	path.setAttribute('d', landed ? LANDED_PROBE_ICON_D : SPACECRAFT_ICON_D);
}

function addLabelNameSpan(
	el: HTMLElement,
	name: string,
	variant: LabelVariant,
	isLarge: boolean
): HTMLSpanElement {
	// Plain span — the whole label root is the `<a>`, so halo + name are one link.
	const span = document.createElement('span');
	span.className = `scene-label__name scene-label__name--${variant}${isLarge ? ' scene-label__name--large' : ''}`;
	span.dir = 'auto'; // designations like "65803 Didymos" must not bidi-reorder in an RTL page
	span.textContent = name;
	// Straight after the halo, even when the name resolves after the annotation
	// stack was built: label culling reads the name span as the halo's sibling.
	const halo = el.firstElementChild;
	if (halo) halo.after(span);
	else el.appendChild(span);
	return span;
}

/** Update (or lazily create) the name span on an existing label. Used when a
 *  minor body's localized name resolves after the mesh renders (we don't wait
 *  on Wikidata to show the body). No-op for `variant: 'none'`. */
export function setLabelName(
	bo: BodyObjects,
	name: string,
	variant: LabelVariant,
	isLarge: boolean
): void {
	if (variant === 'none' || !name || !bo.label) return;
	const el = bo.label.element as HTMLElement;
	const existing = el.querySelector('.scene-label__name') as HTMLSpanElement | null;
	if (existing) existing.textContent = name;
	else addLabelNameSpan(el, name, variant, isLarge);
	syncLabelAria(bo);
}

export function getLabelVariant(body: PositionedBody): LabelVariant {
	const t = body.data.objectType;
	if (
		isMajorBody(t) ||
		t === ObjectType.STAR ||
		isAsteroid(t) ||
		t === ObjectType.COMET ||
		t === ObjectType.BARYCENTER ||
		t === ObjectType.LAGRANGE_POINT
	)
		return 'major';
	if (t === ObjectType.SPACECRAFT) return 'spacecraft';
	if (t === ObjectType.DEBRIS) return 'debris';
	return 'none';
}

/**
 * Creates a CSS2DObject label for a major body. Root is an `<a href>` so the
 * whole label is a real middle/⌘-clickable link screen readers announce;
 * tabindex=-1 keeps labels out of tab order (search is the keyboard path).
 * Left-click is intercepted to focus in-app instead of navigating.
 */
export function createLabel(
	color: string,
	name: string,
	variant: LabelVariant,
	href: string,
	onClick: () => void,
	isLarge = false,
	onHoverChange?: (hovered: boolean) => void,
	isMinor = false
): CSS2DObject | null {
	if (variant === 'none') return null;

	// Root: the link. Sized to the indicator only (CSS2DRenderer writes transform
	// here); draggable=false so a camera-drag over a label can't start a link drag.
	const el = document.createElement('a');
	el.className = `scene-label scene-label--${variant}`;
	el.href = href;
	el.tabIndex = -1;
	el.draggable = false;
	// Permanent accessible name: the visible name span is display:none'd while
	// culled/dimmed, which strips it from the name computation, so the anchor
	// carries its own aria-label that survives every dim/restore state.
	if (name) el.setAttribute('aria-label', name);

	// halo: visual ring/hexagon, transition lives here not on root
	let halo: HTMLElement | SVGSVGElement;
	if (variant === 'major') {
		const div = document.createElement('div');
		div.className = `scene-label__halo scene-label__halo--major`;
		div.style.border = `2px solid ${color}`;
		div.style.background = `${color}22`;
		halo = div;
	} else {
		const ns = 'http://www.w3.org/2000/svg';
		const svg = document.createElementNS(ns, 'svg');
		svg.setAttribute('viewBox', '0 0 24 24');
		svg.setAttribute('fill', `${color}22`);
		svg.setAttribute('stroke', color);
		svg.setAttribute('stroke-width', '2');
		svg.setAttribute('stroke-linejoin', 'round');
		svg.classList.add('scene-label__halo', `scene-label__halo--${variant}`);
		const path = document.createElementNS(ns, 'path');
		path.setAttribute('d', variant === 'debris' ? 'M3 5 L21 5 L12 21 Z' : SPACECRAFT_ICON_D);
		svg.appendChild(path);
		halo = svg;
	}
	el.appendChild(halo);

	// Click-vs-drag: record pointer position on pointerdown, then compare
	// with the click event's coordinates (which reflect the mouseup position).
	// This avoids pointermove which stops firing when the pointer leaves the
	// small label element during a drag.
	let downX = 0;
	let downY = 0;
	el.addEventListener('pointerdown', (e: PointerEvent) => {
		downX = e.clientX;
		downY = e.clientY;
	});
	const guardedClick = (e: MouseEvent) => {
		e.stopPropagation();
		// ⌘/ctrl/shift/middle-click → let the browser follow the anchor href (new tab).
		if (isModifiedClick(e)) return;
		e.preventDefault();
		const dx = e.clientX - downX;
		const dy = e.clientY - downY;
		if (dx * dx + dy * dy <= 9) onClick();
	};

	// Name text: absolutely positioned to the right, vertically centered on indicator
	if (name) addLabelNameSpan(el, name, variant, isLarge);
	// Minor halos collapse to the same scale as occluded/dimmed labels by
	// default; on hover they grow to the regular hover size, on mouseleave
	// they revert to the collapsed scale (instead of the no-transform default).
	if (isMinor) halo.style.transform = 'scale(0.3)';

	el.addEventListener('click', guardedClick);
	el.addEventListener('mouseenter', () => {
		halo.style.transform = 'scale(1.15)';
		document.body.style.cursor = 'pointer';
		onHoverChange?.(true);
	});
	el.addEventListener('mouseleave', () => {
		halo.style.transform = isMinor ? 'scale(0.3)' : '';
		forgetLabelStyle(halo);
		document.body.style.cursor = '';
		onHoverChange?.(false);
	});

	const obj = new CSS2DObject(el);
	obj.visible = false; // updateBodyVisibility sets the correct state next frame; avoids a 1-frame flash when added mid-load
	return obj;
}
