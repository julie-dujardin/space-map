/** The drawer's galleries and image-viewer model: pooled shelf names, the
 *  active gallery, the viewer gate, and the links a shelf or viewer picture
 *  leads out through. */

import type { Snippet } from 'svelte';
import {
	ATMOSPHERE_GALLERY,
	buildGalleries,
	findGallery,
	heroImage,
	imageCount,
	type Gallery,
	type ShelfLink
} from '$lib/fetch/objects/galleries';
import { fetchObjectDetail, type ObjectDetailData } from '$lib/fetch/objects/object-data';
import { pickImageUrl } from '$lib/fetch/objects/images';
import type { GroupDetailData } from '$lib/fetch/groups/details';
import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
import type { AppState } from '$lib/state/app-state.svelte';
import type { FocusFeature, FocusObject } from '$lib/state/focusable';
import { focusHref, tabHref } from '$lib/state/focus-link';
import { applyFeature, serializeUrl } from '$lib/state/url';
import { SHELF_TABS } from '../tab-visibility';
import type { DrawerTab } from '$lib/state/view';
import * as m from '$lib/paraglide/messages.js';

export interface GalleryStateDeps {
	isGroupMode: () => boolean;
	data: () => ObjectDetailData | null;
	groupDetail: () => GroupDetailData | null;
	bodyId: () => string | undefined;
	displayName: () => string;
	appState: () => AppState;
	focusObject: () => FocusObject | undefined;
	focusFeature: () => FocusFeature | undefined;
	notableMembers: () => NotableMemberEntry[] | undefined;
	memberNames: () => Record<string, string> | undefined;
	notableFeatures: () => NotableMemberEntry[] | undefined;
	featureNames: () => Record<string, string> | undefined;
	tabPresent: () => Record<DrawerTab, boolean>;
	tabLabels: () => Partial<Record<DrawerTab, string>>;
	/** The destination tab's own drawing, where it has one for a shelf — the
	 *  snippets stay in the drawer, whose template defines them. */
	backdrop: (key: string) => Snippet | undefined;
}

export class GalleryState {
	// A pooled gallery picture is labelled by its subject rather than its
	// filename, so the names resolved by the members/surface models land here.
	readonly subjectNames: Map<string, string>;
	readonly galleries: Gallery[];
	// A `&gal=` naming no shelf here (a stale link, another object's member)
	// falls back to the index, and the viewer to the leading shelf.
	readonly activeGallery: Gallery | undefined;
	readonly hasImages: boolean;
	readonly imageTotal: number;
	readonly viewerImages: Gallery['images'] | undefined;
	// Gate the viewer mount on a valid index AND a loaded images list. The
	// AppState's `?img=` URL parser doesn't know how many images this gallery
	// has, so we belt-and-braces the bound here too.
	readonly viewerActive: boolean;
	// Structure tab's hero is the atmosphere shelf — what the cross-section
	// plots is exactly what those photos show. Interior has no equivalent picture.
	readonly atmosphereGallery: Gallery | undefined;
	/** This page's own portrait, for a tile leading to another of its tabs. */
	readonly pageHero: string | undefined;

	// One promise per member, kept because the link resolves afresh on every
	// camera nudge (its href is built from the live view) and a new promise
	// restarts the tile's picture.
	#subjectHeroes = new Map<string, Promise<string | undefined>>();
	#deps: GalleryStateDeps;

	constructor(d: GalleryStateDeps) {
		this.#deps = d;
		this.subjectNames = $derived.by(() => {
			const names = new Map<string, string>();
			const memberNames = d.memberNames();
			const featureNames = d.featureNames();
			// Shelf subjects first: a notable member's own entry is the better name
			// where both exist, so it overwrites this.
			const global = d.isGroupMode() ? d.groupDetail()?.global : d.data()?.global;
			for (const gallery of global?.galleries ?? []) {
				if (gallery.subject && gallery.name) {
					names.set(gallery.subject, memberNames?.[gallery.subject] ?? gallery.name);
				}
			}
			for (const member of d.notableMembers() ?? []) {
				if (member.id) names.set(member.id, memberNames?.[member.id] ?? member.name);
			}
			for (const feature of d.notableFeatures() ?? []) {
				const key = `${feature.id}:${feature.feature_id}`;
				names.set(String(feature.feature_id), featureNames?.[key] ?? feature.name);
			}
			return names;
		});
		this.galleries = $derived(
			buildGalleries(
				(d.isGroupMode() ? d.groupDetail()?.global : d.data()?.global) ?? undefined,
				d.displayName(),
				(subject) => this.subjectNames.get(subject)
			)
		);
		this.activeGallery = $derived(findGallery(this.galleries, d.appState()?.view.gallery ?? null));
		this.hasImages = $derived(this.galleries.length > 0);
		this.imageTotal = $derived(imageCount(this.galleries));
		this.viewerImages = $derived((this.activeGallery ?? this.galleries[0])?.images);
		const viewerIndex = $derived(d.appState()?.view.imageIndex);
		this.viewerActive = $derived(
			!!this.viewerImages &&
				this.viewerImages.length > 0 &&
				viewerIndex != null &&
				viewerIndex < this.viewerImages.length
		);
		this.atmosphereGallery = $derived(findGallery(this.galleries, ATMOSPHERE_GALLERY));
		this.pageHero = $derived.by(() => {
			const image = heroImage(d.isGroupMode() ? d.groupDetail()?.global : d.data()?.global);
			return image ? pickImageUrl(image, 300) : undefined;
		});
	}

	/** A member's portrait for its tile. The bundle fetch is cached, and asking
	 *  for it warms the page the tile leads to. */
	#subjectHero(id: string): Promise<string | undefined> {
		let hero = this.#subjectHeroes.get(id);
		if (!hero) {
			hero = fetchObjectDetail(id).then((detail) => {
				const image = detail.global?.images?.[0];
				return image ? pickImageUrl(image, 300) : undefined;
			});
			this.#subjectHeroes.set(id, hero);
		}
		return hero;
	}

	/** A picture's subject — an Object.id, or an IAU feature id on this body —
	 *  as a link to it. Features are numbered; objects carry a type prefix. */
	subjectLink = (subject: string | number): ShelfLink | undefined => {
		const d = this.#deps;
		const name = this.subjectNames.get(String(subject));
		if (!name) return undefined;
		const appState = d.appState();
		if (typeof subject === 'number') {
			const bodyId = d.bodyId();
			if (!bodyId) return undefined;
			const focus = { bodyId, featureId: subject, featureName: name };
			return {
				label: name,
				kind: d.displayName(),
				href: appState ? serializeUrl(applyFeature(appState.view, focus)) : undefined,
				open: () => d.focusFeature()?.(bodyId, subject, name)
			};
		}
		// Its own pictures are what this link is about, so it lands on them
		// rather than on the object's overview.
		return {
			label: name,
			kind: m.tab_images(),
			hero: this.#subjectHero(subject),
			href: focusHref(appState, subject, name, 'images'),
			open: () => d.focusObject()?.(subject, name, { moveCamera: false, tab: 'images' })
		};
	};

	shelfLink = (gallery: Gallery): ShelfLink | undefined => {
		const d = this.#deps;
		if (gallery.subjectId) return this.subjectLink(gallery.subjectId);
		const tab = SHELF_TABS[gallery.key];
		if (!tab || !d.tabPresent()[tab]) return undefined;
		// What the destination tab draws, rather than a photograph: every
		// photograph of the subject is already on the shelf underneath, and the
		// chart is what the tab has that the gallery doesn't.
		const drawn = d.backdrop(gallery.key);
		const appState = d.appState();
		return {
			label: d.tabLabels()[tab] ?? gallery.title,
			kind: d.displayName(),
			hero: drawn ? undefined : this.pageHero,
			background: drawn,
			href: tabHref(appState, tab),
			open: () => appState.setTab(tab)
		};
	};
}
