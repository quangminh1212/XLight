/**
 * Build script for XLight NPM package.
 * Copies Python source files into npm/python/ directory.
 *
 * Usage: node scripts/build-npm.js
 */

import { copyFileSync, mkdirSync, existsSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = resolve(__dirname, "..");
const NPM_DIR = join(ROOT, "npm");
const PYTHON_DIR = join(NPM_DIR, "python");

// Ensure python/ dir exists
mkdirSync(PYTHON_DIR, { recursive: true });

// Files to copy
const files = [
  { src: "xlight.py", dest: "xlight.py" },
  { src: "requirements.txt", dest: "requirements.txt" },
];

let copied = 0;
for (const f of files) {
  const srcPath = join(ROOT, f.src);
  const destPath = join(PYTHON_DIR, f.dest);
  if (existsSync(srcPath)) {
    copyFileSync(srcPath, destPath);
    console.log(`  ✓ ${f.src} → npm/python/${f.dest}`);
    copied++;
  } else {
    console.error(`  ✗ Missing: ${f.src}`);
  }
}

// Copy README and LICENSE to npm/
for (const file of ["README.md", "LICENSE"]) {
  const srcPath = join(ROOT, file);
  const destPath = join(NPM_DIR, file);
  if (existsSync(srcPath)) {
    copyFileSync(srcPath, destPath);
    console.log(`  ✓ ${file} → npm/${file}`);
    copied++;
  }
}

console.log(`\n✅ Build complete: ${copied} files copied to npm/`);
console.log(`\nNext steps:`);
console.log(`  cd npm`);
console.log(`  npm publish`);
