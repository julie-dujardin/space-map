/**
 * A word or two drawn at a place. A marker is the host's own element, styled
 * and built by the host; a label is the cheap case, where all it wanted was
 * the text and the map's own way of drawing it — white on a shadow, legible
 * over a lit limb as well as over the sky.
 */

import { MarkerExtension } from './marker';
import type { Anchor } from './anchor';
import type { Shape } from './style';
import './drawings.css';

export interface LabelOptions {
	anchor: Anchor;
	text: string;
	/** Any CSS colour. White when left out. */
	color?: string;
	fontSizePx?: number;
	/** Which point of the text sits on the anchor, 0 to 1 in its own box.
	 *  Defaults to its centre. */
	align?: readonly [number, number];
	/** Hide the label when its place has turned to the far side of the body it
	 *  sits on. */
	occlude?: boolean;
	/** Take pointer events, so the host's own listeners on {@link Label.element}
	 *  fire. Off by default: the camera is dragged through the label layer. */
	interactive?: boolean;
	/** Added to the element, for styling from the host's own stylesheet. */
	className?: string;
}

export interface Label extends Shape {
	/** The element the text is in, for a host that wants to listen to it or
	 *  style it further. */
	readonly element: HTMLElement;
	setText(text: string): void;
}

export class LabelExtension extends MarkerExtension implements Label {
	constructor(options: LabelOptions, canvas: HTMLCanvasElement) {
		const element = document.createElement('div');
		element.className = 'sm-drawing-label';
		if (options.interactive) element.classList.add('sm-drawing--interactive');
		if (options.className) element.classList.add(options.className);
		element.textContent = options.text;
		if (options.color) element.style.color = options.color;
		if (options.fontSizePx !== undefined) element.style.fontSize = `${options.fontSizePx}px`;
		super(
			{ anchor: options.anchor, element, align: options.align, occlude: options.occlude },
			canvas
		);
	}

	setText(text: string): void {
		this.element.textContent = text;
	}
}
