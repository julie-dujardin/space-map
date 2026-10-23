/** The site row's quick search: a plain query, the first hits grouped by kind,
 *  and the keys that walk them from the field. Nothing goes to the URL. */

import { tick, untrack } from 'svelte';
import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import { fetchGroupIndex } from '$lib/fetch/groups/registry';
import { featureTypeLabel } from '$lib/format/feature-type';
import { searchHitHref } from '$lib/state/page-href';
import { fetchObjectNames, search, type SearchHit } from './client';
import { hitName, secondaryText } from './format';

/** Long enough that a one-letter keystroke doesn't fan out to the index. */
const MIN_QUERY = 2;
const DEBOUNCE_MS = 180;
const LIMIT = 10;

/** Group order, and each group's heading. */
const KINDS: { kind: SearchHit['kind']; label: () => string }[] = [
	{ kind: 'object', label: m.search_kind_object },
	{ kind: 'feature', label: m.search_kind_feature },
	{ kind: 'group', label: m.search_kind_group },
	{ kind: 'pad', label: m.group_pads }
];

export interface HitGroup {
	kind: SearchHit['kind'];
	label: string;
	/** `index` is the row's place in the walk of the arrow keys. */
	rows: { hit: SearchHit; index: number }[];
}

export class QuickSearch {
	query = $state('');
	hits = $state<SearchHit[]>([]);
	searching = $state(false);
	activeIndex = $state(-1);
	#names = $state(new Map<string, string>());
	#featureSlugByCode = $state<Record<string, string>>({});

	trimmed = $derived(this.query.trim());
	active = $derived(this.trimmed.length >= MIN_QUERY);
	groups = $derived.by((): HitGroup[] => {
		let index = 0;
		const out: HitGroup[] = [];
		for (const { kind, label } of KINDS) {
			const hits = this.hits.filter((h) => h.kind === kind);
			if (hits.length)
				out.push({ kind, label: label(), rows: hits.map((hit) => ({ hit, index: index++ })) });
		}
		return out;
	});
	/** The rows in the order they are drawn, which is the order the arrows walk. */
	rows = $derived(this.groups.flatMap((g) => g.rows.map((r) => r.hit)));
	allHref = $derived(`/?q=${encodeURIComponent(this.trimmed)}`);

	readonly listboxId: string;
	// Newest query wins: a stale answer is dropped, never shown over a newer one.
	#token = 0;
	/** Enter came before the hits of the last keystroke. */
	#pickTop = false;
	#featureTypesAsked = false;

	constructor(listboxId: string) {
		this.listboxId = listboxId;

		$effect(() => {
			const q = this.trimmed;
			const locale = getLocale();
			this.#pickTop = false;
			if (q.length < MIN_QUERY) {
				this.hits = [];
				this.searching = false;
				return;
			}
			untrack(() => this.#askFeatureTypes());
			const mine = ++this.#token;
			this.searching = true;
			const timer = setTimeout(() => {
				search(q, locale, LIMIT)
					.then((found) => {
						if (mine !== this.#token) return;
						this.hits = found;
						this.searching = false;
						if (this.#pickTop) {
							this.#pickTop = false;
							tick().then(() => this.#follow(0));
						}
					})
					.catch((e) => {
						if (mine !== this.#token) return;
						console.warn('[quick-search] query failed:', e);
						this.hits = [];
						this.searching = false;
					});
			}, DEBOUNCE_MS);
			return () => clearTimeout(timer);
		});

		$effect(() => {
			void this.hits;
			this.activeIndex = -1;
		});

		$effect(() => {
			const i = this.activeIndex;
			if (i >= 0) document.getElementById(this.optionId(i))?.scrollIntoView({ block: 'nearest' });
		});

		// Parents and hosts arrive as ids.
		$effect(() => {
			const names = this.#names;
			const locale = getLocale();
			const ids = this.hits
				.map((h) => (h.kind === 'object' ? h.parent_id : h.kind === 'feature' ? h.body_id : null))
				.filter((id): id is string => !!id && !names.has(id));
			if (!ids.length) return;
			untrack(() => fetchObjectNames(ids, locale)).then((named) => {
				if (named.size) this.#names = new Map([...this.#names, ...named]);
			});
		});
	}

	/** Feature type names live on the group index, fetched with the first query
	 *  rather than with every page. */
	#askFeatureTypes(): void {
		if (this.#featureTypesAsked) return;
		this.#featureTypesAsked = true;
		fetchGroupIndex().then((index) => {
			const out: Record<string, string> = {};
			for (const [slug, entry] of Object.entries(index)) if (entry.code) out[entry.code] = slug;
			this.#featureSlugByCode = out;
		});
	}

	optionId(index: number): string {
		return `${this.listboxId}-${index}`;
	}

	name(hit: SearchHit): string {
		return hitName(hit, getLocale());
	}

	secondary(hit: SearchHit): string {
		return secondaryText(hit, {
			bodyName: (id) => this.#names.get(id) ?? id,
			featureTypeLabel: (code) => featureTypeLabel(this.#featureSlugByCode[code]) ?? code
		});
	}

	href(hit: SearchHit): string {
		return searchHitHref(hit, this.name(hit));
	}

	/** A row is a link, so following it is a click on it. */
	#follow(index: number): void {
		document.getElementById(this.optionId(index))?.click();
	}

	/** Arrows walk the rows from the field. Enter follows the highlighted row,
	 *  else the top one, once the hits of the last keystroke are in. */
	onKey = (e: KeyboardEvent): void => {
		if (e.key === 'Enter') {
			// An input method confirms its text with Enter.
			if (e.isComposing || e.keyCode === 229) return;
			e.preventDefault();
			if (this.activeIndex >= 0) this.#follow(this.activeIndex);
			else if (this.searching) this.#pickTop = true;
			else this.#follow(0);
			return;
		}
		const n = this.rows.length;
		if (!n) return;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			this.activeIndex = (this.activeIndex + 1) % n;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			this.activeIndex = this.activeIndex <= 0 ? n - 1 : this.activeIndex - 1;
		}
	};
}
