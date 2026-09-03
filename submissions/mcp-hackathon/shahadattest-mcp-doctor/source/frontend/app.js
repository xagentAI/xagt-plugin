const BACKEND = (localStorage.getItem('mcp_backend') || 'http://localhost:8000');
document.getElementById('backendUrl').textContent = BACKEND;
let PID = null;
async function jget(p){const r=await fetch(BACKEND+p);return r.json();}
async function jpost(p,b){const r=await fetch(BACKEND+p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});if(!r.ok)throw new Error(await r.text());return r.json();}
fetch(BACKEND+'/health').then(r=>r.json()).then(h=>document.getElementById('health').textContent='backend '+h.status+' v'+h.version).catch(()=>document.getElementById('health').textContent='backend unreachable');
function show(){document.getElementById('view-proj').scrollIntoView();}
async function tryDemo(){
  const spec = await (await fetch('demo-openapi.json')).json();
  spec.servers=[{url:prompt('Demo API base URL:','http://localhost:8001')}];
  const p = await jpost('/api/projects',{name:'Demo Weather API',openapi_json:spec});
  await openProject(p.id);
}
async function createProject(){
  const name=document.getElementById('pname').value||'Demo';
  const url=document.getElementById('purl').value||null;
  const raw=document.getElementById('pjson').value||null;
  let body={name};
  if(raw){try{body.openapi_json=JSON.parse(raw);}catch(e){document.getElementById('newOut').textContent='Invalid JSON: '+e;return;}}
  else if(url){body.openapi_url=url;}
  else{document.getElementById('newOut').textContent='Provide OpenAPI URL or paste JSON.';return;}
  try{const p=await jpost('/api/projects',body);await openProject(p.id);}
  catch(e){document.getElementById('newOut').textContent=String(e).slice(0,500);}
}
async function openProject(id){
  PID=id;
  document.getElementById('view-proj').style.display='block';
  await jpost(`/api/projects/${id}/analyze`,{});
  await refresh();show();
}
async function refresh(){
  const proj=await jget(`/api/projects/${PID}`);
  document.getElementById('projTitle').textContent=proj.name;
  const s=proj.score||{};const b=s.breakdown||{};
  document.getElementById('scoreBig').textContent=(s.overall??'–')+' / 100';
  document.getElementById('scoreBreak').innerHTML=Object.entries(b).map(([k,v])=>`<span class="pill">${k}: ${v}</span>`).join(' ');
  const issues=proj.issues||[];
  const cnt={};issues.forEach(i=>cnt[i.severity]=(cnt[i.severity]||0)+1);
  document.getElementById('issues').innerHTML=issues.slice(0,30).map(i=>`<div><span class="pill">${i.severity}</span> <b>${i.code}</b> — ${i.message}<div class="mut">fix: ${i.suggested_repair||''}</div></div>`).join('')||'<span class="mut">No issues 🎉</span>';
  const tests=await jget(`/api/projects/${PID}/tests`).catch(()=>[]);
  const passed=tests.filter(t=>t.status==='passed').length;
  document.getElementById('testSum').innerHTML=`${tests.length} endpoints · ${passed} passed`;
  document.getElementById('eps').innerHTML=(proj.endpoints||[]).map(e=>{const t=tests.find(t=>t.endpoint===`${e.method} ${e.path}`);return `<tr><td>${e.method}</td><td>${e.path}<div class="mut">${e.operation_id}</div></td><td class="${t?(t.status==='passed'?'pass':'warn'):''}">${t?t.status:'—'}</td><td>${t&&t.latency_ms!=null?t.latency_ms+'ms':'—'}</td><td>${issues.filter(i=>i.endpoint===`${e.method} ${e.path}`).length}</td></tr>`;}).join('');
  const tools=await jget(`/api/projects/${PID}/tools`).catch(()=>[]);
  document.getElementById('tools').innerHTML=tools.map(t=>`<div class="card"><b>${t.name}</b><div class="mut">${t.description}</div><pre>${JSON.stringify(t.inputSchema,null,1).slice(0,600)}</pre></div>`).join('');
}
async function runTests(){await jpost(`/api/projects/${PID}/test`,{});await refresh();}
async function doRepair(){
  document.getElementById('compare').textContent='Agentizing: analyzing → rules → validating → retesting…';
  const r=await jpost(`/api/projects/${PID}/repair`,{});
  const c=r.comparison;
  document.getElementById('compare').innerHTML=`<div class="big-arrow">${c.before_score} ↓ ${c.after_score}</div><b>+${c.improvement} Agent Readiness</b><div class="mut">${c.issues_fixed} issues fixed · ${c.issues_remaining} remaining</div>`;
  await refresh();
}
async function tryProxy(){
  const op=document.getElementById('opid').value;
  let args={};try{args=JSON.parse(document.getElementById('opargs').value||'{}');}catch(e){}
  const r=await jpost(`/api/projects/${PID}/proxy/${op}`,{arguments:args});
  document.getElementById('proxyOut').textContent=JSON.stringify(r,null,2);
}
async function doExport(){
  const r=await jget(`/api/projects/${PID}/export`);
  document.getElementById('exportOut').textContent=JSON.stringify(r,null,2).slice(0,4000);
  const blob=new Blob([JSON.stringify(r,null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='mcp-doctor-export.json';a.click();
}
