import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDir, "..");
const targetRoot = resolve(projectRoot, "public/cesium");
const requiredFolders = ["Assets", "ThirdParty", "Workers", "Widgets"];
const cesiumCandidates = [
  resolve(projectRoot, "node_modules/cesium/Build/Cesium"),
  resolve(projectRoot, "../node_modules/cesium/Build/Cesium"),
];
const cesiumBuildRoot = cesiumCandidates.find((candidate) => existsSync(candidate)) ?? "";

if (!cesiumBuildRoot) {
  console.warn("[cesium-sync] skip: Cesium build directory not found");
  process.exit(0);
}

rmSync(targetRoot, { recursive: true, force: true });
mkdirSync(targetRoot, { recursive: true });

for (const folderName of requiredFolders) {
  const source = resolve(cesiumBuildRoot, folderName);
  const target = resolve(targetRoot, folderName);
  cpSync(source, target, { recursive: true });
}

console.info("[cesium-sync] synced Cesium static assets to public/cesium");
