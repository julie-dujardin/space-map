<script lang="ts">
	// The system map in the site's own colours; the chart itself is the core's.
	import type { Attachment } from 'svelte/attachments';
	import { SystemMapChart } from '$lib/systemmap/chart';
	import type { SystemMapModel } from '$lib/systemmap/model';

	interface Props {
		model: SystemMapModel;
		ariaLabel: string;
		/** 'background' strips axis/labels/links/tooltips and fills+crops its box —
		 *  a static decorative diagram behind a cross-ref tile. */
		variant?: 'hero' | 'background';
	}
	let { model, ariaLabel, variant = 'hero' }: Props = $props();

	const chart: Attachment<HTMLElement> = (node) => {
		const made = new SystemMapChart();
		node.append(made.root);
		// Its own effect, so a new model redraws the chart rather than rebuilding it.
		$effect(() => made.update(model, { ariaLabel, variant }));
		return () => made.destroy();
	};
</script>

<div class="system-map contents" {@attach chart}></div>

<style>
	.system-map {
		--sm-system-map-radius: var(--radius-md);
		--sm-system-map-background: color-mix(in oklab, var(--muted) 30%, transparent);
		--sm-system-map-ink: var(--muted-foreground);
		--sm-system-map-tip-background: color-mix(in oklab, var(--background) 90%, transparent);
		--sm-system-map-tip-ink: var(--foreground);
	}
</style>
