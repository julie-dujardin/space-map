import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { ObjectType, isAsteroid, isMajorBody, type PositionedBody } from '$lib/types/objects';
import './label.css';

export type LabelVariant = 'major' | 'spacecraft' | 'debris' | 'none';

/** Click handler attached to a label's name span — stashed on the root via a
 *  WeakMap so {@link setLabelName} can re-bind it when adding the span lazily
 *  (e.g. after a click-promoted minor body's detail bundle resolves). */
const labelClickHandlers = new WeakMap<HTMLElement, (e: MouseEvent) => void>();

function addLabelNameSpan(
	el: HTMLElement,
	name: string,
	variant: LabelVariant,
	isLarge: boolean,
	onClick: (e: MouseEvent) => void
): HTMLSpanElement {
	const span = document.createElement('span');
	span.className = `scene-label__name scene-label__name--${variant}${isLarge ? ' scene-label__name--large' : ''}`;
	span.textContent = name;
	span.addEventListener('click', onClick);
	el.appendChild(span);
	return span;
}

/** Update (or lazily create) the name span on an existing label. Used when a
 *  click-promoted minor body's localized name resolves a few hundred ms after
 *  the mesh + halo are rendered — we don't want to wait on Wikidata before
 *  showing the body, so the span is filled in once the bundle arrives. No-op
 *  when the label was created with `variant: 'none'` (e.g. debris). */
export function setLabelName(
	label: CSS2DObject,
	name: string,
	variant: LabelVariant,
	isLarge: boolean
): void {
	if (variant === 'none' || !name) return;
	const el = label.element as HTMLElement;
	const existing = el.querySelector('.scene-label__name') as HTMLSpanElement | null;
	if (existing) {
		existing.textContent = name;
		return;
	}
	const handler = labelClickHandlers.get(el);
	if (!handler) return;
	addLabelNameSpan(el, name, variant, isLarge, handler);
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
 * Creates a CSS2DObject label for a major body.
 *
 * Root element (el): fixed indicator size, no transition — CSS2DRenderer writes
 * its `transform` every frame to position it in screen space.
 *
 * halo: holds the visual ring/hexagon + transition for hover scale,
 * so it never fights with CSS2DRenderer's positioning transform.
 *
 * Name text: absolutely positioned to the right of the halo.
 */
export function createLabel(
	color: string,
	name: string,
	variant: LabelVariant,
	onClick: () => void,
	isLarge = false,
	onHoverChange?: (hovered: boolean) => void
): CSS2DObject | null {
	if (variant === 'none') return null;

	// Root: sized to the indicator only, no transition (CSS2DRenderer writes transform here)
	const el = document.createElement('div');
	el.className = `scene-label scene-label--${variant}`;

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
		path.setAttribute(
			'd',
			variant === 'debris'
				? 'M3 5 L21 5 L12 21 Z'
				: 'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z'
		);
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
		const dx = e.clientX - downX;
		const dy = e.clientY - downY;
		if (dx * dx + dy * dy <= 9) onClick();
	};

	// Stash the guarded-click handler so setLabelName() can re-bind it if the
	// span gets added later (lazy-resolved name on click-promoted bodies).
	labelClickHandlers.set(el, guardedClick);

	// Name text: absolutely positioned to the right, vertically centered on indicator
	if (name) addLabelNameSpan(el, name, variant, isLarge, guardedClick);

	el.addEventListener('click', guardedClick);
	el.addEventListener('mouseenter', () => {
		halo.style.transform = 'scale(1.15)';
		document.body.style.cursor = 'pointer';
		onHoverChange?.(true);
	});
	el.addEventListener('mouseleave', () => {
		halo.style.transform = '';
		document.body.style.cursor = '';
		onHoverChange?.(false);
	});

	const obj = new CSS2DObject(el);
	obj.visible = false; // updateBodyVisibility sets the correct state next frame; avoids a 1-frame flash when added mid-load
	return obj;
}
