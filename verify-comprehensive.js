const fs = require('fs');
const { execSync } = require('child_process');

console.log('=== 1. Router basePath check ===');
const main = fs.readFileSync('/app/web/.next/static/chunks/main-c582f1a0e5b05ecf.js', 'utf8');
const bpIdx = main.indexOf('this.basePath');
console.log('  ' + main.substring(bpIdx, bpIdx + 30));

console.log('\n=== 2. Quoted /fl refs in main chunk ===');
const flCount = (main.match(/"\/fl"/g) || []).length;
console.log('  Count: ' + flCount);
console.log('  ' + (flCount === 0 ? 'PASS' : 'FAIL'));

console.log('\n=== 3. Login page redirect code ===');
const login = fs.readFileSync('/app/web/.next/static/chunks/app/login/page-68ebbe86393a4038.js', 'utf8');
const rIdx = login.indexOf('e.replace(');
if (rIdx >= 0) {
  console.log('  ' + login.substring(rIdx, rIdx + 60));
} else {
  // Minified: look for .replace("
  const rIdx2 = login.indexOf('.replace("');
  if (rIdx2 >= 0) console.log('  ' + login.substring(rIdx2, rIdx2 + 60));
}

console.log('\n=== 4. Normalize path (strip /admin) ===');
const nIdx = login.indexOf('.slice(6)');
if (nIdx >= 0) {
  console.log('  ' + login.substring(Math.max(0, nIdx - 30), nIdx + 15));
}

console.log('\n=== 5. Route test via proxy ===');
const routes = ['/login', '/ai-chat', '/fl/ai-chat', '/admin/ai-chat'];
routes.forEach(r => {
  try {
    const result = execSync('curl -s -o /dev/null -w "%{http_code}" http://proxy:3000' + r, {timeout: 5}).toString().trim();
    console.log('  ' + result + ' ' + r);
  } catch(e) {
    console.log('  ERROR ' + r);
  }
});

console.log('\n=== 6. Overall ===');
console.log('  Image: fquiz-web:84-v4');
console.log('  basePath: "" (empty)');
console.log('  /fl/ai-chat returns: ' + (() => {
  try { return execSync('curl -s -o /dev/null -w "%{http_code}" http://proxy:3000/fl/ai-chat', {timeout: 5}).toString().trim(); } catch(e) { return 'ERROR'; }
})());
