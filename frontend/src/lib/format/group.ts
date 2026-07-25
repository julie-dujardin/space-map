import * as m from '$lib/paraglide/messages.js';
import type { GroupType, OrganizationRole, SatelliteCategory } from '$lib/fetch/groups/registry';

export function groupTypeLabel(type: GroupType): string {
	// Several types share the exact label of an object-detail field/link, so they
	// reuse that single message key rather than a duplicate group_type_* one —
	// one string to translate, no drift between badge and detail row.
	switch (type) {
		case 'constellation':
			return m.group_type_constellation();
		case 'launch_vehicle':
			return m.launch_vehicle();
		case 'organization':
			return m.group_type_organization();
		case 'launch_site':
			return m.launch_site();
		case 'bus':
			return m.group_type_bus();
		case 'country':
			return m.group_label_country();
		case 'orbit_class':
			return m.orbit_class();
		case 'earth_orbit_class':
			return m.group_type_earth_orbit_class();
		case 'small_body_flag':
			return m.group_type_small_body_flag();
		case 'category':
			return m.group_type_category();
		case 'split_comet':
			return m.group_type_split_comet();
		case 'mission':
			return m.mission();
		case 'feature_type':
			return m.group_type_feature_type();
	}
}

/** Plural group-type label, for headers over a list of groups ("Constellations",
 *  "Launch sites"). The numeric count sits in its own column, so these are
 *  invariant plurals — `group_type_*` stays singular for badges/inline use. */
export function groupTypeLabelPlural(type: GroupType): string {
	switch (type) {
		case 'constellation':
			return m.group_type_plural_constellation();
		case 'launch_vehicle':
			return m.group_type_plural_launch_vehicle();
		case 'organization':
			return m.group_type_plural_organization();
		case 'launch_site':
			return m.group_type_plural_launch_site();
		case 'bus':
			return m.group_type_plural_bus();
		case 'country':
			return m.group_type_plural_country();
		case 'orbit_class':
			return m.group_type_plural_orbit_class();
		case 'earth_orbit_class':
			return m.group_type_plural_earth_orbit_class();
		case 'small_body_flag':
			return m.group_type_plural_small_body_flag();
		case 'category':
			return m.group_type_plural_category();
		case 'split_comet':
			return m.group_type_plural_split_comet();
		case 'mission':
			return m.group_type_plural_mission();
		case 'feature_type':
			return m.group_type_plural_feature_type();
	}
}

/** Badge label for an organization's operator/manufacturer role tag. */
export function organizationRoleLabel(role: OrganizationRole): string {
	return role === 'operator' ? m.group_type_operator() : m.group_type_manufacturer();
}

export function satelliteCategoryLabel(cat: SatelliteCategory): string {
	switch (cat) {
		case 'disaster-sar':
			return m.satellite_category_disaster_sar();
		case 'weather':
			return m.satellite_category_weather();
		case 'observation':
			return m.satellite_category_observation();
		case 'communications':
			return m.satellite_category_communications();
		case 'navigation':
			return m.satellite_category_navigation();
		case 'science':
			return m.satellite_category_science();
		case 'military':
			return m.satellite_category_military();
		case 'debris':
			return m.satellite_category_debris();
		case 'station':
			return m.satellite_category_station();
		case 'manned_capsule':
			return m.satellite_category_manned_capsule();
		case 'unmanned_cargo':
			return m.satellite_category_unmanned_cargo();
		case 'space_tug':
			return m.satellite_category_space_tug();
		case 'rocket':
			return m.satellite_category_rocket();
		case 'upper_stage':
			return m.satellite_category_upper_stage();
		case 'miscellaneous':
			return m.satellite_category_miscellaneous();
	}
}
