#!/usr/bin/env node

import { createHash, randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const envPath = resolve(root, ".env.local");

function parseEnv(text) {
  const values = new Map();
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (match) values.set(match[1], match[2]);
  }
  return values;
}

function updateEnv(text, updates) {
  const remaining = new Map(Object.entries(updates));
  const lines = text.split(/\r?\n/).map((line) => {
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=/);
    if (!match || !remaining.has(match[1])) return line;
    const value = remaining.get(match[1]);
    remaining.delete(match[1]);
    return `${match[1]}=${value}`;
  });
  for (const [key, value] of remaining) lines.push(`${key}=${value}`);
  return `${lines.filter((line, index) => line || index < lines.length - 1).join("\n").trim()}\n`;
}

function randomSecret(bytes = 32) {
  return randomBytes(bytes).toString("base64url");
}

function keychainAccessCode() {
  const found = spawnSync(
    "security",
    ["find-generic-password", "-s", "com.cortana.web", "-a", "access-code", "-w"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
  );
  return found.status === 0 ? found.stdout.trim() : "";
}

function saveAccessCode(value) {
  const saved = spawnSync(
    "security",
    ["add-generic-password", "-U", "-s", "com.cortana.web", "-a", "access-code", "-w", value],
    { stdio: "ignore" },
  );
  if (saved.status !== 0) throw new Error("Could not save the owner access key in macOS Keychain");
}

function setVercelEnv(name, value) {
  // Preview variables require an attached Git repository in Vercel. This project
  // is deployed through the CLI until the GitHub app is granted repository access.
  for (const environment of ["production", "development"]) {
    const result = spawnSync(
      "vercel",
      ["env", "add", name, environment, "--value", value, "--force", "--yes"],
      { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    );
    if (result.status !== 0) {
      const diagnostic = `${result.stdout}\n${result.stderr}`.trim();
      throw new Error(`Could not configure ${name} for ${environment}: ${diagnostic}`);
    }
  }
}

const currentText = existsSync(envPath) ? readFileSync(envPath, "utf8") : "";
const current = parseEnv(currentText);
const rotateBridge = process.argv.includes("--rotate-bridge");
const accessCode = keychainAccessCode() || randomSecret(24);
const sessionSecret = current.get("CORTANA_SESSION_SECRET") || randomSecret();
const bridgeToken = rotateBridge
  ? randomSecret()
  : current.get("CORTANA_BRIDGE_TOKEN") || randomSecret();
const accessHash = createHash("sha256").update(accessCode).digest("hex");

const updates = {
  OPENAI_MODEL: "gpt-5.5",
  CORTANA_SESSION_SECRET: sessionSecret,
  CORTANA_ACCESS_KEY_HASH: accessHash,
  CORTANA_BRIDGE_URL: "wss://localhost:8765",
  CORTANA_BRIDGE_TOKEN: bridgeToken,
  CORTANA_ALLOWED_ORIGINS: "http://localhost:3000,https://*.vercel.app",
  CORTANA_TLS_CERT: "~/.cortana/certs/localhost.pem",
  CORTANA_TLS_KEY: "~/.cortana/certs/localhost-key.pem",
};

writeFileSync(envPath, updateEnv(currentText, updates), { encoding: "utf8", mode: 0o600 });
chmodSync(envPath, 0o600);
saveAccessCode(accessCode);

setVercelEnv("CORTANA_SESSION_SECRET", sessionSecret);
setVercelEnv("CORTANA_ACCESS_KEY_HASH", accessHash);
setVercelEnv("CORTANA_BRIDGE_URL", updates.CORTANA_BRIDGE_URL);
setVercelEnv("CORTANA_BRIDGE_TOKEN", bridgeToken);

console.log("Configured Cortana web authentication and bridge credentials safely.");
console.log("Owner access key: saved in macOS Keychain as com.cortana.web/access-code.");
console.log("OpenAI API key: remains local and was not uploaded to Vercel.");
