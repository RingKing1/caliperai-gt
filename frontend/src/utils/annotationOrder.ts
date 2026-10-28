import type { Annotation, CuboidData } from '@/types';

/**
 * Ordering helpers shared by the annotation list and the keyboard navigation
 * shortcuts, so "next box" means the same thing in both places.
 */

/** Planar distance from the ego vehicle (LiDAR origin is the ego). */
export const distanceToEgo = (annotation: Annotation): number => {
  if (annotation.type !== 'cuboid') return Number.POSITIVE_INFINITY;
  const center = (annotation.data as CuboidData)?.center;
  if (!center) return Number.POSITIVE_INFINITY;
  return Math.hypot(center.x ?? 0, center.y ?? 0);
};

/** Stable ascending order by ego distance; ties fall back to id for determinism. */
export const sortByDistance = (annotations: Annotation[]): Annotation[] =>
  [...annotations].sort((a, b) => {
    const d = distanceToEgo(a) - distanceToEgo(b);
    if (d !== 0) return d;
    return a.id.localeCompare(b.id);
  });

/** Resolve ids to annotations, dropping any id the store does not hold yet. */
export const pickAnnotations = (
  ids: string[],
  annotations: Map<string, Annotation>,
): Annotation[] => {
  const out: Annotation[] = [];
  ids.forEach((id) => {
    const ann = annotations.get(id);
    if (ann) out.push(ann);
  });
  return out;
};
