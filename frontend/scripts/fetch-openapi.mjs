/**
 * Pull the live backend OpenAPI document into the checked-in spec snapshot.
 *
 * Usage:
 *   npm run fetch:api                                   # default http://localhost:8000
 *   BACKEND_OPENAPI_URL=http://host:8000/openapi.json npm run fetch:api
 *
 * After refreshing the snapshot, run `npm run gen:api` and commit both files.
 */
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const outPath = resolve(here, "../openapi/spec.json");
const url =
  process.env.BACKEND_OPENAPI_URL ?? "http://localhost:8000/openapi.json";

const res = await fetch(url);
if (!res.ok) {
  console.error(`Failed to fetch ${url}: ${res.status} ${res.statusText}`);
  if (res.status === 404) {
    console.error(
      "Hint: /openapi.json is only served when the backend runs with ENVIRONMENT=development.",
    );
  }
  process.exit(1);
}
const spec = await res.json();
writeFileSync(outPath, JSON.stringify(spec, null, 2) + "\n");
console.log(`OpenAPI snapshot written to openapi/spec.json from ${url}`);
