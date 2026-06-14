import * as m from '$lib/paraglide/messages.js';
import type { GroupType, SatelliteCategory } from '$lib/fetch/groups/registry';

export function groupTypeLabel(type: GroupType): string {
	switch (type) {
		case 'constellation':
			return m.group_type_constellation();
		case 'operator':
			return m.group_type_operator();
		case 'launch_site':
			return m.group_type_launch_site();
		case 'manufacturer':
			return m.group_type_manufacturer();
		case 'bus':
			return m.group_type_bus();
		case 'country':
			return m.group_type_country();
		case 'orbit_class':
		case 'earth_orbit_class':
			return m.group_type_orbit_class();
		case 'small_body_flag':
			return m.group_type_small_body_flag();
		case 'category':
			return m.group_type_category();
		case 'split_comet':
			return m.group_type_split_comet();
	}
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
