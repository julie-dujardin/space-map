import { redirect } from '@sveltejs/kit';

export function load() {
	redirect(302, '/body/10/Sun');
}
