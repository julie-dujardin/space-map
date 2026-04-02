import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { ObjectType, isMajorBody, type PositionedBody } from '$lib/types/objects';
import './label.css';

export type LabelVariant = 'major' | 'spacecraft' | 'none';

export function getLabelVariant(body: PositionedBody): LabelVariant {
	const t = body.data.objectType;
	if (isMajorBody(t) || t === ObjectType.STAR) return 'major';
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
	onClick: () => void
): CSS2DObject | null {
	if (variant === 'none') return null;

	// Root: sized to the indicator only, no transition (CSS2DRenderer writes transform here)
	const el = document.createElement('div');
	el.className = `scene-label scene-label--${variant}`;

	// halo: visual ring/hexagon, transition lives here not on root
	const halo = document.createElement('div');
	halo.className = `scene-label__halo scene-label__halo--${variant}`;
	// color-derived styles stay inline
	if (variant === 'major') {
		halo.style.border = `2px solid ${color}`;
		halo.style.background = `${color}22`;
	} else {
		halo.style.background = `${color}22`;
		halo.style.outline = `2px solid ${color}`;
	}
	el.appendChild(halo);

	// Name text: absolutely positioned to the right, vertically centered on indicator
	if (name) {
		const span = document.createElement('span');
		span.className = `scene-label__name scene-label__name--${variant}`;
		span.textContent = name;
		span.addEventListener('click', (e) => {
			e.stopPropagation();
			onClick();
		});
		el.appendChild(span);
	}

	el.addEventListener('click', (e) => {
		e.stopPropagation();
		onClick();
	});
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
