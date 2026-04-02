import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { ObjectType, isMajorBody, type PositionedBody } from '$lib/types/objects';

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
 * Indicator child: holds the visual ring/hexagon + transition for hover scale,
 * so it never fights with CSS2DRenderer's positioning transform.
 *
 * Name text: absolutely positioned to the right of the indicator.
 */
export function createLabel(
	color: string,
	name: string,
	variant: LabelVariant,
	onClick: () => void
): CSS2DObject | null {
	if (variant === 'none') return null;

	const indicatorSize = variant === 'major' ? 32 : 20;

	// Root: sized to the indicator only, no transition (CSS2DRenderer writes transform here)
	const el = document.createElement('div');
	el.style.cssText = [
		`width:${indicatorSize}px`,
		`height:${indicatorSize}px`,
		'position:relative',
		'pointer-events:auto',
		'cursor:pointer',
		'user-select:none'
	].join(';');

	// Indicator child: visual ring/hexagon, transition lives here not on root
	const indicator = document.createElement('div');
	indicator.style.cssText = ['width:100%', 'height:100%', 'transition:transform 0.1s'].join(';');

	if (variant === 'major') {
		indicator.style.borderRadius = '50%';
		indicator.style.border = `2px solid ${color}`;
		indicator.style.background = `${color}22`;
	} else {
		indicator.style.clipPath = 'polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)';
		indicator.style.background = `${color}22`;
		indicator.style.outline = `1px solid ${color}`;
	}

	el.appendChild(indicator);

	// Name text: absolutely positioned to the right, vertically centered on indicator
	if (name) {
		const span = document.createElement('span');
		span.textContent = name;
		span.style.cssText = [
			'position:absolute',
			`left:${indicatorSize + 8}px`,
			'top:50%',
			'transform:translateY(-50%)',
			'white-space:nowrap',
			'pointer-events:auto',
			'cursor:pointer',
			'color:white',
			`font-size:${variant === 'major' ? 14 : 10}px`,
			variant === 'major' ? 'font-weight:bold' : '',
			'text-shadow:0 0 4px #000,0 0 4px #000'
		].join(';');
		span.addEventListener('click', (e) => {
			e.stopPropagation();
			onClick();
		});
		span.addEventListener('mouseenter', () => {
			indicator.style.transform = 'scale(1.15)';
			document.body.style.cursor = 'pointer';
		});
		span.addEventListener('mouseleave', () => {
			indicator.style.transform = '';
			document.body.style.cursor = '';
		});
		el.appendChild(span);
	}

	el.addEventListener('click', (e) => {
		e.stopPropagation();
		onClick();
	});
	el.addEventListener('mouseenter', () => {
		indicator.style.transform = 'scale(1.15)';
		document.body.style.cursor = 'pointer';
	});
	el.addEventListener('mouseleave', () => {
		indicator.style.transform = '';
		document.body.style.cursor = '';
	});

	return new CSS2DObject(el);
}
