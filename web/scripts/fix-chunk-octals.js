/**
 * Post-build script: Fix octal escape sequences in webpack chunks
 * 
 * @spz-loader/core embeds WebAssembly binary data as JavaScript template literals
 * using \00 (two-digit octal escapes) which are forbidden in template literals
 * since ES2018. This script converts \00 to \x00 (hex escapes) only inside
 * template literals.
 * 
 * Run after `npm run build:web` or `next build`.
 */
const fs = require('fs');
const path = require('path');

// Accept chunks dir as CLI arg, or default to script location
const CHUNKS_DIR = process.argv[2] || path.join(__dirname, '..', '.next', 'static', 'chunks');

function fixFile(fp) {
  const original = fs.readFileSync(fp, 'utf-8');
  
  // Quick check
  if (!original.includes('\\00')) return false;

  let fixed = '';
  let lastIdx = 0;
  const templateRe = /`[^`]*`/gs;  // Simple: match between backticks (binary templates have no nested)
  let match;

  while ((match = templateRe.exec(original)) !== null) {
    fixed += original.slice(lastIdx, match.index);
    const tmpl = match[0];
    // Only replace \00 inside template literals
    if (tmpl.includes('\\00')) {
      fixed += tmpl.replace(/\\00/g, '\\x00');
    } else {
      fixed += tmpl;
    }
    lastIdx = match.index + tmpl.length;
  }
  fixed += original.slice(lastIdx);

  if (fixed !== original) {
    const count = (original.match(/\\00/g) || []).length;
    fs.writeFileSync(fp, fixed, 'utf-8');
    return count;
  }
  return false;
}

function main() {
  if (!fs.existsSync(CHUNKS_DIR)) {
    console.error(`⚠️  Chunks directory not found: ${CHUNKS_DIR}`);
    process.exit(1);
  }

  let totalFixed = 0;
  const files = fs.readdirSync(CHUNKS_DIR).filter(f => f.endsWith('.js'));

  for (const file of files) {
    const fp = path.join(CHUNKS_DIR, file);
    const result = fixFile(fp);
    if (result !== false) {
      console.log(`✅ ${file}: fixed ${result} \\00 → \\x00`);
      totalFixed++;
    }
  }

  if (totalFixed === 0) {
    console.log('✅ No chunks needed patching.');
  } else {
    console.log(`\nPatched ${totalFixed} file(s).`);
  }
}

main();
