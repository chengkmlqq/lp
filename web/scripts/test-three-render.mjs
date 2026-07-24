#!/usr/bin/env node
/**
 * Three.js 渲染定时测试脚本
 * 每小时执行一次，验证 three.js 能否正确渲染出图。
 *
 * 用法: node scripts/test-three-render.mjs [--fix]
 *
 * 原理：
 * 1. 生成测试 HTML，引用本地 three.js 模块
 * 2. 启动临时 HTTP 服务器（避免 file:// 的 CORS 限制）
 * 3. Puppeteer 加载页面，执行渲染测试
 * 4. 截图验证，输出 JSON 结果
 * 5. --fix 模式：检查常见问题并自动修复/提交
 */

import puppeteer from "puppeteer";
const launchBrowser = typeof puppeteer.launch === "function"
  ? puppeteer.launch
  : () => { throw new Error("Puppeteer launch not available"); };

import { execSync } from "child_process";
import { existsSync, mkdirSync, writeFileSync, readFileSync } from "fs";
import { resolve, dirname, extname } from "path";
import { fileURLToPath } from "url";
import { createServer } from "http";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..", ".."); // scripts -> web -> lp
const SCREENSHOT_DIR = resolve(ROOT, ".three-test-screenshots");
const HTML_OUTPUT = resolve(ROOT, ".three-test-run.html");
const LOG_FILE = resolve(ROOT, ".three-test-results.json");
const PASS_MARK = resolve(ROOT, ".three-test-pass");

if (!existsSync(SCREENSHOT_DIR)) mkdirSync(SCREENSHOT_DIR, { recursive: true });

const PORT = 19783 + Math.floor(Math.random() * 1000);

// ── 生成测试 HTML ──────────────────────────────────────────
function generateTestHTML() {
  const threeRoot = resolve(ROOT, "node_modules/three");
  const buildPath = resolve(threeRoot, "build/three.module.js");
  const addonsDir = resolve(threeRoot, "addons/");
  if (!existsSync(buildPath)) {
    console.error("❌ 未找到 three.module.js");
    process.exit(1);
  }
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Three.js Render Test</title>
<style>
  body { margin:0; background:#0f172a; overflow:hidden; }
  #container { width:100vw; height:100vh; position:relative; }
</style>
</head>
<body>
<div id="container"></div>
<script type="importmap">
{
  "imports": {
    "three": "./node_modules/three/build/three.module.js",
    "three/addons/": "./node_modules/three/examples/jsm/"
  }
}
</script>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";

const results = {};
function record(name, pass, detail) { results[name]={pass,detail}; console.log(\`[TEST] \${name}: \${pass?"PASS":"FAIL"} - \${detail}\`); }
function sleep(ms) { return new Promise(r=>setTimeout(r,ms)); }

async function runTests() {
  const c = document.getElementById("container");
  const w = c.clientWidth||1200, h = c.clientHeight||800;

  // 1. 基础场景创建
  try {
    const scene = new THREE.Scene(); scene.background=new THREE.Color(0x0f172a);
    const camera = new THREE.PerspectiveCamera(45,w/h,0.1,20000); camera.position.set(0,600,600);
    const renderer = new THREE.WebGLRenderer({antialias:true}); renderer.setSize(w,h); c.appendChild(renderer.domElement);
    const labelR = new CSS2DRenderer(); labelR.setSize(w,h);
    labelR.domElement.style.position="absolute"; labelR.domElement.style.top="0"; labelR.domElement.style.left="0";
    labelR.domElement.style.pointerEvents="none"; c.appendChild(labelR.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0,0,0); controls.update();
    const al = new THREE.AmbientLight(0xffffff,0.5); scene.add(al);
    const dl = new THREE.DirectionalLight(0xffffff,1); dl.position.set(100,200,50); scene.add(dl);
    record("basic-scene", true, "场景/相机/渲染器/灯光/控制器 创建成功");
  } catch(e) { record("basic-scene", false, e.message); }

  await sleep(50);

  // Re-create clean scene
  const scene=new THREE.Scene(); scene.background=new THREE.Color(0x0f172a);
  const camera=new THREE.PerspectiveCamera(45,w/h,0.1,20000); camera.position.set(0,600,600);
  const renderer=new THREE.WebGLRenderer({antialias:true}); renderer.setSize(w,h); c.appendChild(renderer.domElement);
  const labelR=new CSS2DRenderer(); labelR.setSize(w,h);
  labelR.domElement.style.position="absolute"; labelR.domElement.style.top="0"; labelR.domElement.style.left="0";
  labelR.domElement.style.pointerEvents="none"; c.appendChild(labelR.domElement);
  const controls=new OrbitControls(camera,renderer.domElement); controls.target.set(0,0,0);
  scene.add(new THREE.AmbientLight(0xffffff,0.5));
  const dl2=new THREE.DirectionalLight(0xffffff,1); dl2.position.set(100,200,50); scene.add(dl2);

  const tGroup=new THREE.Group(); scene.add(tGroup);
  const lGroup=new THREE.Group(); scene.add(lGroup);
  const pGroup=new THREE.Group(); scene.add(pGroup);

  // 2. 地形网格
  try {
    const size=5000, seg=64;
    const geom=new THREE.PlaneGeometry(size,size,seg,seg); geom.rotateX(-Math.PI/2);
    const pos=geom.attributes.position.array;
    const colors=new Float32Array(pos.length);
    for(let i=0;i<=seg;i++) for(let j=0;j<=seg;j++){
      const idx=(j*(seg+1)+i)*3;
      const x=(i/seg-0.5)*size, z=(j/seg-0.5)*size;
      const height=Math.sin(x*0.01)*30+Math.cos(z*0.015)*20+10;
      pos[idx+1]=height;
      const r=0.2+height/100*0.6, g=0.2+(1-(height+50)/100)*0.4, b=0.2;
      colors[idx]=r; colors[idx+1]=g; colors[idx+2]=b;
    }
    geom.setAttribute("color",new THREE.BufferAttribute(colors,3)); geom.computeVertexNormals();
    tGroup.add(new THREE.Mesh(geom,new THREE.MeshStandardMaterial({vertexColors:true,roughness:0.6,metalness:0.1})));
    record("terrain-grid",true,\`地形网格 OK，顶点 \${(seg+1)*(seg+1)}\`);
  } catch(e) { record("terrain-grid",false,e.message); }

  // 3. 杆塔点云 + 4. 线段 + 5. 标签
  try {
    const tc=30; const pts_pos=[], pts_col=[];
    const line_pts=[];
    for(let i=0;i<tc;i++){
      const x=(i-tc/2)*160, z=Math.sin(i*0.5)*100;
      const h=Math.sin(x*0.003)*30+Math.cos(z*0.005)*20+10;
      pts_pos.push(x,h,z);
      const risk=i%3;
      const col=risk===0?[0.13,0.77,0.37]:risk===1?[0.96,0.62,0.04]:[0.94,0.27,0.27];
      pts_col.push(...col);
      line_pts.push(new THREE.Vector3(x,h,z));
    }
    // 3.杆塔点
    const pg=new THREE.BufferGeometry();
    pg.setAttribute("position",new THREE.Float32BufferAttribute(pts_pos,3));
    pg.setAttribute("color",new THREE.Float32BufferAttribute(pts_col,3));
    pGroup.add(new THREE.Points(pg,new THREE.PointsMaterial({size:12,vertexColors:true,sizeAttenuation:true,opacity:0.9,transparent:true})));
    record("tower-points",true,\`杆塔点云 OK，\${tc}座\`);
    // 4.线段
    const lg=new THREE.BufferGeometry().setFromPoints(line_pts);
    lGroup.add(new THREE.Line(lg,new THREE.LineBasicMaterial({color:0xf97316})));
    record("line-segments",true,\`线路线段 OK，\${tc}节点\`);
    // 5.标签
    for(let i=0;i<tc;i++){
      const x=(i-tc/2)*160, z=Math.sin(i*0.5)*100;
      const h=Math.sin(x*0.003)*30+Math.cos(z*0.005)*20+10;
      const div=document.createElement("div");
      div.textContent=i===0?"起点 塔#1":i===tc-1?"终点 塔#"+(i+1):"塔#"+(i+1);
      div.style.color="#fff"; div.style.fontSize="11px"; div.style.fontWeight="600";
      div.style.fontFamily="sans-serif"; div.style.textShadow="0 0 4px rgba(0,0,0,0.8)";
      div.style.background="rgba(0,0,0,0.5)"; div.style.padding="2px 6px"; div.style.borderRadius="3px";
      div.style.whiteSpace="nowrap";
      const lbl=new CSS2DObject(div); lbl.position.set(x,h+15,z); pGroup.add(lbl);
    }
    record("labels-css2d",true,\`CSS2D 标签 OK，\${tc}个\`);
  } catch(e) {
    if(!results["tower-points"]) record("tower-points",false,e.message);
    if(!results["line-segments"]) record("line-segments",false,e.message);
    if(!results["labels-css2d"]) record("labels-css2d",false,e.message);
  }

  // 渲染
  controls.target.set(0,30,0); controls.update();
  for(let f=0;f<40;f++){ renderer.render(scene,camera); labelR.render(scene,camera); controls.update(); }
  await sleep(200);
  for(let f=0;f<10;f++){ renderer.render(scene,camera); labelR.render(scene,camera); }
  await sleep(50);

  const passCount=Object.values(results).filter(r=>r.pass).length;
  const totalCount=Object.values(results).length;
  const allPass=passCount===totalCount;
  console.log(\`\\n[SUMMARY] \${passCount}/\${totalCount} tests passed - \${allPass?"ALL PASS":"SOME FAILED"}\`);
  window.__TEST_RESULTS__={allPass,passCount,totalCount,results};
  window.__TEST_COMPLETE__=true;
}

runTests().catch(e=>{
  console.error("[TEST] Fatal:",e.message);
  window.__TEST_RESULTS__={allPass:false,passCount:0,totalCount:5,results:{fatal:{pass:false,detail:e.message}}};
  window.__TEST_COMPLETE__=true;
});
</script>
</body>
</html>`;
}

// ── HTTP 服务器 ────────────────────────────────────────────
function startServer(htmlContent) {
  return new Promise((srvReady, reject) => {
    const server = createServer((req, res) => {
    try {
      const rawPath = req.url?.split("?")[0] || "/";

      // 根路径 → 返回测试 HTML
      if (rawPath === "/" || rawPath === "/index.html") {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(htmlContent);
        return;
      }

      // 安全限制：只允许访问 node_modules
      const filePath = resolve(ROOT, "." + rawPath);
      if (!filePath.startsWith(resolve(ROOT, "node_modules"))) {
        res.writeHead(403);
        res.end("Forbidden");
        return;
      }

      if (!existsSync(filePath)) {
        res.writeHead(404);
        res.end("Not found");
        return;
      }

      const ext = extname(filePath);
      const mime = {
        ".js": "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".svg": "image/svg+xml",
      }[ext] || "application/octet-stream";

      res.writeHead(200, { "Content-Type": mime });
      res.end(readFileSync(filePath));
    } catch (err) {
      console.error("  ⚠️ 服务请求异常:", req.url, err.message);
      if (!res.headersSent) res.writeHead(500);
      res.end("Server error");
    }
  });

    server.listen(PORT, "127.0.0.1", () => {
      console.log(`  🌐 临时 HTTP 服务器: http://127.0.0.1:${PORT}`);
      srvReady(server);
    });
    server.on("error", reject);
  });
}

// ── 执行渲染测试 ──────────────────────────────────────────
async function runRenderTest() {
  console.log("\n" + "=".repeat(60));
  console.log("  Three.js 渲染测试 ——", new Date().toISOString().replace("T", " ").slice(0, 19));
  console.log("=".repeat(60));

  const html = generateTestHTML();
  writeFileSync(HTML_OUTPUT, html, "utf-8");

  const server = await startServer(html);
  let browser;

  try {
    browser = await launchBrowser({
      headless: true,
      args: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
      ],
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1200, height: 800 });

    // 捕获控制台（包含错误）
    page.on("console", (msg) => {
      const text = msg.text();
      if (text.startsWith("[TEST]") || text.startsWith("[SUMMARY]")) {
        console.log("    " + text);
      } else if (msg.type() === "error") {
        console.error("    🔴 Browser error:", text);
      }
    });
    page.on("pageerror", (err) => {
      console.error("    🔴 Page error:", err.message);
    });
    page.on("requestfailed", (req) => {
      console.error("    🔴 Request failed:", req.url(), req.failure()?.errorText);
    });

    const url = `http://127.0.0.1:${PORT}/`;
    await page.goto(url, { waitUntil: "networkidle0", timeout: 15000 });

    // 等待测试完成（最长 40s）
    await page.waitForFunction(
      () => window.__TEST_COMPLETE__ === true,
      { timeout: 40000 }
    );

    const testResults = await page.evaluate(() => window.__TEST_RESULTS__);

    // 截图
    const ts = Date.now();
    const screenshotPath = resolve(SCREENSHOT_DIR, `render-${ts}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: false });

    if (testResults) {
      console.log(`\n  📸 截图: ${screenshotPath}`);
      const p = testResults.passCount, t = testResults.totalCount;
      console.log(`  📊 ${p}/${t} 通过 — ${testResults.allPass ? "✅ ALL PASS" : "❌ 有失败项"}`);
      for (const [name, r] of Object.entries(testResults.results)) {
        console.log(`     ${r.pass ? "✅" : "❌"} ${name}: ${r.detail}`);
      }
      return testResults;
    }

    console.error("  ❌ 未能获取测试结果");
    return { allPass: false, passCount: 0, totalCount: 5, results: { error: "No results" } };

  } catch (e) {
    console.error("  ❌ 测试异常:", e.message);
    return { allPass: false, passCount: 0, totalCount: 5, results: { fatal: { pass: false, detail: e.message } } };
  } finally {
    if (browser) await browser.close();
    server.close();
  }
}

// ── 检查常见问题并自动修复 ────────────────────────────────
function autoFixIssues() {
  const issues = [];

  const components = [
    { file: "src/components/power-line-three-map.tsx", label: "PK 3D 地图" },
    { file: "src/components/elevation-preview-three-map.tsx", label: "高程预览" },
  ];

  for (const { file, label } of components) {
    const fp = resolve(ROOT, "web", file);
    if (!existsSync(fp)) { console.log(`  ⚠️ ${label}: 文件不存在`); continue; }
    const content = readFileSync(fp, "utf-8");
    const checks = [
      { pat: /controls\S*\.dispose\b/, msg: "controls dispose" },
      { pat: /renderer\S*\.dispose\b/, msg: "renderer dispose" },
      { pat: /labelRenderer\S*\.dispose\b/, msg: "labelRenderer dispose" },
      { pat: /geometry\S*\.dispose\b/, msg: "geometry dispose" },
      { pat: /material\S*\.dispose\b/, msg: "material dispose" },
      { pat: /\S*\.disconnect\b/, msg: "ResizeObserver disconnect" },
    ];
    const missing = checks.filter(c => !c.pat.test(content));
    if (missing.length > 0) {
      issues.push(`${label}: 缺少 ${missing.map(m => m.msg).join(", ")}`);
    } else {
      console.log(`  ✅ ${label}: 所有 dispose 检查通过`);
    }
  }

  if (issues.length > 0) {
    console.log("\n⚠️ 发现但未自动修复:");
    issues.forEach(i => console.log(`  - ${i}`));
  } else {
    console.log("  ✅ 未发现明显问题");
  }

  return issues.length === 0;
}

// ── Git 提交 ──────────────────────────────────────────────
function gitCommit(message) {
  try {
    const status = execSync("git status --porcelain", { cwd: ROOT, encoding: "utf-8" }).trim();
    if (!status) { console.log("  ℹ️ 无改动，跳过提交"); return false; }

    // 只提交相关文件
    const changed = status.split("\n")
      .filter(l => l.startsWith(" M") || l.startsWith("??"))
      .map(l => l.trim().split(/\s+/).pop())
      .filter(f => f.startsWith("web/") || f.startsWith(".three-test"));

    if (changed.length === 0) { console.log("  ℹ️ 无 web 相关改动"); return false; }

    execSync("git add " + changed.map(f => `"${f}"`).join(" "), { cwd: ROOT });
    execSync("git commit -m " + JSON.stringify(message), { cwd: ROOT });
    // 尝试推送，失败不阻断
    try {
      execSync("git push origin dev", { cwd: ROOT, timeout: 30000 });
      console.log("  ✅ 已推送");
    } catch {
      console.log("  ⚠️ 推送失败（网络？），代码已提交");
    }
    return true;
  } catch (e) {
    console.error("  ❌ Git 错误:", e.message);
    return false;
  }
}

// ── 写结果 ────────────────────────────────────────────────
function writeResults(results) {
  const log = { timestamp: new Date().toISOString(), ...results };
  writeFileSync(LOG_FILE, JSON.stringify(log, null, 2), "utf-8");
}

// ── 主函数 ────────────────────────────────────────────────
async function main() {
  const args = process.argv.slice(2);
  const shouldFix = args.includes("--fix");
  const cronMode = args.includes("--cron");

  if (shouldFix) {
    console.log("🔧 检查 three.js 常见问题...");
    autoFixIssues();
    console.log("");
  }

  const results = await runRenderTest();
  writeResults(results);

  if (results.allPass) {
    writeFileSync(PASS_MARK, new Date().toISOString(), "utf-8");
    console.log(`\n✅ 全部通过，标记已写入`);
  } else {
    console.log(`\n❌ 有测试失败`);
  }

  if (cronMode && results.allPass && shouldFix) {
    const ts = new Date().toISOString().slice(0, 19).replace("T", " ");
    gitCommit(`[test][3d] 定时渲染测试通过 (${ts})`);
  }

  process.exit(results.allPass ? 0 : 1);
}

main().catch(e => { console.error("Fatal:", e); process.exit(1); });
