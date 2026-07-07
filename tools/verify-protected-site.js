#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

function readArg(name, fallback = "") {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  return process.argv[index + 1] || fallback;
}

function readRepeatedArg(name) {
  const values = [];
  for (let index = 0; index < process.argv.length; index += 1) {
    if (process.argv[index] === name && process.argv[index + 1]) {
      values.push(process.argv[index + 1]);
      index += 1;
    }
  }
  return values;
}

function fail(message) {
  console.error(message);
  process.exit(1);
}

function extractPayload(html) {
  const markerStart = '<script type="application/json" id="encryptedPayload">';
  const markerEnd = "</script>";
  const start = html.indexOf(markerStart);
  if (start < 0) fail("encrypted payload marker not found");
  const end = html.indexOf(markerEnd, start);
  if (end < 0) fail("encrypted payload end marker not found");
  return JSON.parse(JSON.parse(html.slice(start + markerStart.length, end)));
}

function decryptPayload(payload, password) {
  const key = crypto.pbkdf2Sync(
    password,
    Buffer.from(payload.salt, "base64"),
    payload.iterations,
    32,
    "sha256"
  );
  const decipher = crypto.createDecipheriv(
    "aes-256-gcm",
    key,
    Buffer.from(payload.iv, "base64")
  );
  decipher.setAuthTag(Buffer.from(payload.tag, "base64"));
  return Buffer.concat([
    decipher.update(Buffer.from(payload.ciphertext, "base64")),
    decipher.final(),
  ]).toString("utf8");
}

function main() {
  const htmlPath = path.resolve(readArg("--html", "public/index.html"));
  const password = process.env.CULTURE_ALERT_SITE_PASSWORD || readArg("--password");
  const leakMarkers = readRepeatedArg("--leak");

  if (!fs.existsSync(htmlPath)) fail(`html not found: ${htmlPath}`);
  if (!password) fail("CULTURE_ALERT_SITE_PASSWORD or --password is required");

  const html = fs.readFileSync(htmlPath, "utf8");
  for (const marker of leakMarkers) {
    if (html.includes(marker)) {
      fail(`plaintext leak marker found in encrypted page: ${marker}`);
    }
  }

  const payload = extractPayload(html);
  const plain = decryptPayload(payload, password);
  const expectedMarkers = ["detailOverlay", "keywordChoices", "feature-card"];
  const missing = expectedMarkers.filter((marker) => !plain.includes(marker));
  if (missing.length) {
    fail(`decrypted report missing expected markers: ${missing.join(", ")}`);
  }
  console.log(`verified=${htmlPath}`);
  console.log(`decrypted_length=${plain.length}`);
  console.log(`leak_markers_checked=${leakMarkers.length}`);
}

main();

