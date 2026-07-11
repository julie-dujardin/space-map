<script lang="ts">
	import { announcements } from './announcer.svelte';
</script>

<!-- Shared visually-hidden live regions. aria-atomic so the whole message is
     read even when only part of it changes. -->
<div class="sr-only" role="status" aria-live="polite" aria-atomic="true">
	{announcements.polite}
</div>
<div class="sr-only" role="alert" aria-live="assertive" aria-atomic="true">
	{announcements.assertive}
</div>
