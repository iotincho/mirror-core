const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const base=process.env.PROTOTYPE_URL || 'http://127.0.0.1:5181/laboratorio/';
const root=path.join(__dirname,'screenshots');
const sandbox={window:{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,'data.js'),'utf8'),sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,'graph.js'),'utf8'),sandbox);
const D=sandbox.window.LAB_DATA, project=sandbox.window.LabGraph.project;
for(const kind of ['values','podcast']) {
 const source=D.findings[kind], before=JSON.stringify(source);
 const a=project(source,{mode:'labels',expanded:true});
 const b=project(source,{mode:'findings',expanded:true});
 const c=project(source,{mode:'both',expanded:true});
 assert(a.nodes.every(n=>['note','label'].includes(n.data.kind)));
 assert(b.nodes.every(n=>['note','finding'].includes(n.data.kind)));
 assert.equal(b.edges.filter(e=>e.data.kind==='evidence').length,source.length);
 assert.equal(new Set(b.edges.map(e=>e.data.id)).size,b.edges.length);
 assert.deepEqual([...new Set(c.nodes.map(n=>n.data.kind))].sort(),['finding','label','note']);
 assert.equal(c.nodes.filter(n=>n.data.kind==='finding').length,source.length);
 assert.equal(c.nodes.filter(n=>n.data.kind==='label').length,new Set(source.flatMap(f=>Array.from(f.tags))).size);
 assert.equal(c.edges.filter(e=>e.data.kind==='evidence').length,source.length);
 assert.equal(c.edges.filter(e=>e.data.kind==='shared').length,0);
 assert.equal(new Set(c.edges.map(e=>e.data.id)).size,c.edges.length);
 for(const {data:e} of c.edges) {
  assert(c.nodes.some(n=>n.data.id===e.source));assert(c.nodes.some(n=>n.data.id===e.target));
  const f=source.find(f=>f.id===e.findingIds[0]);assert(f);
  if(e.kind==='tagging') {assert(f.tags.includes(e.tag));assert.equal(e.source,`finding:${f.id}`)}
  else {assert.equal(e.source,`note:${f.note}`);assert.equal(e.target,`finding:${f.id}`)}
 }
 for(const {data:e} of a.edges) for(const id of e.findingIds) {
  const f=source.find(f=>f.id===id); assert.equal(f.note,e.noteId); assert(f.tags.includes(e.tag));
 }
 for(const {data:e} of b.edges.filter(e=>e.data.kind==='shared')) {
  const [f,g]=e.findingIds.map(id=>source.find(f=>f.id===id));
  assert.deepEqual(Array.from(e.tags),Array.from(f.tags.filter(t=>g.tags.includes(t))));
 }
 assert.equal(JSON.stringify(source),before);
}
const duplicate={...D.findings.values[0],id:'v-duplicate'};
const aggregate=project([D.findings.values[0],duplicate],{mode:'labels',expanded:true});
assert(aggregate.edges.every(e=>e.data.findingIds.length===2));
const normalized=project([{...D.findings.values[0],tags:['Presencia',' presencia ','PRESENCIA']}],{mode:'both',expanded:true});
assert.equal(normalized.nodes.filter(n=>n.data.kind==='label').length,1);
assert.equal(normalized.edges.filter(e=>e.data.kind==='tagging').length,1);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || undefined,args:['--no-sandbox']});
 const report={projections:'passed: three projections, typed nodes and edges, normalized shared label nodes, complete evidence paths, no source mutation',layouts:[],errors:[],requests:[]};
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1050},reducedMotion:'reduce'});
  const page=await context.newPage();
  page.on('pageerror',e=>report.errors.push(String(e)));
  page.on('request',r=>report.requests.push(r.url()));
  await page.goto(base);await page.evaluate(()=>localStorage.clear());await page.reload();
  await page.getByRole('button',{name:'Explorar',exact:true}).click();
  await page.getByRole('button',{name:'Por etiquetas',exact:true}).waitFor();
  const stored=await page.evaluate(()=>localStorage.getItem('el-espejo:laboratorio:prototype:demo:v1'));
  async function graphReady(){await page.waitForFunction(()=>document.querySelector('#lab-graph')?._cyreg?.cy?.nodes().length>0);await page.waitForTimeout(150)}
  async function select(id){
   const summary=page.locator('.graph-accessibility summary');
   if(!await page.locator('.graph-accessibility').evaluate(el=>el.open))await summary.click();
   await page.locator('[data-action="graph-select"]').filter({has:page.locator('span')}).evaluateAll((els,key)=>{const el=els.find(e=>e.dataset.id===key);if(!el)throw new Error(`Missing ${key}`);el.click()},id);
  }
  async function check(name,width){
   await page.setViewportSize({width,height:844});await graphReady();
   const result=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,small:[...document.querySelectorAll('button,a.brand,.bottom-nav a')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height&&(r.height<43.5||r.width<43.5)}).map(e=>({text:e.textContent,aria:e.getAttribute("aria-label"),cls:e.className,w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}))}));
   const frame=await page.evaluate(()=>{const c=document.querySelector('#lab-graph')._cyreg.cy;return {box:c.elements().renderedBoundingBox(),width:c.width(),height:c.height()}});
   assert(frame.box.x1>=-1&&frame.box.y1>=-1&&frame.box.x2<=frame.width+1&&frame.box.y2<=frame.height+1,`${name} ${width}: graph out of frame ${JSON.stringify(frame)}`);
   if(result.overflow)console.log(await page.evaluate(()=>[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,15).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width}))));
   assert.equal(result.overflow,false,`${name} ${width} overflow`);assert.equal(result.small.length,0,JSON.stringify(result.small));report.layouts.push({name,width,overflow:false});
  }
  async function snapshot(name){
   await page.locator('.graph-accessibility').evaluate(el=>el.open=false);
   await page.evaluate(()=>document.activeElement?.blur());await graphReady();
   await page.locator('.graph-projection').screenshot({path:path.join(root,name+'.png')});
  }
  await graphReady();
  assert.deepEqual(await page.evaluate(()=>[...new Set(document.querySelector('#lab-graph')._cyreg.cy.nodes().map(n=>n.data('kind')))].sort()),['label','note']);
  await select('membership:n1:label:presencia');
  await page.locator('#finding-detail').getByText('Hacer lugar a la presencia',{exact:true}).waitFor();
  await page.locator('#finding-detail blockquote').getByText(/Quiero estar más presente/).waitFor();
  for(const width of [320,390,768,1440])await check('labels',width);
  await snapshot('grafo-etiquetas-desktop');
  await page.setViewportSize({width:390,height:844});await snapshot('grafo-etiquetas-mobile');
  await page.setViewportSize({width:1440,height:1050});
  await page.getByRole('button',{name:'Por hallazgos',exact:true}).click();await graphReady();
  assert.deepEqual(await page.evaluate(()=>[...new Set(document.querySelector('#lab-graph')._cyreg.cy.nodes().map(n=>n.data('kind')))].sort()),['finding','note']);
  await select('shared:v1:v5');
  await page.getByRole('heading',{name:'Un hilo compartido.',exact:true}).waitFor();
  await page.locator('#finding-detail .tag').getByText('Vínculos',{exact:true}).waitFor();
  await page.locator('#finding-detail').getByRole('button',{name:/Hacer lugar a la presencia/}).click();
  await page.getByRole('button',{name:'Leer en la nota completa'}).click();await page.locator('mark').waitFor();await page.keyboard.press('Escape');
  await select('evidence:v1');await page.getByText('RELACIÓN CON SU NOTA · CITA DE ORIGEN',{exact:true}).waitFor();
  await page.locator('#finding-detail blockquote').getByText(/Quiero estar más presente/).waitFor();
  const canvasBox=await page.locator('#lab-graph').boundingBox();
  const mid=await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.getElementById('shared:v1:v5').renderedMidpoint());
  await page.mouse.click(canvasBox.x+mid.x,canvasBox.y+mid.y);
  await page.getByRole('heading',{name:'Un hilo compartido.',exact:true}).waitFor();
  await page.getByRole('button',{name:'Acercar grafo'}).click();
  const camera=await page.evaluate(()=>{const c=document.querySelector('#lab-graph')._cyreg.cy;return {zoom:c.zoom(),pan:c.pan()}});
  await select('evidence:v1');
  assert.deepEqual(await page.evaluate(()=>{const c=document.querySelector('#lab-graph')._cyreg.cy;return {zoom:c.zoom(),pan:c.pan()}}),camera);
  await page.getByRole('button',{name:'Ajustar grafo a la pantalla'}).click();
  for(const width of [320,390,768,1440])await check('findings',width);
  await snapshot('grafo-hallazgos-desktop');
  await page.setViewportSize({width:390,height:844});await snapshot('grafo-hallazgos-mobile');
  await page.getByRole('button',{name:'Etiquetas y hallazgos',exact:true}).click();await graphReady();
  assert.deepEqual(await page.evaluate(()=>[...new Set(document.querySelector('#lab-graph')._cyreg.cy.nodes().map(n=>n.data('kind')))].sort()),['finding','label','note']);
  assert.equal(await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.edges('[kind="shared"]').length),0);
  await select('tagging:v1:label:presencia');
  await page.getByText('RELACIÓN CON LA ETIQUETA · Presencia',{exact:true}).waitFor();
  await page.locator('#finding-detail blockquote').getByText(/Quiero estar más presente/).waitFor();
  await select('label:presencia');
  assert.equal(await page.locator('#finding-detail [data-action="graph-finding"]').count(),3);
  await select('evidence:v1');
  await page.getByText('RELACIÓN CON SU NOTA · CITA DE ORIGEN',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Leer en la nota completa'}).click();await page.locator('mark').waitFor();await page.keyboard.press('Escape');
  for(const width of [320,390,768,1440])await check('both',width);
  await snapshot('grafo-completo-desktop');
  await page.setViewportSize({width:390,height:844});await snapshot('grafo-completo-mobile');
  await page.getByRole('button',{name:'Más conexiones',exact:true}).click();await graphReady();
  assert.equal(await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.nodes('[kind="finding"]').length),5);
  assert.equal(await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.nodes('[kind="label"]').length),6);
  for(const width of [320,390,1440])await check('both-expanded',width);
  await snapshot('grafo-completo-expandido-desktop');
  await page.getByRole('button',{name:'Por etiquetas',exact:true}).click();await graphReady();
  assert.equal(await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.nodes('[kind="finding"]').length),0);
  assert.equal(await page.evaluate(()=>localStorage.getItem('el-espejo:laboratorio:prototype:demo:v1')),stored);
  assert.deepEqual(report.errors,[]);assert(report.requests.every(u=>new URL(u).origin===new URL(base).origin));assert(!report.requests.some(u=>u.includes('/api/')));
  report.requests={external:0,backend:0};report.interactions='passed: three-view switch, membership evidence, shared labels, finding-label edge, label grouping, quote edge, full-source reading, canvas edge tap, camera preservation, expansion, local state unchanged';
  fs.writeFileSync(path.join(root,'graph-validation.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
