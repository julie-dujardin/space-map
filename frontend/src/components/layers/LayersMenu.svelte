<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { Switch } from '$lib/components/ui/switch';
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

	const layerToggles: {
		id: string;
		label: () => string;
		desc: () => string;
		checked: () => boolean;
		set: (on: boolean) => void;
	}[] = [
		{
			id: 'clouds',
			label: () => m.layers_clouds(),
			desc: () => m.layers_clouds_desc(),
			checked: () => settings.showClouds,
			set: (on) => settings.setShowClouds(on)
		},
		{
			id: 'atmosphere',
			label: () => m.layers_atmosphere(),
			desc: () => m.layers_atmosphere_desc(),
			checked: () => settings.showAtmospheres,
			set: (on) => settings.setShowAtmospheres(on)
		},
		{
			id: 'high-ambient',
			label: () => m.layers_high_ambient(),
			desc: () => m.layers_high_ambient_desc(),
			checked: () => settings.highAmbient,
			set: (on) => settings.setHighAmbient(on)
		}
	];
</script>

<div class="flex min-h-0 flex-col">
	<header class="px-5 pt-5 pb-3">
		<h2 class="text-base font-semibold">{m.layers_title()}</h2>
	</header>

	<div class="px-5 pb-5 flex min-h-0 flex-col gap-5 overflow-y-auto">
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
			{#each layerToggles as toggle (toggle.id)}
				<label class="flex items-center justify-between gap-3 cursor-pointer">
					<div class="flex flex-col min-w-0">
						<span class="text-sm font-medium">{toggle.label()}</span>
						<span class="text-xs text-muted-foreground">{toggle.desc()}</span>
					</div>
					<Switch checked={toggle.checked()} onCheckedChange={toggle.set} />
				</label>
			{/each}
		</section>
	</div>
</div>
