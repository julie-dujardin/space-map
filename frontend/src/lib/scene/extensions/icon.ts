/**
 * A picture at a place, the same size on screen wherever the camera is: a
 * mission badge over a landing site, an arrow over a spacecraft. It is drawn
 * in the map's label layer rather than as geometry, which is what holds its
 * size — a sprite in a scene spanning metres to astronomical units has no one
 * size that works.
 */

import { MarkerExtension } from './marker';
import type { Anchor } from './anchor';
import type { Shape } from './style';
import './drawings.css';

export interface IconOptions {
	anchor: Anchor;
	/** Where the picture comes from. Anything an `<img>` takes, a data URL
	 *  included. */
	url: string;
	/** Width in screen pixels. The picture's own width when left out. */
	widthPx?: number;
	/** Height in screen pixels. Follows the width when left out. */
	heightPx?: number;
	/** Which point of the picture sits on the anchor, 0 to 1 in its own box.
	 *  Defaults to its centre. */
	align?: readonly [number, number];
	/** Hide it when its place has turned to the far side of the body it sits
	 *  on. */
	occlude?: boolean;
	/** 0 to 1. */
	opacity?: number;
	/** Take pointer events, so the host's own listeners on {@link Icon.element}
	 *  fire. Off by default: the camera is dragged through the label layer. */
	interactive?: boolean;
	className?: string;
	/** Describes the picture to a screen reader. Empty by default, which is
	 *  what a decorative picture should say. */
	alt?: string;
}

export interface Icon extends Shape {
	/** The `<img>` itself, for a host that wants to listen to it or style it
	 *  further. */
	readonly element: HTMLImageElement;
	setUrl(url: string): void;
}

export class IconExtension extends MarkerExtension implements Icon {
	declare readonly element: HTMLImageElement;

	constructor(options: IconOptions, canvas: HTMLCanvasElement) {
		const element = document.createElement('img');
		element.className = 'sm-drawing-icon';
		if (options.interactive) element.classList.add('sm-drawing--interactive');
		if (options.className) element.classList.add(options.className);
		element.src = options.url;
		element.alt = options.alt ?? '';
		if (options.widthPx !== undefined) element.style.width = `${options.widthPx}px`;
		if (options.heightPx !== undefined) element.style.height = `${options.heightPx}px`;
		if (options.opacity !== undefined) element.style.opacity = String(options.opacity);
		super(
			{ anchor: options.anchor, element, align: options.align, occlude: options.occlude },
			canvas
		);
	}

	setUrl(url: string): void {
		this.element.src = url;
	}
}
