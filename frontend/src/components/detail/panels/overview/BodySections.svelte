<script lang="ts">
	import Spacecraft from '../../sections/Spacecraft.svelte';
	import Atmosphere from '../../sections/Atmosphere.svelte';
	import Surface from '../../sections/Surface.svelte';
	import Interior from '../../sections/Interior.svelte';
	import Rings from '../../sections/Rings.svelte';
	import Orbital from '../../sections/Orbital.svelte';
	import Discovery from '../../sections/Discovery.svelte';
	import Mission from '../../sections/Mission.svelte';
	import type { OrbitalElements, PositionedBody } from '$lib/types/objects';
	import type { ObjectDetailData } from '$lib/fetch/objects/object-data';

	interface Props {
		body: PositionedBody;
		data: ObjectDetailData | null;
		orbitElements: OrbitalElements | undefined;
		parentBody: PositionedBody | undefined;
		jd: number;
	}

	let { body, data, orbitElements, parentBody, jd }: Props = $props();
</script>

<Spacecraft global={data?.global ?? null} />
<Atmosphere global={data?.global ?? null} />
<Surface global={data?.global ?? null} />
<Interior global={data?.global ?? null} />
<Rings global={data?.global ?? null} {body} />
<Orbital
	global={data?.global ?? null}
	localized={data?.localized ?? null}
	{body}
	{orbitElements}
	{parentBody}
	{jd}
/>
<Discovery global={data?.global ?? null} localized={data?.localized ?? null} />
<Mission global={data?.global ?? null} localized={data?.localized ?? null} />
