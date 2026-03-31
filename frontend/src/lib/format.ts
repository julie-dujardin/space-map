import { isAsteroid, ObjectType } from './types/objects';

/** Map ObjectType to URL type prefix. */
export function urlType(type: ObjectType): string {
	if (type === ObjectType.SPACECRAFT) return 'probe'; // TODO
	if (type === ObjectType.DEBRIS) return 'sat'; // TODO
	if (isAsteroid(type) || type === ObjectType.COMET) return 'sb';
	return 'body';
}
