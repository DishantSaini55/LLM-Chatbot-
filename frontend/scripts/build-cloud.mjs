import { spawnSync } from "node:child_process";

// Vite embeds this address in the browser bundle at build time. A public site
// pointing at localhost would call each visitor's own computer instead of our API.
const configured = process.env.VITE_API_BASE_URL?.trim();
try {
  const url = new URL(configured ?? "");
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash ||
      /^(localhost|127\.|0\.0\.0\.0|\[::1\])/.test(url.hostname) ||
      url.hostname.endsWith(".invalid")) {
    throw new Error("Invalid public API URL");
  }
} catch {
  console.error("Set VITE_API_BASE_URL to the public HTTPS backend URL before deploying the frontend.");
  process.exit(1);
}

for (const args of [
  ["node_modules/typescript/bin/tsc", "--noEmit"],
  ["node_modules/vite/bin/vite.js", "build"],
]) {
  const result = spawnSync(process.execPath, args, {
    stdio: "inherit",
    env: { ...process.env, VITE_API_BASE_URL: configured },
  });
  if (result.error || result.status !== 0) process.exit(result.status ?? 1);
}
