<!--
  The sidebar shell the travel panel lives in on `/nav/<from>/<to>`.

  It mirrors DetailDrawer's frame — Vaul sheet on mobile, fixed aside on desktop
  — but has no tabs: a trip is one panel, and its two ends are the URL rather
  than a selection inside the app.
-->
<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import { Drawer as Vaul } from 'vaul-svelte';
	import { Button } from '$lib/components/ui/button/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import XIcon from '@lucide/svelte/icons/x';
	import Share2Icon from '@lucide/svelte/icons/share-2';
	import { toast } from 'svelte-sonner';
	import * as m from '$lib/paraglide/messages.js';
	import type { BodyData } from '$lib/types/objects';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { fetchObjectDetail, type GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { CAT_SOLAR_SYSTEM } from '$lib/fetch/groups/registry';
	import { sameSystemBlock } from '$lib/travel/travel-body';
	import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
	import type { TravelEndpointPick } from '$lib/travel/endpoint';
	import DrawerTitle from '../frame/DrawerTitle.svelte';
	import TravelPanel from './TravelPanel.svelte';

	interface Props {
		/** Departure and destination ids, straight off the route. The destination is
		 *  null on the empty form. */
		fromId: string;
		toId: string | null;
		/** IAU feature ids when an end is a named place on its body's surface. */
		fromFeatureId: number | null;
		toFeatureId: number | null;
		/** The app's clock, as a Julian Date. Live — see `nowJd` below. */
		clockJd: number;
		isMobile: boolean;
		inert?: boolean;
		onClose: () => void;
	}
	let {
		fromId,
		toId,
		fromFeatureId,
		toFeatureId,
		clockJd,
		isMobile,
		inert = false,
		onClose
	}: Props = $props();

	// The planner reasons from a "now" captured when the trip opens, not from the
	// live clock: the clock ticks twice a second and each tick would re-solve a
	// whole porkchop grid. Choosing a different date is what "depart at" is for.
	let nowJd = $derived.by(() => {
		void fromId;
		void toId;
		return untrack(() => clockJd);
	});

	const ctx = getContext<ContextManager | undefined>('ctx');
	const appState = getContext<AppState | undefined>('appState');

	// Bodies the panel can reason about. Rebuilt when the loader lands more of
	// them — an unresolved end shows as a blocked trip rather than an error.
	let bodiesById = $derived.by((): Map<string, BodyData> => {
		void ctx?.bodies.minorBodyVersion;
		const out = new Map<string, BodyData>();
		if (!ctx) return out;
		for (const [id, body] of ctx.bodies.bodiesById) out.set(id, body.data);
		return out;
	});

	let origin = $derived(bodiesById.get(fromId) ?? null);
	let target = $derived(toId === null ? null : (bodiesById.get(toId) ?? null));

	// Localized planet names come from the solar-system category's member map —
	// one cached fetch for the whole dropdown, instead of a localized object
	// bundle per candidate.
	let names = $state<Record<string, string>>({});
	$effect(() => {
		let cancelled = false;
		fetchGroupDetail(CAT_SOLAR_SYSTEM)
			.then((d) => {
				if (!cancelled) names = d.localized?.notable_member_names ?? {};
			})
			.catch((e) => console.warn('[travel] no localized body names, falling back to export:', e));
		return () => {
			cancelled = true;
		};
	});

	function displayName(body: BodyData): string {
		return names[body.id] ?? body.name ?? body.id;
	}

	// Bodies the search must not offer for one end, given what the other end is.
	// Only the loaded bodies can be tested — the index reaches far past the scene
	// — so this catches the two cases that actually come up (the same body twice,
	// and a moon of the other end's own primary) and leaves the rest to the
	// panel's own blocked state.
	function excluded(against: BodyData | null): ReadonlySet<string> {
		const out = new Set<string>();
		if (!against) return out;
		out.add(against.id);
		for (const b of bodiesById.values()) {
			if (sameSystemBlock(b, against, bodiesById) !== null) out.add(b.id);
		}
		return out;
	}

	let excludeForOrigin = $derived(excluded(target));
	let excludeForTarget = $derived(excluded(origin));

	// A feature endpoint is labelled by the place, not by the planet under it.
	// Resolved from the body's nomenclature so a shared link reads correctly on
	// load, when no pick handed us a name.
	let featureNames = $state<Record<string, string>>({});

	function loadFeatureName(bodyId: string, featureId: number | null) {
		if (featureId === null) return;
		const key = `${bodyId}:${featureId}`;
		if (featureNames[key]) return;
		let cancelled = false;
		fetchBodyNomenclature(bodyId)
			.then((features) => {
				const found = features.find((f) => f.featureId === featureId);
				if (cancelled) return;
				if (!found) {
					console.warn(`[travel] feature ${featureId} is not in ${bodyId}'s nomenclature.`);
					return;
				}
				featureNames = { ...featureNames, [key]: found.name };
			})
			.catch((e) => console.warn(`[travel] could not name feature ${featureId} on ${bodyId}:`, e));
		return () => {
			cancelled = true;
		};
	}

	$effect(() => loadFeatureName(fromId, fromFeatureId));
	$effect(() => {
		if (toId === null) return;
		return loadFeatureName(toId, toFeatureId);
	});

	/** What an end is called: the named place when there is one, else the body. */
	function endpointName(body: BodyData, featureId: number | null): string {
		if (featureId === null) return displayName(body);
		return featureNames[`${body.id}:${featureId}`] ?? displayName(body);
	}

	// Only the atmosphere is read, and only to decide whether an arrival gets an
	// aerocapture discount and a departure a drag loss. A failed fetch prices the
	// end airless, so it is logged rather than surfaced.
	let originDetail = $state<GlobalObjectData | null>(null);
	let targetDetail = $state<GlobalObjectData | null>(null);

	function loadDetail(id: string, set: (d: GlobalObjectData | null) => void) {
		let cancelled = false;
		fetchObjectDetail(id, false)
			.then((d) => {
				if (!cancelled) set(d.global);
			})
			.catch((e) => {
				console.warn(`[travel] no detail bundle for ${id}, pricing it airless:`, e);
				if (!cancelled) set(null);
			});
		return () => {
			cancelled = true;
		};
	}

	$effect(() => {
		originDetail = null;
		return loadDetail(fromId, (d) => (originDetail = d));
	});
	$effect(() => {
		targetDetail = null;
		if (toId === null) return;
		return loadDetail(toId, (d) => (targetDetail = d));
	});

	let crumb = $derived(
		target
			? {
					label: displayName(target),
					target: { kind: 'focus' as const, id: target.id, name: displayName(target) }
				}
			: null
	);

	async function handleShare() {
		try {
			await navigator.clipboard.writeText(window.location.href);
			toast.success(m.link_copied());
		} catch (e) {
			console.warn('[travel] clipboard write refused:', e);
		}
	}
</script>

{#snippet toolbar()}
	<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={handleShare}>
		<Share2Icon />
		<span class="sr-only">{m.share()}</span>
	</Button>
	<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={onClose}>
		<XIcon />
		<span class="sr-only">{m.close()}</span>
	</Button>
{/snippet}

{#snippet body(contentClass: string)}
	<div class={contentClass}>
		{#if origin}
			<TravelPanel
				{origin}
				{target}
				originName={endpointName(origin, fromFeatureId)}
				targetName={target ? endpointName(target, toFeatureId) : null}
				originFeatureId={fromFeatureId}
				targetFeatureId={toFeatureId}
				{bodiesById}
				{nowJd}
				{excludeForOrigin}
				{excludeForTarget}
				{originDetail}
				{targetDetail}
				onOriginChange={(pick: TravelEndpointPick) =>
					appState?.setNav(
						{ id: pick.bodyId, featureId: pick.featureId },
						toId === null ? null : { id: toId, featureId: toFeatureId }
					)}
				onTargetChange={(pick: TravelEndpointPick) =>
					appState?.setNav(
						{ id: fromId, featureId: fromFeatureId },
						{ id: pick.bodyId, featureId: pick.featureId }
					)}
				onSwap={() =>
					toId &&
					appState?.setNav(
						{ id: toId, featureId: toFeatureId },
						{ id: fromId, featureId: fromFeatureId }
					)}
			/>
		{:else}
			<p class="text-muted-foreground text-xs">{m.travel_unknown_orbit()}</p>
		{/if}
	</div>
{/snippet}

{#if isMobile}
	<Vaul.Root open={true} shouldScaleBackground={false} dismissible={false} repositionInputs={false}>
		<Vaul.Portal>
			<Vaul.Content
				{inert}
				trapFocus={false}
				aria-labelledby="travel-drawer-title"
				class="bg-background fixed inset-x-0 bottom-0 z-50 flex h-dvh max-h-dvh flex-col rounded-t-xl border-t shadow-lg outline-none"
			>
				<div class="flex flex-col items-center gap-2 px-4 pt-3 pb-2">
					<div class="bg-muted-foreground/40 h-1 w-10 rounded-full"></div>
					<div class="flex w-full items-center justify-between gap-2">
						<DrawerTitle {crumb} title={m.travel_title()} id="travel-drawer-title" />
						<div class="flex items-center gap-1.5">{@render toolbar()}</div>
					</div>
				</div>
				<div
					class="min-h-0 flex-1 overflow-y-auto"
					style="padding-bottom: calc(1rem + var(--safe-bottom));"
				>
					{@render body('px-4 pt-4')}
				</div>
			</Vaul.Content>
		</Vaul.Portal>
	</Vaul.Root>
{:else}
	<aside
		{inert}
		aria-labelledby="travel-drawer-title"
		class="bg-background fixed start-0 top-0 z-50 flex h-full w-[var(--detail-panel)] max-w-[90vw] flex-col border-e shadow-lg"
	>
		<!-- pt aligns the title row with the top-4 featured chips beside it. -->
		<div class="flex items-center justify-between gap-2 px-4 pt-[18px] pb-2">
			<DrawerTitle {crumb} title={m.travel_title()} id="travel-drawer-title" />
			<div class="flex items-center gap-1.5">{@render toolbar()}</div>
		</div>
		<ScrollArea class="min-h-0 flex-1">
			{@render body('px-4 pt-4 pb-4')}
		</ScrollArea>
	</aside>
{/if}
