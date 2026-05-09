import { formatQuantityParts, type QuantityParts } from './quantities';
import { AU_KM } from '$lib/math/units';

type DistanceUnit = 'astronomical_unit' | 'kilometre';

const AU_TO_KM_THRESHOLD = 0.01;

function pickUnit(au: number): DistanceUnit {
	const abs = Math.abs(au);
	return abs > 0 && abs < AU_TO_KM_THRESHOLD ? 'kilometre' : 'astronomical_unit';
}

export function convertDistance(au: number): { value: number; unit: DistanceUnit } {
	const unit = pickUnit(au);
	return { value: unit === 'kilometre' ? au * AU_KM : au, unit };
}

export function formatDistance(au: number): QuantityParts {
	return formatQuantityParts(convertDistance(au));
}
