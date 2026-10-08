<script lang="ts">
	import XIcon from '@lucide/svelte/icons/x';
	import type { ClassValue } from 'svelte/elements';
	import * as m from '$lib/paraglide/messages.js';
	import { dismissProof, proofSlot, proofState } from '$lib/search/proof.svelte';

	type Props = {
		/** A card over the page, for a page with no search box to hold the widget. */
		floating?: boolean;
		/** False while the results that hold the widget are closed. The widget then
		 *  waits out of sight. */
		shown?: boolean;
		/** Spacing for the box inside its search box. */
		class?: ClassValue;
	};

	let { floating = false, shown = true, class: spacing }: Props = $props();

	let slot: HTMLDivElement | undefined = $state();
	const visible = $derived(shown && slot !== undefined && proofState.asking === slot);
</script>

<!-- Holds the Turnstile widget. It stays mounted with no size, because
     Cloudflare runs its check inside it. -->
<div
	inert={!shown}
	class={[
		floating &&
			'fixed start-1/2 top-20 z-[100] w-[min(21rem,calc(100vw-1rem))] -translate-x-1/2 rtl:translate-x-1/2',
		floating && visible && 'bg-popover text-popover-foreground rounded-lg border p-3 shadow-lg',
		floating && !visible && 'pointer-events-none',
		!floating && visible && spacing,
		!floating && !visible && 'absolute h-0 w-full overflow-hidden'
	]}
	aria-live="polite"
>
	{#if visible}
		<div class="mb-2 flex items-start gap-2">
			<p class={['flex-1', floating ? 'text-sm' : 'text-muted-foreground text-xs']}>
				{m.search_proof_prompt()}
			</p>
			{#if floating}
				<button
					type="button"
					class="text-muted-foreground hover:text-foreground -m-1 rounded p-1"
					aria-label={m.close()}
					onclick={dismissProof}
				>
					<XIcon class="size-4" />
				</button>
			{/if}
		</div>
	{/if}
	<!-- `--fit` comes from `proofSlot`: the widget has a least width of 300 px. -->
	<div
		bind:this={slot}
		use:proofSlot={{ shown, floating }}
		class="[&>div]:w-[max(100%,300px)] [&>div]:[zoom:var(--fit,1)]"
	></div>
</div>
