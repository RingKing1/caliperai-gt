/**
 * Drift gate: regenerate TS types from the checked-in OpenAPI snapshot into a
 * temp file and fail if the committed src/types/generated/api.ts differs.
 *
 * Usage: npm run check:api
 */
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const committed = resolve(root, "src/types/generated/api.ts");
const temp = resolve(root, "src/types/generated/.api.check.ts");

try {
  const bin = resolve(root, "node_modules/.bin/openapi-typescript");
  execFileSync(
    bin,
    [resolve(root, "openapi/spec.json"), "-o", temp],
    { cwd: root, stdio: "inherit" },
  );
  if (readFileSync(temp, "utf8") !== readFileSync(committed, "utf8")) {
    console.error(
      "Generated API types are out of date. Run `npm run gen:api` and commit the result.",
    );
    process.exit(1);
  }
  console.log("Generated API types are up to date.");
} finally {
  rmSync(temp, { force: true });
}
