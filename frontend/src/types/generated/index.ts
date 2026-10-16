/**
 * Canonical API types generated from the backend OpenAPI document.
 *
 * Source of truth: openapi/spec.json (refresh with `npm run fetch:api`,
 * regenerate with `npm run gen:api`). Do not edit api.ts by hand; adopt these
 * types incrementally from hand-written interfaces in src/types/*.ts to
 * remove drift.
 *
 * Examples:
 *   import type { components } from "@/types/generated";
 *   type Task = components["schemas"]["TaskResponse"];
 *   type SceneList = components["schemas"]["SceneListResponse"];
 */
export type { paths, webhooks, components, operations } from "./api";

import type { components as GeneratedComponents } from "./api";

/** Shorthand for a named component schema, e.g. Schema<"TaskResponse">. */
export type Schema<K extends keyof GeneratedComponents["schemas"]> =
  GeneratedComponents["schemas"][K];


/**
 * Backend nullable fields serialise to `T | null`; the frontend convention is
 * optional (`T | undefined`). This normalises one generated component.
 */
export type NullToUndefined<T> = {
  [K in keyof T]: null extends T[K] ? Exclude<T[K], null> | undefined : T[K];
};
