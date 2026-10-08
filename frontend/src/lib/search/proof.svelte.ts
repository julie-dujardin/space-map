/** Proof for the search key endpoint that a person is at the page: a Turnstile
 *  token. Cloudflare makes it and the endpoint checks it. */

import { toast } from 'svelte-sonner';
import { env } from '$env/dynamic/public';
import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';

/** Cloudflare serves the script from this address only. */
const SCRIPT = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';

/** The longest wait for a token that needs no click. The endpoint then decides
 *  without one. */
const PATIENCE_MS = 10_000;

/** Errors after which the widget tries again by itself, from Cloudflare's list
 *  of client-side codes. Any other error is final. */
const RETRIED = /^(300|600)\d*$|^(110600|110620|200500)$/;
/** The widget tries again this soon, to fit several tries inside `PATIENCE_MS`. */
const RETRY_MS = 2000;

/** The widget is this wide or more. A narrower slot draws it smaller. */
const WIDGET_MIN_PX = 300;

const TOAST_ID = 'search-proof';

interface Turnstile {
	render(slot: HTMLElement, options: Record<string, unknown>): string | null | undefined;
	remove(widget: string): void;
}

declare global {
	interface Window {
		turnstile?: Turnstile;
	}
}

export interface SlotOptions {
	/** The visitor can see the slot. */
	shown: boolean;
	/** The card of the layout. It shows itself, and is the last choice. */
	floating?: boolean;
}

/** A place on the page that can hold the widget. Each search box has one. */
interface Slot extends SlotOptions {
	el: HTMLElement;
}

class ProofState {
	/** The slot whose widget waits for a click. */
	asking = $state<HTMLElement | null>(null);
}

export const proofState = new ProofState();

/** Every mounted slot. A slot goes to the end when the visitor gets to see it. */
const slots: Slot[] = [];

/** The proof under way: where its widget is, how to move it, how to end it. */
let run: {
	slot: Slot;
	place: (slot: Slot) => void;
	end: (token: string | null) => void;
} | null = null;

/** The visitor is told once for each page load that a check waits out of sight. */
let told = false;

let openSearch: (() => void) | null = null;

/** Names the way to open the main search panel, for the button of the toast.
 *  Returns the call that takes it back. */
export function onOpenSearch(open: () => void): () => void {
	openSearch = open;
	return () => {
		if (openSearch === open) openSearch = null;
	};
}

/** The slot for the widget: the one the visitor saw last, else one out of
 *  sight, else the card of the layout. */
function best(): Slot | undefined {
	const own = slots.filter((slot) => !slot.floating);
	return own.findLast((slot) => slot.shown) ?? own.at(-1) ?? slots.at(-1);
}

/** Keeps a widget that wants a click where the visitor can reach it, and tells
 *  the visitor when there is no such place. */
function settle(): void {
	if (!run) return;
	const next = best();
	if (!slots.includes(run.slot)) {
		if (!next) return run.end(null);
		run.place(next);
	} else if (proofState.asking && !run.slot.shown && next?.shown) {
		run.place(next);
	}
	if (!proofState.asking || run.slot.shown) {
		toast.dismiss(TOAST_ID);
	} else if (!told) {
		told = true;
		toast.info(m.search_proof_prompt(), {
			id: TOAST_ID,
			duration: Number.POSITIVE_INFINITY,
			closeButton: true,
			action: openSearch
				? { label: m.search_proof_open(), onClick: () => openSearch?.() }
				: undefined
		});
	}
}

/** Action for an element that can hold the widget. */
export function proofSlot(el: HTMLElement, options: SlotOptions) {
	const slot: Slot = { el, ...options };
	slots.push(slot);
	const sized = new ResizeObserver(([{ contentRect }]) => {
		el.style.setProperty('--fit', String(Math.min(1, contentRect.width / WIDGET_MIN_PX)));
	});
	sized.observe(el);
	settle();
	return {
		update(next: SlotOptions) {
			if (next.shown && !slot.shown) slots.push(...slots.splice(slots.indexOf(slot), 1));
			slot.shown = next.shown;
			settle();
		},
		destroy() {
			sized.disconnect();
			slots.splice(slots.indexOf(slot), 1);
			settle();
		}
	};
}

/** Stops the wait for a click. The endpoint then decides without a token. */
export function dismissProof(): void {
	run?.end(null);
}

let loading: Promise<Turnstile> | null = null;

function load(): Promise<Turnstile> {
	loading ??= new Promise<Turnstile>((resolve, reject) => {
		const script = document.createElement('script');
		script.src = SCRIPT;
		script.async = true;
		script.onload = () => (window.turnstile ? resolve(window.turnstile) : reject());
		script.onerror = reject;
		document.head.append(script);
	}).catch((blocked: unknown) => {
		// A blocker can be off at the next try.
		loading = null;
		throw blocked;
	});
	return loading;
}

/** Resolves when the tab shows. A browser slows a hidden tab, and its token
 *  could come after `PATIENCE_MS`. */
function tabShown(): Promise<void> {
	if (document.visibilityState === 'visible') return Promise.resolve();
	return new Promise((resolve) => {
		const check = () => {
			if (document.visibilityState !== 'visible') return;
			document.removeEventListener('visibilitychange', check);
			resolve();
		};
		document.addEventListener('visibilitychange', check);
	});
}

/**
 * One token, or null when none came. Without `PUBLIC_TURNSTILE_SITEKEY` it
 * loads nothing from Cloudflare.
 *
 * The widget shows only when Cloudflare wants a click. It then goes to the
 * search box the visitor has open, and the wait lasts until the click.
 */
export async function takeProof(): Promise<string | null> {
	const sitekey = env.PUBLIC_TURNSTILE_SITEKEY;
	if (!sitekey) return null;
	await tabShown();
	const api = await load().catch(() => null);
	const first = best();
	if (!api || !first) return null;
	let widget: string | null | undefined;
	let patience: ReturnType<typeof setTimeout> | undefined;
	/** Counts the widgets, so a callback of a removed one is ignored. */
	let placed = 0;
	try {
		return await new Promise<string | null>((resolve) => {
			const place = (slot: Slot) => {
				const mine = ++placed;
				if (widget) api.remove(widget);
				widget = null;
				proofState.asking = null;
				clearTimeout(patience);
				patience = setTimeout(() => resolve(null), PATIENCE_MS);
				run = { slot, place, end: resolve };
				try {
					widget = api.render(slot.el, {
						sitekey,
						action: 'search',
						appearance: 'interaction-only',
						size: 'flexible',
						theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
						language: getLocale(),
						callback: (token: string) => {
							if (mine === placed) resolve(token);
						},
						'retry-interval': RETRY_MS,
						'error-callback': (code: unknown) => {
							if (mine === placed && !RETRIED.test(String(code))) resolve(null);
							// `true` tells Cloudflare that the page handles the error.
							return true;
						},
						'unsupported-callback': () => {
							if (mine === placed) resolve(null);
						},
						'before-interactive-callback': () => {
							if (mine !== placed) return;
							clearTimeout(patience);
							proofState.asking = slot.el;
							// Not inside the callback: `settle` can remove this widget.
							queueMicrotask(settle);
						}
					});
				} catch {
					// Cloudflare refuses the key or an option.
				}
				if (!widget) resolve(null);
			};
			place(first);
		});
	} finally {
		clearTimeout(patience);
		run = null;
		proofState.asking = null;
		toast.dismiss(TOAST_ID);
		if (widget) api.remove(widget);
	}
}
