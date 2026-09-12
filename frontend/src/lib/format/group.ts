import * as m from '$lib/paraglide/messages.js';
import {
	CAT_ASTEROIDS,
	CAT_ATMOSPHERES,
	CAT_COMETS,
	CAT_DEBRIS,
	CAT_DWARF_PLANETS,
	CAT_MAGNETIC_FIELDS,
	CAT_MOONS,
	CAT_OCEANS,
	CAT_PLANETS,
	CAT_PROBES,
	CAT_RADIATION,
	CAT_RING_SYSTEMS,
	CAT_SATELLITES,
	CAT_SATELLITE_SYSTEMS,
	CAT_SOLAR_SYSTEM,
	CAT_STRUCTURE_ACTIVITY,
	CAT_SURFACE_FEATURES,
	CAT_TECTONICS,
	CAT_TIDAL_HEATING,
	CAT_VOLCANISM,
	type GroupType,
	type OrganizationRole,
	type SatelliteCategory
} from '$lib/fetch/groups/registry';

/** Singular and plural label per group type. `one` sometimes points at an
 *  object-detail field/link key instead of a `group_type_*` one, so badge and
 *  detail row cannot drift apart. The count sits in its own column, so `many`
 *  is an invariant plural. */
const GROUP_TYPE_NAME: Record<GroupType, { one: () => string; many: () => string }> = {
	constellation: { one: m.group_type_constellation, many: m.group_type_plural_constellation },
	launch_vehicle: { one: m.launch_vehicle, many: m.group_type_plural_launch_vehicle },
	organization: { one: m.group_type_organization, many: m.group_type_plural_organization },
	launch_site: { one: m.launch_site, many: m.group_type_plural_launch_site },
	bus: { one: m.group_type_bus, many: m.group_type_plural_bus },
	country: { one: m.group_label_country, many: m.group_type_plural_country },
	orbit_class: { one: m.orbit_class, many: m.group_type_plural_orbit_class },
	earth_orbit_class: {
		one: m.group_type_earth_orbit_class,
		many: m.group_type_plural_earth_orbit_class
	},
	small_body_flag: { one: m.group_type_small_body_flag, many: m.group_type_plural_small_body_flag },
	category: { one: m.group_type_category, many: m.group_type_plural_category },
	split_comet: { one: m.group_type_split_comet, many: m.group_type_plural_split_comet },
	mission: { one: m.mission, many: m.group_type_plural_mission },
	feature_type: { one: m.group_type_feature_type, many: m.group_type_plural_feature_type }
};

export function groupTypeLabel(type: GroupType): string {
	return GROUP_TYPE_NAME[type].one();
}

/** For headers over a list of groups ("Constellations", "Launch sites"). */
export function groupTypeLabelPlural(type: GroupType): string {
	return GROUP_TYPE_NAME[type].many();
}

/** Badge label for an organization's operator/manufacturer role tag. */
export function organizationRoleLabel(role: OrganizationRole): string {
	return role === 'operator' ? m.group_type_operator() : m.group_type_manufacturer();
}

/** Group-badge wording, shorter than the `category_*` object-chip namespace. */
const SATELLITE_CATEGORY_NAME: Record<SatelliteCategory, () => string> = {
	'disaster-sar': m.satellite_category_disaster_sar,
	weather: m.satellite_category_weather,
	observation: m.satellite_category_observation,
	communications: m.satellite_category_communications,
	navigation: m.satellite_category_navigation,
	science: m.satellite_category_science,
	military: m.satellite_category_military,
	debris: m.satellite_category_debris,
	station: m.satellite_category_station,
	manned_capsule: m.satellite_category_manned_capsule,
	unmanned_cargo: m.satellite_category_unmanned_cargo,
	space_tug: m.satellite_category_space_tug,
	rocket: m.satellite_category_rocket,
	upper_stage: m.satellite_category_upper_stage,
	miscellaneous: m.satellite_category_miscellaneous
};

export function satelliteCategoryLabel(cat: SatelliteCategory): string {
	return SATELLITE_CATEGORY_NAME[cat]();
}

/** Plural category headers, not the singular Wikidata label. */
const CATEGORY_NAME: Record<string, () => string> = {
	[CAT_SOLAR_SYSTEM]: m.category_name_solar_system,
	[CAT_SATELLITE_SYSTEMS]: m.category_name_satellite_systems,
	[CAT_PLANETS]: m.category_name_planets,
	[CAT_DWARF_PLANETS]: m.category_name_dwarf_planets,
	[CAT_MOONS]: m.category_name_moons,
	[CAT_RING_SYSTEMS]: m.category_name_ring_systems,
	[CAT_ASTEROIDS]: m.category_name_asteroids,
	[CAT_COMETS]: m.category_name_comets,
	[CAT_SATELLITES]: m.category_name_satellites,
	[CAT_DEBRIS]: m.category_name_debris,
	[CAT_PROBES]: m.category_name_probes,
	[CAT_SURFACE_FEATURES]: m.category_name_surface_features,
	[CAT_STRUCTURE_ACTIVITY]: m.category_name_structure_activity,
	[CAT_ATMOSPHERES]: m.category_name_atmospheres,
	[CAT_OCEANS]: m.category_name_oceans,
	[CAT_VOLCANISM]: m.category_name_volcanism,
	[CAT_TECTONICS]: m.category_name_tectonics,
	[CAT_MAGNETIC_FIELDS]: m.category_name_magnetic_fields,
	[CAT_TIDAL_HEATING]: m.category_name_tidal_heating,
	[CAT_RADIATION]: m.category_name_radiation
};

/** Localized display name for a `cat-` slug; the raw slug if unknown. */
export function categoryLabel(slug: string): string {
	return CATEGORY_NAME[slug]?.() ?? slug;
}
