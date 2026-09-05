<script lang="ts">
	import { Drawer as Vaul } from 'vaul-svelte';
	import ClockIcon from '@lucide/svelte/icons/clock';
	import XIcon from '@lucide/svelte/icons/x';
	import { Button } from '$lib/components/ui/button/index.js';
	import * as Popover from '$lib/components/ui/popover';
	import { getLocale, getTextDirection } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { DRAWER_TOP_GAP_PX } from '$lib/drawer';
	import TimeMenu from './TimeMenu.svelte';

	interface Props {
		clock: SimClock;
		/** A phone gets a bottom sheet; a desktop too narrow for the time bar
		 *  gets a popover like the other corner buttons. */
		isMobile?: boolean;
	}

	let { clock, isMobile = false }: Props = $props();

	let open = $state(false);

	const buttonClass = `pointer-events-auto flex items-center justify-center
		w-12 h-12 md:w-10 md:h-10 rounded-full
		bg-white hover:bg-white/80
		text-black transition-colors cursor-pointer`;

	// The button sits at the inline-end edge; open the popover toward screen centre.
	const side = $derived(getTextDirection(getLocale()) === 'rtl' ? 'right' : 'left');
</script>

{#if isMobile}
	<button
		type="button"
		onclick={() => (open = true)}
		class={buttonClass}
		title={m.time_header()}
		aria-label={m.time_header()}
	>
		<ClockIcon class="size-7 md:size-5" />
	</button>

	<Vaul.Root bind:open shouldScaleBackground={false}>
		<Vaul.Portal>
			<Vaul.Overlay class="fixed inset-0 z-[60] bg-black/40" />
			<Vaul.Content
				class="fixed inset-x-0 bottom-0 z-[61] flex flex-col rounded-t-xl border-t bg-background shadow-lg outline-none"
				style="max-height: calc(100dvh - {DRAWER_TOP_GAP_PX}px);"
			>
				<div class="flex shrink-0 flex-col items-center gap-2 px-4 pt-3 pb-2">
					<div class="h-1 w-10 rounded-full bg-muted-foreground/40"></div>
					<div class="flex w-full items-center justify-between">
						<Vaul.Title class="text-sm font-semibold">{m.time_header()}</Vaul.Title>
						<Button variant="ghost" size="icon-sm" onclick={() => (open = false)}>
							<XIcon />
							<span class="sr-only">{m.close()}</span>
						</Button>
					</div>
				</div>

				<!-- The calendar makes the sheet outgrow a short screen, so the body scrolls
				     under a pinned header rather than the picker being cut off. -->
				<div
					class="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 pb-[calc(env(safe-area-inset-bottom)+1rem)]"
				>
					<TimeMenu {clock} />
				</div>
			</Vaul.Content>
		</Vaul.Portal>
	</Vaul.Root>
{:else}
	<Popover.Root bind:open>
		<Popover.Trigger class={buttonClass} title={m.time_header()} aria-label={m.time_header()}>
			<ClockIcon class="size-7 md:size-5" />
		</Popover.Trigger>
		<Popover.Content {side} align="end" sideOffset={8} class="w-80 gap-3 p-4">
			<div class="text-xs font-medium text-muted-foreground">{m.time_header()}</div>
			<TimeMenu {clock} />
		</Popover.Content>
	</Popover.Root>
{/if}
