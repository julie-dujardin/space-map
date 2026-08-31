import type { BodyObjects } from '../types';

/**
 * Caption lines under a body's label: short disclaimers about what the marker
 * on screen is, or is not. Listed in the order they stack under the name —
 * `carrier` names the marker the body is drawn at, `missing` says what the body
 * has nothing of.
 */
export const ANNOTATION_KINDS = ['carrier', 'missing'] as const;

export type LabelAnnotation = (typeof ANNOTATION_KINDS)[number];

const SHOWN = 'scene-label__annotation--visible';

/**
 * Write one annotation line under a body's label, or hide it with `null`. Every
 * kind shares one stack, so two disclaimers on the same body sit under each
 * other instead of on top of each other. Lines are built on demand and kept
 * once built: which of them applies changes with the camera and the date, so
 * they are written per frame rather than at build time.
 */
export function setLabelAnnotation(
	bo: BodyObjects,
	kind: LabelAnnotation,
	text: string | null
): void {
	let span = bo.labelAnnotations?.[kind];
	if (!span) {
		if (!text || !bo.label) return;
		span = document.createElement('span');
		span.className = 'scene-label__annotation';
		span.dir = 'auto';
		span.textContent = text;
		insert(bo, span, kind);
		(bo.labelAnnotations ??= {})[kind] = span;
	} else {
		// Text is left in place when hiding, so the line has something to fade out.
		if (text === null) {
			if (!span.classList.contains(SHOWN)) return;
		} else if (span.textContent === text && span.classList.contains(SHOWN)) {
			return;
		} else {
			span.textContent = text;
		}
	}
	span.classList.toggle(SHOWN, text !== null);
	syncLabelAria(bo);
}

/**
 * Rebuild the anchor's accessible name from the body name plus every showing
 * annotation. The spans are display:none'd while the label is culled or dimmed,
 * which strips them from the name computation, so the anchor has to carry the
 * whole line itself.
 */
export function syncLabelAria(bo: BodyObjects): void {
	const el = bo.label?.element as HTMLElement | undefined;
	if (!el) return;
	// Read back from the name span so the two never drift; it survives every dim
	// state, which is display:none, not a text change.
	const parts = [el.querySelector('.scene-label__name')?.textContent || bo.body.data.name];
	for (const kind of ANNOTATION_KINDS) {
		const span = bo.labelAnnotations?.[kind];
		if (span?.classList.contains(SHOWN)) parts.push(span.textContent);
	}
	const label = parts.filter(Boolean).join(', ');
	if (label) el.setAttribute('aria-label', label);
	else el.removeAttribute('aria-label');
}

/** The one stack every annotation of a label shares, built with the first. */
function stack(bo: BodyObjects): HTMLElement {
	if (!bo.labelStack) {
		const el = document.createElement('span');
		el.className = 'scene-label__annotations';
		bo.label!.element.appendChild(el);
		bo.labelStack = el;
	}
	return bo.labelStack;
}

/** Keep the stack in ANNOTATION_KINDS order however the lines arrive. */
function insert(bo: BodyObjects, span: HTMLElement, kind: LabelAnnotation): void {
	for (const later of ANNOTATION_KINDS.slice(ANNOTATION_KINDS.indexOf(kind) + 1)) {
		const below = bo.labelAnnotations?.[later];
		if (below) {
			below.parentElement!.insertBefore(span, below);
			return;
		}
	}
	stack(bo).appendChild(span);
}
