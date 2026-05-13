<script lang="ts">
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import XIcon from '@lucide/svelte/icons/x';
	import * as Popover from '$lib/components/ui/popover';
	import * as m from '$lib/paraglide/messages.js';
	import SettingsMenu from './SettingsMenu.svelte';

	let open = $state(false);
	let isMobile = $state(false);

	$effect(() => {
		const mq = window.matchMedia('(max-width: 767px)');
		isMobile = mq.matches;
		const onChange = (e: MediaQueryListEvent) => (isMobile = e.matches);
		mq.addEventListener('change', onChange);
		return () => mq.removeEventListener('change', onChange);
	});

	// Esc-to-close for the mobile fullscreen panel (Popover handles this itself).
	$effect(() => {
		if (!open || !isMobile) return;
		const onKey = (e: KeyboardEvent) => {
			if (e.key === 'Escape') open = false;
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	});

	const buttonClass = `pointer-events-auto flex items-center justify-center
		w-10 h-10 md:w-8 md:h-8 rounded-full
		bg-black/40 backdrop-blur-md hover:bg-black/55
		text-white transition-colors cursor-pointer`;
</script>

{#if isMobile}
	<button
		type="button"
		class={buttonClass}
		onclick={() => (open = true)}
		title={m.settings_title()}
		aria-label={m.settings_title()}
	>
		<SettingsIcon class="size-5" />
	</button>

	{#if open}
		<!-- Custom fullscreen panel (not Sheet) so we sit above ObjectDrawer's
		     z-50 stack and stay visible regardless of which side-drawer is open. -->
		<div
			class="fixed inset-0 z-[70] bg-background overflow-y-auto"
			role="dialog"
			aria-modal="true"
			aria-label={m.settings_title()}
		>
			<button
				type="button"
				class="absolute top-3 end-3 z-10 inline-flex items-center justify-center
					w-9 h-9 rounded-md hover:bg-accent transition-colors cursor-pointer"
				onclick={() => (open = false)}
				aria-label={m.close()}
			>
				<XIcon class="size-5" />
			</button>
			<SettingsMenu />
		</div>
	{/if}
{:else}
	<Popover.Root bind:open>
		<Popover.Trigger class={buttonClass} title={m.settings_title()} aria-label={m.settings_title()}>
			<SettingsIcon class="size-4" />
		</Popover.Trigger>
		<Popover.Content
			side="bottom"
			align="end"
			sideOffset={8}
			class="w-80 max-h-[80vh] overflow-hidden p-0"
		>
			<SettingsMenu />
		</Popover.Content>
	</Popover.Root>
{/if}
