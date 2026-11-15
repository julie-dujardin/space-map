/** The parts both credit lines are built from. */

export const HOME_URL = 'https://spacemap.co';
export const CREDITS_URL = 'https://spacemap.co/credits';

export function bar(): HTMLElement {
	const el = document.createElement('div');
	el.className = 'sm-attribution';
	return el;
}

export function group(): HTMLElement {
	const el = document.createElement('span');
	el.className = 'sm-attribution__group';
	return el;
}

export function link(href: string, text: string, className?: string): HTMLAnchorElement {
	const a = document.createElement('a');
	a.href = href;
	a.target = '_blank';
	a.rel = 'noopener noreferrer';
	a.textContent = text;
	if (className) a.className = className;
	return a;
}

/** A group of the line: its label, then the names. Hidden with no names. */
export function fillGroup(el: HTMLElement, label: string, names: readonly string[]): void {
	el.hidden = names.length === 0;
	if (el.hidden) return;
	const tag = document.createElement('span');
	tag.className = 'sm-attribution__label';
	tag.textContent = `${label}:`;
	el.replaceChildren(tag, ` ${names.join(' · ')}`);
}
