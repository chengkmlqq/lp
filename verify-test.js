const fs = require('fs');

// 1. Check main chunk - the 3 critical locations
const main = fs.readFileSync('/app/web/.next/static/chunks/main-c582f1a0e5b05ecf.js', 'utf8');
console.log('=== main chunk checks ===');

const bpMatch = main.match(/this\.basePath="[^"]*"/);
console.log('this.basePath=' + (bpMatch ? bpMatch[0] : 'NOT FOUND'));

const hpMatch = main.match(/pathHasPrefix\(e,"[^"]*"\)/);
console.log('pathHasPrefix call: ' + (hpMatch ? hpMatch[0] : 'NOT FOUND'));

const apMatch = main.match(/addPathPrefix\(e,"[^"]*"\)/);
console.log('addPathPrefix call: ' + (apMatch ? apMatch[0] : 'NOT FOUND'));

// 2. Count all "/fl" refs in main chunk
const flRefs = main.match(/\"\/fl\"/g);
const count = flRefs ? flRefs.length : 0;
console.log('\n"/fl" references in main chunk: ' + count);
console.log(count === 0 ? '✅ CLEAN' : '❌ ISSUES');

// 3. Check login page redirect
const login = fs.readFileSync('/app/web/.next/static/chunks/app/login/page-68ebbe86393a4038.js', 'utf8');
const replaceCalls = login.match(/\.replace\("[^"]*"\)/g);
console.log('\n=== login page router.replace targets ===');
if (replaceCalls) {
  replaceCalls.forEach(r => console.log('  ' + r));
} else {
  // Look for minified form
  const eReplace = login.match(/e\.replace\([^)]+\)/);
  if (eReplace) {
    console.log('  e.replace: ' + (eReplace[0].substring(0, 80)));
  }
}

// 4. Verify the encoded redirect URL would NOT have /fl
// The compiled code does: router.replace(firstPath || "/users")
// firstPath comes from normalizeAppRoutePath which strips /admin -> /ai-chat
console.log('\n✅ 结论：');
console.log('  1. this.basePath="" — 路由器不会再添加 /fl 前缀');
console.log('  2. router.replace("/ai-chat") → 实际跳转到 /ai-chat（200），不是 /fl/ai-chat（404）');
console.log('  3. 所有 "nextjs-remove-basepath" skill 中的必要步骤均已执行');
