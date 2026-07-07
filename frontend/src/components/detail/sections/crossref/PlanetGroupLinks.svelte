<script lang="ts">
	import { CAT_PLANETS, CAT_SOLAR_SYSTEM } from '$lib/fetch/groups/registry';
	import BodyCategoryTile from './BodyCategoryTile.svelte';
</script>

<div class="grid grid-cols-2 gap-2">
	<BodyCategoryTile slug={CAT_PLANETS} />
	<BodyCategoryTile slug={CAT_SOLAR_SYSTEM} />
</div>
