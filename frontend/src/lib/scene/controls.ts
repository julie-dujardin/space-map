/**
 * Chrome a host hangs on a map. Both maps take the same kind of thing: an
 * object that builds an element when it is added and cleans up when it is
 * taken off, parked in one of the four corners.
 *
 * The corners are built as they are first used and sit above the map, passing
 * clicks through everywhere a control is not.
 */

import './controls.css';

export type ControlPosition = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';

const POSITIONS: readonly ControlPosition[] = [
	'top-left',
	'top-right',
	'bottom-left',
	'bottom-right'
];

/** One piece of chrome. `M` is the map it is written for. */
export interface Control<M = unknown> {
	/** Build the element to place in the corner. Called once, when added. */
	onAdd(map: M): HTMLElement;
	/** Release whatever `onAdd` set up. The element itself is removed either way. */
	onRemove?(map: M): void;
	/** Corner to use when the host names none; top-right otherwise. */
	getDefaultPosition?(): ControlPosition;
}

/** @internal The corners of one map, and what is in them. */
export class ControlHost<M> {
	private readonly corners = new Map<ControlPosition, HTMLElement>();
	private readonly added = new Map<Control<M>, HTMLElement>();

	constructor(
		private readonly map: M,
		private readonly root: HTMLElement
	) {}

	add(control: Control<M>, position?: ControlPosition): void {
		if (this.added.has(control)) return;
		const element = control.onAdd(this.map);
		this.added.set(control, element);
		this.corner(position ?? control.getDefaultPosition?.() ?? 'top-right').append(element);
	}

	remove(control: Control<M>): void {
		const element = this.added.get(control);
		if (!element) return;
		this.added.delete(control);
		control.onRemove?.(this.map);
		element.remove();
	}

	/** Take every control off, in the order they were added. */
	clear(): void {
		for (const control of [...this.added.keys()]) this.remove(control);
		for (const corner of this.corners.values()) corner.remove();
		this.corners.clear();
	}

	private corner(position: ControlPosition): HTMLElement {
		let corner = this.corners.get(position);
		if (corner) return corner;
		corner = document.createElement('div');
		corner.className = `sm-ctrl sm-ctrl--${position}`;
		this.corners.set(position, corner);
		// One pass over the fixed order, so a corner built late still sits in the
		// same stacking order as one built at boot.
		this.root.append(...POSITIONS.map((p) => this.corners.get(p)).filter((c) => c !== undefined));
		return corner;
	}
}
