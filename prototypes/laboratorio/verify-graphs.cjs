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
const normalize=t=>t.normalize('NFC').trim().toLocaleLowerCase('es').replace(/\s+/g,' ');
const configurations=[];
for(let mask=1;mask<8;mask++) configurations.push({note:!!(mask&1),finding:!!(mask&2),label:!!(mask&4)});
for(const kind of ['values','podcast']) {
 const source=D.findings[kind], before=JSON.stringify(source);
 for(const visibility of configurations) {
  const model=project(source,{visibility,expanded:true});
  assert(model.nodes.every(n=>visibility[n.data.kind]));
  assert.equal(new Set(model.edges.map(e=>e.data.id)).size,model.edges.length);
  assert.equal(model.allNodes.filter(n=>n.data.kind==='finding').length,source.length);
  for(const {data:e} of model.edges) {
   const a=model.nodes.find(n=>n.data.id===e.source)?.data,b=model.nodes.find(n=>n.data.id===e.target)?.data;
   assert(a&&b,'Every edge must connect visible nodes');
   const matches=Array.from(e.findingIds,id=>source.find(f=>f.id===id));assert(matches.length&&matches.every(Boolean));
   if(e.kind==='evidence') {assert.equal(matches[0].note,a.noteId);assert.equal(matches[0].id,b.findingId)}
   if(e.kind==='tagging'||e.kind==='membership') for(const f of matches) assert(f.tags.some(t=>normalize(t)===normalize(e.tag)));
   if(e.kind==='membership') assert(matches.every(f=>f.note===e.noteId));
   if(e.kind==='shared') for(const tag of e.tags) assert(matches.every(f=>f.tags.some(t=>normalize(t)===normalize(tag))));
   if(e.kind==='note-shared') for(const tag of e.tags) for(const n of [a,b]) assert(matches.some(f=>f.note===n.noteId&&f.tags.includes(tag)));
   if(e.kind==='label-shared') for(const f of matches) assert(e.tags.every(t=>f.tags.includes(t)));
  }
 }
 assert.equal(JSON.stringify(source),before);
}
const duplicate={...D.findings.values[0],id:'v-duplicate'};
const aggregate=project([D.findings.values[0],duplicate],{visibility:{finding:false},expanded:true});
assert(aggregate.edges.every(e=>e.data.findingIds.length===2));
const normalized=project([{...D.findings.values[0],tags:['Presencia',' presencia ','PRESENCIA']}],{expanded:true});
assert.equal(normalized.nodes.filter(n=>n.data.kind==='label').length,1);
assert.equal(normalized.edges.filter(e=>e.data.kind==='tagging').length,1);
assert(project(D.findings.values,{visibility:{note:false,finding:false,label:false}}).nodes.length>0);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || undefined,args:['--no-sandbox']});
 const report={projections:'passed: seven combinations for both datasets, no dangling edges, exact provenance, normalized labels, aggregation, no source mutation',layouts:[],errors:[],requests:[]};
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1050},reducedMotion:'reduce'});
  const page=await context.newPage();
  page.on('pageerror',e=>report.errors.push(String(e)));
  page.on('request',r=>report.requests.push(r.url()));
  await page.goto(base);await page.evaluate(()=>localStorage.clear());await page.reload();
  await page.getByRole('button',{name:'Explorar',exact:true}).click();
  const controls=page.getByRole('group',{name:'Tipos de nodo'});
  await controls.waitFor();
  assert.equal(await page.locator('.axis-description').evaluate(el=>el.open),false);
  assert.equal(await page.locator('.axis-description > p').isVisible(),false);
  await page.locator('.axis-description summary').click();assert.equal(await page.locator('.axis-description > p').isVisible(),true);
  await page.locator('.axis-description summary').click();
  assert.equal(await page.getByRole('button',{name:'Más conexiones',exact:true}).count(),0);
  assert.equal(await page.getByText('Elementos y conexiones',{exact:true}).count(),0);
  const stored=await page.evaluate(()=>localStorage.getItem('el-espejo:laboratorio:prototype:demo:v1'));
  async function graphReady(){await page.waitForFunction(()=>document.querySelector('#lab-graph')?._cyreg?.cy?.nodes().length>0);await page.waitForTimeout(150)}
  async function select(id){
   await page.evaluate(key=>{const c=document.querySelector('#lab-graph')._cyreg.cy;const e=c.getElementById(key);if(!e.length)throw new Error(`Missing ${key}`);e.emit('tap')},id);
  }
  const camera=()=>page.evaluate(()=>{const c=document.querySelector('#lab-graph')._cyreg.cy;return {zoom:c.zoom(),pan:c.pan()}});
  const positions=()=>page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.nodes().map(n=>({id:n.id(),position:n.position()})));
  async function toggle(name){
   const before=await camera(), nodes=await positions();
   await controls.getByRole('button',{name,exact:true}).click();
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   assert.deepEqual(await camera(),before,'Toggle must preserve camera');
   assert.deepEqual(await positions(),nodes,'Toggle must preserve every node position, including hidden ones');
  }
  async function check(name,width){
   await page.setViewportSize({width,height:844});await graphReady();
   const result=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,small:[...document.querySelectorAll('button,a.brand,.bottom-nav a')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height&&(r.height<43.5||r.width<43.5)}).map(e=>({text:e.textContent,w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}))}));
   assert.equal(result.overflow,false,`${name} ${width} overflow`);assert.equal(result.small.length,0,JSON.stringify(result.small));
   const frame=await page.evaluate(()=>{const c=document.querySelector('#lab-graph')._cyreg.cy;return {box:c.elements(':visible').renderedBoundingBox(),width:c.width(),height:c.height()}});
   assert(frame.box.x1>=-1&&frame.box.y1>=-1&&frame.box.x2<=frame.width+1&&frame.box.y2<=frame.height+1,`${name} ${width}: graph out of frame`);
   report.layouts.push({name,width,overflow:false});
  }
  async function snapshot(name){
   await page.evaluate(()=>document.activeElement?.blur());await graphReady();
   await page.locator('.graph-projection').screenshot({path:path.join(root,name+'.png')});
  }
  await graphReady();
  await page.evaluate(()=>window.validationGraph=document.querySelector('#lab-graph')._cyreg.cy);
  await select('evidence:v1');await page.locator('#finding-detail blockquote').getByText(/Quiero estar más presente/).waitFor();
  for(const width of [320,390,768,1440])await check('all-layers',width);
  await snapshot('grafo-capas-desktop');
  await page.screenshot({path:path.join(root,'eje-descripcion-cerrada-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await snapshot('grafo-capas-mobile');
  await page.setViewportSize({width:1440,height:1050});await graphReady();
  // Drag a real canvas node; restoring a layer must also restore its manual position.
  await page.locator('#lab-graph').scrollIntoViewIfNeeded();
  const box=await page.locator('#lab-graph').boundingBox();
  const point=await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.getElementById('finding:v1').renderedPosition());
  const beforeDrag=await positions();
  await page.mouse.move(box.x+point.x,box.y+point.y);await page.mouse.down();await page.mouse.move(box.x+point.x+22,box.y+point.y+16,{steps:5});await page.mouse.up();
  assert.notDeepEqual(await positions(),beforeDrag,'Canvas node must be draggable');
  const dragged=await positions();
  await select('finding:v1');await page.getByRole('button',{name:'Acercar grafo'}).click();
  await toggle('Hallazgos');await page.getByText('Este elemento está oculto en el mapa. Su detalle sigue disponible.',{exact:true}).waitFor();
  await select('membership:n1:label:presencia');await page.locator('#finding-detail blockquote').getByText(/Quiero estar más presente/).waitFor();
  await page.getByRole('button',{name:'Leer en la nota completa',exact:true}).click();await page.locator('mark').waitFor();await page.keyboard.press('Escape');
  await toggle('Hallazgos');assert.deepEqual(await positions(),dragged);
  await toggle('Etiquetas');await select('shared:v1:v5');await page.getByRole('heading',{name:'Un hilo compartido.',exact:true}).waitFor();
  await toggle('Notas'); // Findings only.
  assert(await controls.getByRole('button',{name:'Hallazgos',exact:true}).isDisabled());
  await toggle('Etiquetas');await toggle('Hallazgos'); // Labels only.
  assert(await controls.getByRole('button',{name:'Etiquetas',exact:true}).isDisabled());
  const labelEdge=await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.edges('[kind="label-shared"]').first().id());
  await select(labelEdge);await page.getByRole('heading',{name:'Juntas en un hallazgo.',exact:true}).waitFor();
  assert(await page.locator('#finding-detail blockquote').count()>0);
  await toggle('Notas');await toggle('Etiquetas'); // Notes only.
  const noteEdge=await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.edges('[kind="note-shared"]').first().id());
  await select(noteEdge);await page.getByRole('heading',{name:'Un hilo entre tus notas.',exact:true}).waitFor();
  assert(await page.locator('#finding-detail blockquote').count()>1);
  await toggle('Hallazgos');await toggle('Etiquetas');
  assert(await page.evaluate(()=>window.validationGraph===document.querySelector('#lab-graph')._cyreg.cy),'One Cytoscape instance must survive toggles');
  for(const visibility of configurations) {
   for(const [kind,name] of [['note','Notas'],['finding','Hallazgos'],['label','Etiquetas']]) if(visibility[kind]&&(await controls.getByRole('button',{name,exact:true}).getAttribute('aria-pressed'))!=='true')await toggle(name);
   for(const [kind,name] of [['note','Notas'],['finding','Hallazgos'],['label','Etiquetas']]) if(!visibility[kind]&&(await controls.getByRole('button',{name,exact:true}).getAttribute('aria-pressed'))==='true')await toggle(name);
   const kinds=await page.evaluate(()=>[...new Set(document.querySelector('#lab-graph')._cyreg.cy.nodes(':visible').map(n=>n.data('kind')))].sort());
   assert.deepEqual(kinds,Object.keys(visibility).filter(k=>visibility[k]).sort(),JSON.stringify(await page.evaluate(()=>({buttons:[...document.querySelectorAll('[data-action=graph-layer]')].map(e=>[e.dataset.kind,e.getAttribute('aria-pressed')]),nodes:document.querySelector('#lab-graph')._cyreg.cy.nodes().map(n=>({id:n.id(),classes:n.classes(),visible:n.visible()}))}))));
   // Explicit fit is user-controlled; toggling never fits or rearranges automatically.
   await page.getByRole('button',{name:'Ajustar grafo a la pantalla'}).click();
   for(const width of [320,390,768,1440])await check(kinds.join('+'),width);
   if(!visibility.finding&&visibility.note&&visibility.label) {
    await select('membership:n1:label:presencia');await snapshot('grafo-capas-sin-hallazgos-desktop');
    await page.setViewportSize({width:390,height:844});await snapshot('grafo-capas-sin-hallazgos-mobile');
   }
  }
  // Keyboard toggle and focus remain usable.
  const notes=controls.getByRole('button',{name:'Notas',exact:true});await notes.focus();await page.keyboard.press('Space');assert.equal(await notes.getAttribute('aria-pressed'),'false');
  await page.keyboard.press('Space');assert.equal(await notes.getAttribute('aria-pressed'),'true');
  const beforeExpansion=await positions(), beforeCamera=await camera();
  await page.locator('#lab-graph').scrollIntoViewIfNeeded();
  const canvasBox=await page.locator('#lab-graph').boundingBox();
  const notePoint=await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.getElementById('note:n1').renderedPosition());
  await page.mouse.click(canvasBox.x+notePoint.x,canvasBox.y+notePoint.y);await graphReady();
  assert.equal(await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.nodes('[kind="finding"]:visible').length),4);
  assert.deepEqual(await camera(),beforeCamera);
  const expandedPositions=await positions();
  for(const n of beforeExpansion) assert.deepEqual(expandedPositions.find(x=>x.id===n.id),n);
  await select('label:ritmo%20propio');await graphReady();
  assert.equal(await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.nodes('[kind="finding"]:visible').length),5);
  assert.deepEqual(await camera(),beforeCamera);
  const allCount=await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.nodes().length);
  await select('label:ritmo%20propio');assert.equal(await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.nodes().length),allCount);
  await page.getByRole('button',{name:'Ajustar grafo a la pantalla'}).click();
  for(const width of [320,390,1440])await check('expanded',width);
  await snapshot('grafo-progresivo-desktop');
  await page.setViewportSize({width:390,height:844});await page.reload();await graphReady();
  assert.equal(await page.locator('.axis-description').evaluate(el=>el.open),false);
  await page.locator('#lab-graph').scrollIntoViewIfNeeded();
  const mobileScroll=await page.evaluate(()=>scrollY), mobileCamera=await camera();
  await select('note:n1');await graphReady();
  assert.equal(await page.evaluate(()=>scrollY),mobileScroll,'Mobile expansion must keep the graph in view');
  assert.deepEqual(await camera(),mobileCamera);
  assert.equal(await page.evaluate(()=>document.querySelector('#lab-graph')._cyreg.cy.nodes('[kind="finding"]:visible').length),4);
  await page.screenshot({path:path.join(root,'eje-exploracion-mobile.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>localStorage.getItem('el-espejo:laboratorio:prototype:demo:v1')),stored);
  assert.deepEqual(report.errors,[]);assert(report.requests.every(u=>new URL(u).origin===new URL(base).origin));assert(!report.requests.some(u=>u.includes('/api/')));
  report.requests={external:0,backend:0};report.interactions='passed: seven layer combinations, one graph instance, camera and dragged positions preserved, hidden selection detail retained, exact citations, full-source reading, single-layer provenance, keyboard, last-layer protection, collapsed purpose, progressive canvas expansion with stable positions and camera, no global expansion button, storage unchanged';
  fs.writeFileSync(path.join(root,'graph-validation.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
