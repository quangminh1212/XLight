#!/usr/bin/env node

/**
 * XLight NPM Wrapper
 * ==================
 * Thin Node.js shim that locates Python, installs dependencies,
 * and spawns the XLight application.
 *
 * Usage:
 *   npx xlight          - Launch GUI
 *   npx xlight --cli    - Launch CLI mode
 */

import { spawn, execSync } from "child_process";
import { existsSync, mkdirSync, writeFileSync, readFileSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";
import { createRequire } from "module";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PACKAGE_ROOT = resolve(__dirname, "..");
const PYTHON_DIR = join(PACKAGE_ROOT, "python");

// ── Environment ──
const spawnEnv = {
  ...process.env,
  PYTHONUTF8: "1",
  PYTHONIOENCODING: "utf-8",
};

const IS_WIN = process.platform === "win32";

// ── Python Discovery ──

/**
 * Try running a command and return true if it succeeds.
 */
function commandExists(cmd, args = ["--version"]) {
  try {
    execSync(`${cmd} ${args.join(" ")}`, {
      stdio: "ignore",
      env: spawnEnv,
      shell: IS_WIN,
      timeout: 10000,
    });
    return true;
  } catch {
    return false;
  }
}

/**
 * Return the first working Python executable from candidates.
 */
function findPython() {
  // 1. XLIGHT_PYTHON env override
  const override = process.env.XLIGHT_PYTHON;
  if (override && commandExists(override)) {
    return override;
  }

  // 2. Standard candidates
  const candidates = IS_WIN
    ? ["python", "python3", "py -3"]
    : ["python3", "python"];

  for (const cmd of candidates) {
    if (commandExists(cmd)) {
      // Verify it's Python 3.8+
      try {
        const ver = execSync(`${cmd} -c "import sys; print(sys.version_info[:2])"`, {
          env: spawnEnv,
          shell: IS_WIN,
          timeout: 10000,
          encoding: "utf-8",
        }).trim();
        const match = ver.match(/\((\d+),\s*(\d+)\)/);
        if (match) {
          const [, major, minor] = match.map(Number);
          if (major >= 3 && minor >= 8) {
            return cmd;
          }
        }
      } catch {
        // Skip
      }
    }
  }

  return null;
}

/**
 * Check if Python dependencies are installed.
 */
function checkDeps(python) {
  try {
    execSync(
      `${python} -c "import screen_brightness_control, pystray, PIL"`,
      {
        stdio: "ignore",
        env: spawnEnv,
        shell: IS_WIN,
        timeout: 15000,
      }
    );
    return true;
  } catch {
    return false;
  }
}

/**
 * Install Python dependencies via pip.
 */
function installDeps(python) {
  const reqFile = join(PYTHON_DIR, "requirements.txt");
  if (!existsSync(reqFile)) {
    console.error("[XLight] requirements.txt not found in package.");
    process.exit(1);
  }

  console.log("[XLight] Installing Python dependencies...");
  try {
    execSync(`${python} -m pip install --user -r "${reqFile}"`, {
      stdio: "inherit",
      env: spawnEnv,
      shell: IS_WIN,
      timeout: 120000,
    });
    console.log("[XLight] Dependencies installed successfully.");
  } catch (err) {
    console.error("[XLight] Failed to install dependencies.");
    console.error(
      "[XLight] Try manually: pip install screen_brightness_control pystray Pillow"
    );
    process.exit(1);
  }
}

// ── Main ──

function main() {
  // 1. Find Python
  const python = findPython();
  if (!python) {
    console.error(
      [
        "",
        "╔══════════════════════════════════════════════════════════╗",
        "║  XLight requires Python 3.8+                           ║",
        "║                                                        ║",
        "║  Install from: https://python.org/downloads            ║",
        "║                                                        ║",
        "║  Or set XLIGHT_PYTHON env var to your Python path:     ║",
        "║    set XLIGHT_PYTHON=C:\\Python313\\python.exe           ║",
        "╚══════════════════════════════════════════════════════════╝",
        "",
      ].join("\n")
    );
    process.exit(1);
  }

  // 2. Check & install dependencies
  if (!checkDeps(python)) {
    installDeps(python);
  }

  // 3. Resolve xlight.py path
  const xlightPy = join(PYTHON_DIR, "xlight.py");
  if (!existsSync(xlightPy)) {
    console.error("[XLight] xlight.py not found in package.");
    process.exit(1);
  }

  // 4. Spawn XLight
  const userArgs = process.argv.slice(2);
  const child = spawn(python, [xlightPy, ...userArgs], {
    stdio: "inherit",
    env: spawnEnv,
    shell: IS_WIN,
    cwd: process.cwd(),
  });

  child.on("error", (err) => {
    console.error(`[XLight] Failed to start: ${err.message}`);
    process.exit(1);
  });

  child.on("close", (code) => {
    process.exit(code ?? 0);
  });
}

main();
