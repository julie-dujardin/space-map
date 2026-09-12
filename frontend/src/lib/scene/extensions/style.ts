/**
 * How a drawing on the map looks, and what a host holds on to once it is
 * drawn. The flat map's shapes take the same words — a colour, a width in
 * screen pixels, an opacity, a fill — so a page holding both maps describes a
 * drawing once and draws it twice.
 *
 * Widths are pixels rather than kilometres because the scene spans metres to
 * astronomical units: a line a kilometre wide is a wall from a low orbit and
 * nothing at all from the next planet out.
 */

import type { Anchor } from './anchor';

export interface ShapeStyle {
	/** Any CSS colour. White when left out. */
	color?: string;
	/** Outline width in screen pixels, held at any distance. Zero leaves the
	 *  outline out, for an area drawn as a fill alone. */
	widthPx?: number;
	/** 0 to 1, over the outline. */
	opacity?: number;
	/** Fill colour for an area. An area is filled in its own colour unless it
	 *  says otherwise; a circle is a ring until it is given one. */
	fill?: string;
	/** 0 to 1, over the fill. */
	fillOpacity?: number;
}

/** A drawing on the map, for as long as the host keeps it. */
export interface Shape {
	/** Move it onto another place or body. */
	setAnchor(anchor: Anchor): void;
	/** Show or hide it without giving up its place. */
	setVisible(visible: boolean): void;
	remove(): void;
}
