import { copyFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const destination = resolve(root, "frontend/public/data");
await mkdir(destination, { recursive: true });
for (const name of ["businesses.json", "business_database_mapping.json", "activities.json", "metadata.json"]) {
  await copyFile(resolve(root, "backend/data", name), resolve(destination, name));
}
console.log("Static dataset synced to frontend/public/data");
