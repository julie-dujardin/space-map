<!--
  Whether each service behind the site answers. The browser of the reader asks,
  and asks again each minute.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { backends, probe } from '$lib/status/backends';

	const REFRESH_MS = 60_000;
	const EM_DASH = '—';

	const services = backends();
	// A service has no entry before its first answer.
	let up = $state<Record<string, boolean>>({});

	$effect(() => {
		let round = 0;
		// A hidden tab asks nothing, and asks at once when the reader comes back.
		const refresh = () => {
			if (document.hidden) return;
			const asked = ++round;
			for (const service of services) {
				void probe(service).then((ok) => {
					// An answer that a later round overtook is out of date.
					if (asked === round) up[service.id] = ok;
				});
			}
		};
		refresh();
		const timer = setInterval(refresh, REFRESH_MS);
		document.addEventListener('visibilitychange', refresh);
		return () => {
			clearInterval(timer);
			document.removeEventListener('visibilitychange', refresh);
		};
	});
</script>

<section>
	<h2 class="mt-7 mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
		{m.status_section_services()}
	</h2>
	<ul>
		{#each services as service (service.id)}
			{@const ok = up[service.id]}
			<li class="flex items-baseline gap-4 border-b border-border py-2.5">
				<div class="min-w-0 flex-1">{service.label()}</div>
				<div class="shrink-0 text-end">
					{#if ok === undefined}
						<span class="text-muted-subtle">{EM_DASH}</span>
					{:else if ok}
						{m.status_service_up()}
					{:else}
						<span class="text-status-due">
							<span
								class="me-2 inline-block size-1.5 rounded-full bg-status-due align-middle"
								aria-hidden="true"
							></span>{m.status_service_down()}
						</span>
					{/if}
				</div>
			</li>
		{/each}
	</ul>
</section>
