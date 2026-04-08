import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { ObjectType, isAsteroid, isMajorBody, type PositionedBody } from '$lib/types/objects';
import './label.css';

export type LabelVariant = 'major' | 'spacecraft' | 'none';

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
	isLarge = false
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
		svg.classList.add('scene-label__halo', 'scene-label__halo--spacecraft');
		const path = document.createElementNS(ns, 'path');
		path.setAttribute(
			'd',
			'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z'
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

	// Name text: absolutely positioned to the right, vertically centered on indicator
	if (name) {
		const span = document.createElement('span');
		span.className = `scene-label__name scene-label__name--${variant}${isLarge ? ' scene-label__name--large' : ''}`;
		span.textContent = name;
		span.addEventListener('click', guardedClick);
		el.appendChild(span);
	}

	el.addEventListener('click', guardedClick);
	el.addEventListener('mouseenter', () => {
		halo.style.transform = 'scale(1.15)';
		document.body.style.cursor = 'pointer';
	});
	el.addEventListener('mouseleave', () => {
		halo.style.transform = '';
		document.body.style.cursor = '';
	});

	return new CSS2DObject(el);
}
