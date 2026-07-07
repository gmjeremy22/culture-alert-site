#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const DEFAULT_INPUT = path.resolve(
  __dirname,
  "..",
  "..",
  "culture-alert",
  "outputs",
  "keyword-recommendation-report.html"
);
const DEFAULT_OUTPUT = path.resolve(__dirname, "..", "public", "index.html");

function readArg(name) {
  const index = process.argv.indexOf(name);
  if (index === -1) return "";
  return process.argv[index + 1] || "";
}

function toBase64(buffer) {
  return Buffer.from(buffer).toString("base64");
}

function fail(message) {
  console.error(message);
  process.exit(1);
}

function htmlEscapeForScript(value) {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

function renderPage(payload) {
  const payloadJson = htmlEscapeForScript(JSON.stringify(payload));
  return `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>수도권 문화 일정 리포트</title>
  <style>
    :root {
      color-scheme: dark;
      --paper: #080808;
      --panel: #121212;
      --ink: #f7f4ee;
      --muted: #a7a096;
      --line: rgba(247, 244, 238, 0.17);
      --accent: #f0dfc2;
      --accent-ink: #15120e;
      --danger: #ffb1a4;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: var(--paper);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }
    main {
      width: min(520px, calc(100% - 40px));
      padding: 30px;
      border: 1px solid var(--line);
      background: var(--panel);
      box-shadow: 0 26px 70px rgba(0, 0, 0, 0.42);
    }
    h1 {
      margin: 0 0 10px;
      font-size: 25px;
      letter-spacing: 0;
    }
    p {
      margin: 0;
      color: var(--muted);
    }
    form {
      display: grid;
      gap: 12px;
      margin-top: 24px;
    }
    label {
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
    }
    input {
      width: 100%;
      min-height: 46px;
      padding: 0 13px;
      border: 1px solid var(--line);
      background: #050505;
      color: var(--ink);
      font: inherit;
    }
    button {
      min-height: 46px;
      border: 0;
      background: var(--accent);
      color: var(--accent-ink);
      font: inherit;
      font-weight: 800;
      cursor: pointer;
    }
    button:disabled {
      cursor: progress;
      opacity: 0.7;
    }
    .meta {
      margin-top: 16px;
      font-size: 13px;
      color: #827b72;
    }
    .error {
      min-height: 22px;
      color: var(--danger);
      font-size: 14px;
    }
  </style>
</head>
<body>
  <main>
    <h1>수도권 문화 일정 리포트</h1>
    <p>비밀번호를 입력하면 최신 카드 리포트를 이 브라우저 안에서 복호화합니다.</p>
    <form id="unlockForm">
      <label for="password">비밀번호</label>
      <input id="password" type="password" autocomplete="current-password" required autofocus>
      <button id="unlockButton" type="submit">열기</button>
      <div class="error" id="error" role="alert"></div>
    </form>
    <p class="meta">생성 시각: ${payload.createdAt}</p>
  </main>
  <script type="application/json" id="encryptedPayload">${payloadJson}</script>
  <script>
    const payload = JSON.parse(JSON.parse(document.getElementById("encryptedPayload").textContent));
    const form = document.getElementById("unlockForm");
    const passwordInput = document.getElementById("password");
    const button = document.getElementById("unlockButton");
    const errorBox = document.getElementById("error");

    function bytesFromBase64(value) {
      const binary = atob(value);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
      }
      return bytes;
    }

    function joinBytes(left, right) {
      const joined = new Uint8Array(left.length + right.length);
      joined.set(left, 0);
      joined.set(right, left.length);
      return joined;
    }

    async function decryptReport(password) {
      const encoder = new TextEncoder();
      const material = await crypto.subtle.importKey(
        "raw",
        encoder.encode(password),
        "PBKDF2",
        false,
        ["deriveKey"]
      );
      const key = await crypto.subtle.deriveKey(
        {
          name: "PBKDF2",
          salt: bytesFromBase64(payload.salt),
          iterations: payload.iterations,
          hash: "SHA-256"
        },
        material,
        { name: "AES-GCM", length: 256 },
        false,
        ["decrypt"]
      );
      const ciphertext = bytesFromBase64(payload.ciphertext);
      const tag = bytesFromBase64(payload.tag);
      const combined = joinBytes(ciphertext, tag);
      const plain = await crypto.subtle.decrypt(
        { name: "AES-GCM", iv: bytesFromBase64(payload.iv), tagLength: 128 },
        key,
        combined
      );
      return new TextDecoder().decode(plain);
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      errorBox.textContent = "";
      button.disabled = true;
      button.textContent = "여는 중";
      try {
        const html = await decryptReport(passwordInput.value);
        document.open();
        document.write(html);
        document.close();
      } catch (error) {
        errorBox.textContent = "비밀번호가 맞지 않거나 리포트를 열 수 없습니다.";
        button.disabled = false;
        button.textContent = "열기";
        passwordInput.select();
      }
    });
  </script>
</body>
</html>
`;
}

function main() {
  const inputPath = path.resolve(
    readArg("--input") ||
      process.env.CULTURE_ALERT_SOURCE_HTML ||
      DEFAULT_INPUT
  );
  const outputPath = path.resolve(readArg("--output") || DEFAULT_OUTPUT);
  const password = process.env.CULTURE_ALERT_SITE_PASSWORD || "";
  const iterations = Number(process.env.CULTURE_ALERT_KDF_ITERATIONS || 310000);

  if (!password) {
    fail("CULTURE_ALERT_SITE_PASSWORD 환경변수에 게시 비밀번호를 넣어주세요.");
  }
  if (!fs.existsSync(inputPath)) {
    fail(`원본 HTML을 찾을 수 없습니다: ${inputPath}`);
  }
  if (!Number.isInteger(iterations) || iterations < 100000) {
    fail("CULTURE_ALERT_KDF_ITERATIONS 값은 100000 이상의 정수여야 합니다.");
  }

  const sourceHtml = fs.readFileSync(inputPath, "utf8");
  const salt = crypto.randomBytes(16);
  const iv = crypto.randomBytes(12);
  const key = crypto.pbkdf2Sync(password, salt, iterations, 32, "sha256");
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ciphertext = Buffer.concat([
    cipher.update(sourceHtml, "utf8"),
    cipher.final(),
  ]);
  const tag = cipher.getAuthTag();

  const payload = {
    version: 1,
    algorithm: "AES-256-GCM",
    kdf: "PBKDF2",
    hash: "SHA-256",
    iterations,
    salt: toBase64(salt),
    iv: toBase64(iv),
    tag: toBase64(tag),
    ciphertext: toBase64(ciphertext),
    createdAt: new Date().toISOString(),
    sourceName: path.basename(inputPath),
  };

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, renderPage(payload), "utf8");
  console.log(`protected_site=${outputPath}`);
  console.log(`source=${inputPath}`);
}

main();

