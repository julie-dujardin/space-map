/** The drawer's members model: the shared members tab (groups list notable
 *  members, bodies list moons), split-comet fragments, mission craft, and the
 *  overview strip each feeds. */

import { STRIP_CAPACITY } from '../members/MemberStrip.svelte';
import { fetchGroupIndex } from '$lib/fetch/groups/registry';
import {
	memberEntryKey,
	type NotableMemberEntry,
	type ObjectDetailData
} from '$lib/fetch/objects/object-data';
import type { GroupDetailData } from '$lib/fetch/groups/details';
import type { AppState } from '$lib/state/app-state.svelte';
import type { CategoryConfig } from '$lib/state/category-config';
import { groupHref, tabHref } from '$lib/state/focus-link';
import { targetVisits, type TargetVisit } from '$lib/probes/target-list';
import * as m from '$lib/paraglide/messages.js';
import { systemTitle } from '../charts/planetary-system.svelte';

/** A planetary system's member is labelled by its primary; the page reads it
 *  as "<primary> system", the name its own page carries. Built over every
 *  entry, since English carries no localized map at all. */
function systemNames(
	members: NotableMemberEntry[] | undefined,
	names: Record<string, string> | undefined,
	cat: CategoryConfig
): Record<string, string> | undefined {
	if (!cat.planetarySystems || !members) return names;
	return Object.fromEntries(
		members.map((mm) => {
			const key = memberEntryKey(mm);
			return [key, systemTitle(key, names?.[key] ?? mm.name)];
		})
	);
}

export interface MembersStateDeps {
	isGroupMode: () => boolean;
	cat: () => CategoryConfig;
	data: () => ObjectDetailData | null;
	groupDetail: () => GroupDetailData | null;
	appState: () => AppState;
}

/** An overview member strip (same card UI, different sources): body
 *  moons/sats, surface features, split-comet fragments, mission craft. Each
 *  model exposes its own; OverviewPanel orders and renders them. */
export interface OverviewStrip {
	members: NotableMemberEntry[];
	localizedNames?: Record<string, string>;
	totalCount: number;
	heading: string;
	seeAllHref?: string;
	onSeeAll: () => void;
	focusMovesCamera?: boolean;
}

export class MembersState {
	// Earth folds its artificial satellites into the moons section: the Moon plus
	// curated featured sats (ISS, Hubble, Starlink), "+N more" → the group page.
	readonly satellitesGroup: string | undefined;
	readonly notableMembers: NotableMemberEntry[] | undefined;
	readonly memberNames: Record<string, string> | undefined;
	readonly memberDescriptions: Record<string, string> | undefined;
	readonly memberTotal: number;
	readonly membersHeading: string;
	readonly membersTabLabel: string;
	readonly showMembersTab: boolean;
	readonly seeAllMembersHref: string | undefined;

	// Split-comet fragments: a strip + tab on the intact parent comet, mirroring
	// moons. `fragmentOf` (the fragment side) drives the breadcrumb + a card.
	readonly notableFragments: NotableMemberEntry[] | undefined;
	readonly fragmentNames: Record<string, string> | undefined;
	readonly fragmentTotal: number;
	readonly fragmentOf: NonNullable<ObjectDetailData['global']>['fragment_of'] | undefined;
	readonly showFragmentsTab: boolean;

	// Probe mission: the mission cross-ref tile lives in SatCrossRefs; the
	// primary craft still shows a strip of its sibling craft.
	readonly missionMembers: NotableMemberEntry[] | undefined;

	// Probes whose events target this body: a strip + tab, mirroring moons.
	readonly probes: NotableMemberEntry[] | undefined;
	readonly probeNames: Record<string, string> | undefined;
	readonly probeTotal: number;
	readonly showProbesTab: boolean;

	// Asteroid/comet SBDB zones (orbit_class), distinct from earth_orbit_class
	// satellite zones; their overview drops the notable-members strip.
	readonly isSmallBodyZone: boolean;

	readonly membersStrip: OverviewStrip | null;
	readonly fragmentsStrip: OverviewStrip | null;
	readonly missionStrip: OverviewStrip | null;
	readonly probesStrip: OverviewStrip | null;
	readonly targetsStrip: OverviewStrip | null;

	// A probe's own destination list, read off its curated events — the body
	// side's probes list mirrored. One derivation feeds the strip, the
	// Targets tab and its badge, so they cannot disagree.
	readonly targetVisits: TargetVisit[];

	// "+N more" matches the Satellites group's categorized member total (group
	// index `n`), not Earth's raw satcat tally, which includes debris.
	#satelliteGroupCount = $state(0);

	readonly seeAllMembers: () => void;

	constructor(d: MembersStateDeps) {
		this.satellitesGroup = $derived(
			d.isGroupMode() ? undefined : d.data()?.global?.satellites_group
		);
		$effect(() => {
			const slug = this.satellitesGroup;
			if (!slug) return;
			fetchGroupIndex().then((idx) => (this.#satelliteGroupCount = idx[slug]?.n ?? 0));
		});
		this.notableMembers = $derived(
			d.isGroupMode()
				? d.groupDetail()?.global?.notable_members
				: this.satellitesGroup
					? [
							...(d.data()?.global?.notable_moons ?? []),
							...(d.data()?.global?.notable_satellites ?? [])
						]
					: d.data()?.global?.notable_moons
		);
		this.memberNames = $derived(
			d.isGroupMode()
				? systemNames(
						d.groupDetail()?.global?.notable_members,
						d.groupDetail()?.localized?.notable_member_names,
						d.cat()
					)
				: this.satellitesGroup
					? {
							...d.data()?.localized?.notable_moon_names,
							...d.data()?.localized?.notable_satellite_names
						}
					: d.data()?.localized?.notable_moon_names
		);
		this.memberDescriptions = $derived(
			d.isGroupMode() ? d.groupDetail()?.localized?.notable_member_descriptions : undefined
		);
		this.memberTotal = $derived(
			d.isGroupMode()
				? (d.groupDetail()?.global?.member_count ?? 0)
				: (d.data()?.global?.moon_count ?? 0) +
						(this.satellitesGroup ? this.#satelliteGroupCount : 0)
		);
		// A split-comet family group lists fragments; a mission group lists its craft.
		const isSplitCometGroup = $derived(d.groupDetail()?.global?.type === 'split_comet');
		const isMissionGroup = $derived(d.groupDetail()?.global?.type === 'mission');
		this.membersHeading = $derived(
			d.isGroupMode()
				? isSplitCometGroup
					? m.fragments_section()
					: isMissionGroup
						? m.mission_members_section()
						: m.members_notable()
				: this.satellitesGroup
					? m.satellites_section()
					: m.moons_section()
		);
		this.membersTabLabel = $derived(
			d.isGroupMode()
				? isSplitCometGroup
					? m.tab_fragments()
					: isMissionGroup
						? m.mission_members_section()
						: d.cat().moons
							? m.tab_moons()
							: m.tab_members()
				: m.tab_moons()
		);
		const hasMembers = $derived(!!this.notableMembers && this.notableMembers.length > 0);
		// Tab only earns its place past the overview strip's capacity; ≤5 fit there.
		// Earth's Satellites strip sends "+N more" to the group, so no in-drawer tab.
		// Planet/dwarf lineups are their own complete member list, so they need none.
		this.showMembersTab = $derived(
			hasMembers &&
				!this.satellitesGroup &&
				this.memberTotal > STRIP_CAPACITY &&
				!d.cat().membersShownInFull
		);
		// Earth's satellites live on their own collection page rather than a tab here.
		this.seeAllMembersHref = $derived(
			this.satellitesGroup
				? groupHref(d.appState(), this.satellitesGroup, this.membersHeading)
				: tabHref(d.appState(), 'members')
		);
		this.seeAllMembers = () => {
			if (this.satellitesGroup) d.appState()?.setGroup(this.satellitesGroup, this.membersHeading);
			else d.appState().setTab('members');
		};

		this.notableFragments = $derived(d.isGroupMode() ? undefined : d.data()?.global?.fragments);
		this.fragmentNames = $derived(d.data()?.localized?.fragment_names);
		this.fragmentTotal = $derived(d.data()?.global?.fragment_count ?? 0);
		this.fragmentOf = $derived(d.isGroupMode() ? undefined : d.data()?.global?.fragment_of);
		const hasFragments = $derived(!!this.notableFragments && this.notableFragments.length > 0);
		this.showFragmentsTab = $derived(hasFragments && this.fragmentTotal > STRIP_CAPACITY);

		this.missionMembers = $derived(d.isGroupMode() ? undefined : d.data()?.global?.mission_members);
		const missionMemberNames = $derived(d.data()?.localized?.mission_member_names);
		const missionMemberTotal = $derived(d.data()?.global?.mission_member_count ?? 0);
		const hasMissionMembers = $derived(!!this.missionMembers && this.missionMembers.length > 0);
		const seeAllMissionMembersHref = $derived.by(() => {
			const link = d.data()?.global?.mission;
			return link ? groupHref(d.appState(), link.primary_id, link.name) : undefined;
		});
		const seeAllMissionMembers = () => {
			const link = d.data()?.global?.mission;
			if (link) d.appState()?.setGroup(link.primary_id, link.name);
		};

		this.probes = $derived(d.isGroupMode() ? undefined : d.data()?.global?.probes);
		this.probeNames = $derived(d.data()?.localized?.probe_names);
		this.probeTotal = $derived(d.data()?.global?.probe_count ?? 0);
		const hasProbes = $derived(!!this.probes && this.probes.length > 0);
		// Present from the first probe: the tab carries the exploration blurb the strip doesn't.
		this.showProbesTab = $derived(hasProbes);

		this.isSmallBodyZone = $derived(d.groupDetail()?.global?.type === 'orbit_class');

		// Lineup/small-body/Solar-System/ring/system pages route members through their own
		// hero or tiles, so they drop the plain members strip.
		this.membersStrip = $derived.by(() => {
			const cat = d.cat();
			if (
				!this.notableMembers?.length ||
				cat.lineup ||
				cat.solarSystem ||
				cat.ringSystems ||
				cat.planetarySystems ||
				// A property collection lists every member below with its own drawing;
				// a strip of photographs above it would be the same bodies said worse.
				cat.property ||
				this.isSmallBodyZone ||
				cat.smallBody
			) {
				return null;
			}
			return {
				members: this.notableMembers,
				localizedNames: this.memberNames,
				totalCount: this.memberTotal,
				heading: this.membersHeading,
				seeAllHref: this.seeAllMembersHref,
				onSeeAll: this.seeAllMembers
			};
		});
		this.fragmentsStrip = $derived.by(() => {
			if (!hasFragments || !this.notableFragments) return null;
			return {
				members: this.notableFragments,
				localizedNames: this.fragmentNames,
				totalCount: this.fragmentTotal,
				heading: m.fragments_section(),
				seeAllHref: tabHref(d.appState(), 'fragments'),
				onSeeAll: () => d.appState().setTab('fragments'),
				focusMovesCamera: false
			};
		});
		this.missionStrip = $derived.by(() => {
			if (!hasMissionMembers || !this.missionMembers) return null;
			return {
				members: this.missionMembers,
				localizedNames: missionMemberNames,
				totalCount: missionMemberTotal,
				heading: m.mission_members_section(),
				seeAllHref: seeAllMissionMembersHref,
				onSeeAll: seeAllMissionMembers
			};
		});
		this.probesStrip = $derived.by(() => {
			if (!hasProbes || !this.probes) return null;
			return {
				members: this.probes,
				localizedNames: this.probeNames,
				totalCount: this.probeTotal,
				heading: m.probes_section(),
				seeAllHref: tabHref(d.appState(), 'probes'),
				onSeeAll: () => d.appState().setTab('probes')
			};
		});

		this.targetVisits = $derived(
			d.isGroupMode() ? [] : targetVisits(d.data()?.global?.events?.items ?? [])
		);
		this.targetsStrip = $derived.by(() => {
			if (this.targetVisits.length === 0) return null;
			return {
				members: this.targetVisits.map((v) => ({
					name: v.target.name,
					id: v.objectId,
					thumbnail: v.target.thumbnail
				})),
				totalCount: this.targetVisits.length,
				heading: m.tab_targets(),
				seeAllHref: tabHref(d.appState(), 'targets'),
				onSeeAll: () => d.appState().setTab('targets')
			};
		});
	}
}
