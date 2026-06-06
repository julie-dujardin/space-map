<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { getSettings, type ViewMode } from '$lib/state/settings.svelte';

	const settings = getSettings();

	const viewOptions: { value: ViewMode; label: () => string; desc: () => string }[] = [
		{ value: 'map', label: () => m.layers_view_map(), desc: () => m.layers_view_map_desc() },
		{
			value: 'immersive',
			label: () => m.layers_view_immersive(),
			desc: () => m.layers_view_immersive_desc()
		}
	];
</script>

<div class="flex flex-col">
	<header class="px-5 pt-5 pb-3">
		<h2 class="text-base font-semibold">{m.layers_title()}</h2>
	</header>

	<div class="px-5 pb-5 flex flex-col gap-5 overflow-y-auto">
		<section class="flex flex-col gap-3">
			<h3
				id="layers-view-mode-label"
				class="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase"
			>
				{m.layers_view_mode()}
			</h3>
			<div class="flex flex-col gap-3" role="radiogroup" aria-labelledby="layers-view-mode-label">
				{#each viewOptions as opt (opt.value)}
					{@const active = settings.viewMode === opt.value}
					<button
						type="button"
						role="radio"
						aria-checked={active}
						class="text-start rounded-md border p-3 transition-colors cursor-pointer
							{active
							? 'border-primary bg-primary/5'
							: 'border-input hover:bg-accent hover:text-accent-foreground'}"
						onclick={() => settings.setViewMode(opt.value)}
					>
						<div class="text-sm font-medium">{opt.label()}</div>
						<div class="text-xs text-muted-foreground mt-0.5">{opt.desc()}</div>
					</button>
				{/each}
			</div>
		</section>

		<section class="flex flex-col gap-3">
			<h3 class="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
				{m.layers_section_layers()}
			</h3>
			<button
				type="button"
				role="switch"
				aria-checked={settings.showClouds}
				class="text-start rounded-md border p-3 transition-colors cursor-pointer
					{settings.showClouds
					? 'border-primary bg-primary/5'
					: 'border-input hover:bg-accent hover:text-accent-foreground'}"
				onclick={() => settings.setShowClouds(!settings.showClouds)}
			>
				<div class="text-sm font-medium">{m.layers_clouds()}</div>
				<div class="text-xs text-muted-foreground mt-0.5">{m.layers_clouds_desc()}</div>
			</button>
		</section>
	</div>
</div>
