<script lang="ts">
	import LayersIcon from '@lucide/svelte/icons/layers';
	import * as m from '$lib/paraglide/messages.js';
	import { Switch } from '$lib/components/ui/switch';
	import OverlayMenuButton from '../OverlayMenuButton.svelte';

	interface Props {
		angleGrid: boolean;
		navigation: boolean;
		onAngleGridChange: (visible: boolean) => void;
		onNavigationChange: (visible: boolean) => void;
	}

	let { angleGrid, navigation, onAngleGridChange, onNavigationChange }: Props = $props();
</script>

<OverlayMenuButton title={m.layers_title()} Icon={LayersIcon}>
	<div class="flex flex-col">
		<header class="px-5 pt-5 pb-3">
			<h2 class="text-base font-semibold">{m.layers_title()}</h2>
		</header>

		<div class="flex flex-col gap-4 px-5 pb-5">
			<label class="flex cursor-pointer items-center justify-between gap-3">
				<span class="text-sm font-medium">{m.layer_graticule()}</span>
				<Switch checked={angleGrid} onCheckedChange={onAngleGridChange} />
			</label>
			<label class="flex cursor-pointer items-center justify-between gap-3">
				<span class="flex min-w-0 flex-col">
					<span class="text-sm font-medium">{m.panorama_navigation_arrows()}</span>
					<span class="text-xs text-muted-foreground">
						{m.panorama_previous()} · {m.panorama_next()}
					</span>
				</span>
				<Switch checked={navigation} onCheckedChange={onNavigationChange} />
			</label>
		</div>
	</div>
</OverlayMenuButton>
