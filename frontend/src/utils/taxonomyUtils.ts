
import type {
  ClassDefinition,
  AttributeDefinition,
  SharedAttributeDefinition,
  TaxonomyConfig,
  Taxonomy
} from '@/types';

// Raw API payloads (e.g. nested DatasetResponse.taxonomy) carry nullable
// fields; normalize them to the frontend's undefined-based convention.
type RawSharedAttribute = {
  name: string;
  type: SharedAttributeDefinition['type'];
  default?: unknown;
  options?: string[] | null;
  required?: boolean | null;
  description?: string | null;
  mutable?: boolean | null;
  applies_to?: string[] | null;
};

export function normalizeSharedAttributes(
  attrs?: RawSharedAttribute[] | null,
): SharedAttributeDefinition[] {
  return (attrs ?? []).map((attr) => ({
    name: attr.name,
    type: attr.type,
    default: attr.default ?? undefined,
    options: attr.options ?? undefined,
    required: attr.required ?? false,
    description: attr.description ?? undefined,
    mutable: attr.mutable ?? true,
    applies_to: attr.applies_to ?? [],
  }));
}

type RawSkeleton = {
  bones?: string[][] | null;
  keypoints?: Array<{ id: string; name: string; color?: string | null }> | null;
};

type RawAttribute = {
  type: AttributeDefinition['type'];
  default?: unknown;
  options?: string[] | null;
  required?: boolean | null;
  description?: string | null;
  mutable?: boolean | null;
};

type RawClass = {
  id: string;
  name: string;
  color: string;
  type: ClassDefinition['type'];
  attributes?: Record<string, RawAttribute> | null;
  skeleton?: string | null;
  description?: string | null;
  default_dimensions?: number[] | null;
  single_click_placement?: boolean | null;
  instance_prefix?: string | null;
};

// Coerce a raw (nested, nullable) API taxonomy config into the frontend's
// TaxonomyConfig convention (null -> undefined, tuple bones).
export function normalizeTaxonomyConfig(raw: {
  classes: RawClass[];
  skeletons?: Record<string, RawSkeleton> | null;
  annotation_rules?: TaxonomyConfig['annotation_rules'] | null;
  shared_attributes?: RawSharedAttribute[] | null;
}): TaxonomyConfig {
  const skeletons: Record<string, TaxonomyConfig['skeletons'][string]> = {};
  for (const [id, skeleton] of Object.entries(raw.skeletons ?? {})) {
    skeletons[id] = {
      bones: (skeleton.bones ?? []) as [string, string][],
      keypoints: (skeleton.keypoints ?? []).map((kp) => ({
        id: kp.id,
        name: kp.name,
        ...(kp.color != null ? { color: kp.color } : {}),
      })),
    };
  }
  return {
    classes: raw.classes.map((cls) => {
      const attributes: ClassDefinition['attributes'] = {};
      for (const [name, attr] of Object.entries(cls.attributes ?? {})) {
        attributes[name] = {
          type: attr.type,
          default: attr.default ?? undefined,
          options: attr.options ?? undefined,
          required: attr.required ?? false,
          description: attr.description ?? undefined,
          mutable: attr.mutable ?? true,
        };
      }
      const normalized: ClassDefinition = {
        id: cls.id,
        name: cls.name,
        color: cls.color,
        type: cls.type,
        attributes,
      };
      if (cls.skeleton != null) normalized.skeleton = cls.skeleton;
      if (cls.description != null) normalized.description = cls.description;
      if (cls.default_dimensions) {
        normalized.default_dimensions = cls.default_dimensions as [number, number, number];
      }
      if (cls.single_click_placement != null) {
        normalized.single_click_placement = cls.single_click_placement;
      }
      if (cls.instance_prefix != null) normalized.instance_prefix = cls.instance_prefix;
      return normalized;
    }),
    skeletons,
    annotation_rules: raw.annotation_rules ?? {
      min_points_polyline: 2,
      min_points_polygon: 3,
      allow_overlapping_boxes: false,
      require_track_id: false,
    },
    shared_attributes: normalizeSharedAttributes(raw.shared_attributes),
  };
}

export function getEffectiveAttributesForClass(
  classId: string,
  taxonomy: TaxonomyConfig | Taxonomy | null
): Record<string, AttributeDefinition> {
  if (!taxonomy) return {};

  const classDef = taxonomy.classes.find(c => c.id === classId);
  if (!classDef) return {};

  const result: Record<string, AttributeDefinition> = {};

  const sharedAttrs = taxonomy.shared_attributes || [];
  for (const sharedAttr of sharedAttrs) {
    const appliesTo = sharedAttr.applies_to || [];
    const appliesToAll = appliesTo.length === 0 || appliesTo.includes('__all__');
    const appliesToThisClass = appliesToAll || appliesTo.includes(classId);

    if (appliesToThisClass) {
      result[sharedAttr.name] = {
        type: sharedAttr.type,
        default: sharedAttr.default,
        options: sharedAttr.options,
        required: sharedAttr.required,
        description: sharedAttr.description,
        mutable: sharedAttr.mutable,
      };
    }
  }

  if (classDef.attributes) {
    for (const [key, attr] of Object.entries(classDef.attributes)) {
      result[key] = attr;
    }
  }

  return result;
}

export function getEnhancedClassDefinition(
  classId: string,
  taxonomy: TaxonomyConfig | Taxonomy | null
): ClassDefinition | undefined {
  if (!taxonomy) return undefined;

  const classDef = taxonomy.classes.find(c => c.id === classId);
  if (!classDef) return undefined;

  return {
    ...classDef,
    attributes: getEffectiveAttributesForClass(classId, taxonomy),
  };
}

export function sharedAttributeAppliesToClass(
  sharedAttr: SharedAttributeDefinition,
  classId: string
): boolean {
  const appliesTo = sharedAttr.applies_to || [];
  if (appliesTo.length === 0 || appliesTo.includes('__all__')) {
    return true;
  }
  return appliesTo.includes(classId);
}

export function getClassesForSharedAttribute(
  sharedAttr: SharedAttributeDefinition,
  taxonomy: TaxonomyConfig | Taxonomy | null
): string[] {
  if (!taxonomy) return [];

  const appliesTo = sharedAttr.applies_to || [];
  if (appliesTo.length === 0 || appliesTo.includes('__all__')) {
    return taxonomy.classes.map(c => c.id);
  }
  return appliesTo;
}
