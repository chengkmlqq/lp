/**
 * Post-build script: Fix octal escape sequences in webpack chunks
 * 
 * @spz-loader/core embeds WebAssembly binary data as JavaScript strings
 * using \00 (two-digit octal escapes) which are forbidden in strict mode
 * strings. This script converts \00 to \x00 (hex escapes) everywhere.
 * 
 * Run after `npm run build:web` or `next build`.
 */
const fs = require('fs');
const path = require('path');

const CHUNKS_DIR = process.argv[2] || path.join(__dirname, '..', '.next', 'static', 'chunks');

function fixFile(fp) {
  const original = fs.readFileSync(fp, 'utf-8');

  // Quick check: look for literal \00 (backslash followed by two zeros)
  if (!original.includes('\\00')) return false;

  // Replace ALL \00 with \x00 (the chunks are in strict mode, 
  // so octal escapes in ANY string context cause syntax errors)
  const fixed = original.replace(/\\00/g, '\\x00');

  if (fixed !== original) {
    const count = (original.match(/\\00/g) || []).length;
    fs.writeFileSync(fp, fixed, 'utf-8');
    return count;
  }
  return false;
}

function main() {
  if (!fs.existsSync(CHUNKS_DIR)) {
    console.error(`Chunks directory not found: ${CHUNKS_DIR}`);
    process.exit(1);
  }

  let totalFixed = 0;
  const files = fs.readdirSync(CHUNKS_DIR).filter(f => f.endsWith('.js'));

  for (const file of files) {
    const fp = path.join(CHUNKS_DIR, file);
    const result = fixFile(fp);
    if (result !== false) {
      console.log(`Fixed ${file}: ${result} \\00 -> \\x00`);
      totalFixed++;
    }
  }

  if (totalFixed === 0) {
    console.log('No chunks needed patching.');
  } else {
    console.log(`\nPatched ${totalFixed} file(s).`);
  }
}

main();
