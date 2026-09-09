/* Worldloom Studio: every displayed run and count comes from the local service. */
"use strict";
const state = {projects: [], catalogue: {}, company: null, page: "overview", harness: false, evals: [], offset: 0, filter: "", history: [], pending: false};
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const copy = (v) => structuredClone(v);
const pretty = (v) => JSON.stringify(v, null, 2);
const label = (v) => String(v || "").replaceAll("_", " ");
const fmt = (v) => Number(v || 0).toLocaleString();
const companyName = (p) => p?.spec.company.identity.company_name || "Company";
const badge = (text, color="") => `<span class="badge ${color}">${esc(text)}</span>`;
const button = (text, action, cls="", attrs="") => `<button type="button" class="${cls}" data-action="${action}" ${attrs}>${text}</button>`;
const option = (value, text, selected) => `<option value="${esc(value)}" ${value===selected?"selected":""}>${esc(text)}</option>`;
const field = (title, name, value="", type="text", help="") => `<div class="field"><label for="f-${name}">${title}</label><input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${type==="number"?'min="1"':""}>${help?`<p class="help">${help}</p>`:""}</div>`;
const icons = {
  overview:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  company:'<path d="M4 21V5l8-2v18M12 8h8v13M8 8v1m0 4v1m8-2v1m0 4v1M2 21h20"/>',
  interview:'<path d="M21 12a8 8 0 0 1-8 8H4l-1 2V11a8 8 0 0 1 8-8h2a8 8 0 0 1 8 9Z"/><path d="M7 9h10M7 13h7"/>',
  usecases:'<path d="M9 5h11M9 12h11M9 19h11M3 5l1 1 2-3M3 12l1 1 2-3M3 19l1 1 2-3"/>',
  evals:'<path d="M4 20V4h16v16ZM4 9h16M10 9v11M15 9v11"/>',
  changes:'<path d="M3 11a9 9 0 1 1 3 8M3 5v6h6M12 7v6l4 2"/>'
};
const navItems = [["overview","Overview"],["company","Company & processes"],["interview","Interview"],["usecases","Use cases"],["evals","Evaluations"],["changes","Changes & runs"]];
function notify(message) { $("#notice").textContent = message; setTimeout(()=> {$("#notice").textContent="";}, 7000); }
async function api(path, body) {
  const response = await fetch(path, {method:body===undefined?"GET":"POST", headers:body===undefined?{}:{"Content-Type":"application/json","X-Worldloom-Studio":"1"}, body:body===undefined?undefined:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
function route(action="") { return `/api/projects/${state.company.id}${action?"/"+action:""}`; }
async function refresh() {
  const previous=state.company.revision;
  state.company=await api(route());state.projects=state.projects.map(p=>p.id===state.company.id?state.company:p);
  if(state.company.revision!==previous){state.evals=[];state.offset=0;state.history=[];}
}
async function selectCompany(id) { state.company=await api(`/api/projects/${id}`);state.evals=[];state.offset=0;state.history=[];state.filter="";render(); }
function latestCompile() { return state.company?.jobs.find(j=>j.revision===state.company.revision && j.options.operation==="compile" && j.result?.report); }
function report() { return latestCompile()?.result.report; }
function head(title, text, actions="") { return `<div class="page-head"><div><h1>${title}</h1><p>${text}</p></div><div class="actions">${actions}</div></div>`; }
function modal(title, content) { $("#dialog-content").innerHTML=`${button("Close","close","close")}<h2>${title}</h2>${content}`;$("#editor").showModal(); }
function download(name, value) { const url=URL.createObjectURL(new Blob([pretty(value)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000); }
async function revise(spec, reason) { await api(route("revise"), {revision:state.company.revision,spec,reason});await refresh();render();notify("Company revision saved. Earlier runs retain their original evidence."); }
function onboarding() {
  return `<main class="onboarding" id="main"><div class="wordmark">worldloom <span>STUDIO</span></div><h1>Start with one company.</h1><p class="intro">Describe its business. Map the work. Build the evidence and evaluations in one coherent world.</p><div class="two-col"><section class="panel"><h2>Create a company workspace</h2><p class="muted small">You can refine the profile with your coding harness.</p><form id="create-form">${field("Company name","name","","text")}
    <div class="form-grid"><div class="field"><label for="f-engine">Generation engine</label><select id="f-engine" name="engine">${state.catalogue.engines.map(v=>option(v,label(v),"retail")).join("")}</select></div><div class="field"><label for="f-geo">Geography</label><select id="f-geo" name="geo">${state.catalogue.locales.map(v=>option(v,label(v),"united_kingdom")).join("")}</select></div></div>${field("Seed","seed",8128,"number","Recorded once. Eval batches reuse the same company.")}<button class="primary" type="submit">Create company</button></form></section>
    <aside class="example"><div class="eyebrow">Try the complete workflow</div><h2>Explore a retail example</h2><p class="small">One retailer. Stock availability cases across Jira, ServiceNow and email. Twenty-four requested evaluations.</p><ol class="small"><li>Inspect the company and process definitions.</li><li>Run the operational use case.</li><li>Explore qualified queries and their evidence.</li></ol>${button("Load retail example","example","primary")}<p class="help">An authored starting example. No customer data.</p></aside></div></main>`;
}
function render() {
  if (!state.company) { $("#app").innerHTML=onboarding();return; }
  const p=state.company;
  const page=navItems.find(([key])=>key===state.page)?.[1];
  $("#app").innerHTML=`<div class="shell"><aside class="sidebar"><div class="wordmark">worldloom <span>STUDIO</span></div><div class="company-select"><label class="sr-only" for="company-switch">Company workspace</label><select id="company-switch">${state.projects.map(c=>option(c.id,companyName(c),p.id)).join("")}</select></div><nav class="nav" aria-label="Company workspace">${navItems.map(([key,title])=>`<button type="button" data-page="${key}" class="${state.page===key?"active":""}" ${state.page===key?'aria-current="page"':""}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">${icons[key]}</svg>${title}</button>`).join("")}</nav><div class="sidebar-bottom">One company per dataset.<br>Every run keeps its revision.${button("+ New company","new-company")}</div></aside><div class="main-shell"><header class="topbar"><div class="breadcrumb">Company workspace &nbsp;/&nbsp; <strong>${esc(page)}</strong></div><div class="actions">${badge(`Revision ${p.ordinal}`)}${button(state.harness?"Harness configured":"Connect harness","harness","quiet")}</div></header><main id="main" class="workspace">${({overview:overview,company:companyPage,interview:interviewPage,usecases:usecasesPage,evals:evalsPage,changes:changesPage}[state.page])()}</main></div></div>`;
}
function journey() {
  const p=state.company,r=report();
  return `<nav class="journey" aria-label="Build workflow">${[["interview","01 · Understand",p.interviews.length?"Continue interview":"Interview"],["company","02 · Model","Company & processes"],["usecases","03 · Specify",`${p.spec.use_cases.length} use cases`],["changes","04 · Generate","Evidence & runs"],["evals","05 · Evaluate",r?`${fmt(r.accepted)} qualified queries`:"Evaluations"]].map(([key,step,title])=>`<button type="button" data-page="${key}"><span>${step}</span>${title}</button>`).join("")}</nav>`;
}
function overview() {
  const p=state.company,s=p.spec,r=report();
  return head(esc(companyName(p)),`${label(s.company.engine)} · ${label(s.company.geo)} · One persistent enterprise`,button("Continue interview","go-interview")+button("Generate evalset","compile","primary",!p.ready?"disabled":""))+journey()+
    `<div class="stats">${[["Company","1","Shared identity across every batch"],["Business units",s.structure?.bus.length||0,"Declared operating structure"],["Use cases",s.use_cases.length,`${fmt(s.use_cases.reduce((n,c)=>n+c.count,0))} requested queries`],["Qualified queries",r?.accepted||0,r?`${r.tasks} task fingerprints · ${r.cases} evidence cases`:"Run generation to measure coverage"]].map(([name,value,detail])=>`<div class="stat"><div class="label">${name}</div><strong>${fmt(value)}</strong><p>${detail}</p></div>`).join("")}</div><div class="two-col"><section class="panel"><div class="panel-head"><div><h2>Company map</h2><p class="muted small">The business context behind your evaluations.</p></div>${button("Explore","go-company")}</div>${companyMap()}</section><div class="stack"><section class="panel"><div class="panel-head"><div><h2>Ready for the next run?</h2><p class="muted small">Declarations and measured results stay distinct.</p></div></div>${findings()}</section><section class="panel"><div class="panel-head"><h2>Recent runs</h2>${button("View all","go-changes","quiet")}</div><div id="run-list">${runList(3)}</div></section></div></div>`;
}
function companyMap() {
  const s=state.company.spec,rows=state.company.processes?.rows||[];
  return `<div class="company-root"><h3>${esc(companyName(state.company))}</h3><p>${esc(label(s.structure?.operating_model||"Operating model not defined"))}</p></div>${s.structure?`<div class="unit-grid">${s.structure.bus.map(b=>`<div class="unit"><h3>${esc(b.name)}</h3><small>${esc(label(b.archetype))} · ${esc((b.countries.length?b.countries:s.structure.countries).join(", "))}</small><div class="counts">${rows.filter(r=>r.owner_bu===b.name).length} process definitions &nbsp;·&nbsp; ${s.use_cases.filter(c=>c.owner===b.name).length} use cases</div></div>`).join("")}</div>`:`<div class="empty"><h2>Map how this company operates</h2><p>Add business units and their responsibilities in the interview.</p>${button("Start interview","go-interview","primary")}</div>`}`;
}
function findings() {
  const f=state.company.findings;
  return f.length?`<ul class="findings">${f.map(v=>`<li>${badge(v.acknowledged?"Acknowledged limit":"Needs input",v.acknowledged?"":"amber")}<p class="small muted">${esc(v.message)}</p></li>`).join("")}</ul>`:`<div class="callout">The declared use cases have source contracts. Generation will independently check evidence and executable outcomes.</div>`;
}
function runList(limit=100) {
  const jobs=state.company.jobs.slice(0,limit);
  if(!jobs.length)return '<p class="muted small">No runs yet. Build the company or generate its evalset.</p>';
  return jobs.map(j=>{const r=j.result?.report;return `<div class="run-row"><div class="spaced"><strong>${esc(label(j.options.operation))}${j.revision!==state.company.revision?' · earlier revision':""}</strong>${badge(j.status==="complete"&&r&&!r.complete?"Coverage incomplete":label(j.status),j.status==="failed"?"red":j.status==="complete"?r&&!r.complete?"amber":"green":"blue")}</div>${r?`<p>${fmt(r.accepted)} / ${fmt(r.target)} queries · ${r.companies} company · ${r.batches} batches</p><progress value="${r.accepted}" max="${r.target}" aria-label="Qualified query quota"></progress>`:""}${j.result?.company?`<p>${esc(j.result.company)} · ${fmt(j.result.facts)} facts · ${fmt(j.result.artifacts)} artifacts</p>`:""}${j.result?.narrated?button(state.company.spec.narration_job===j.id?"Narration selected":"Use this narration","select-narration","quiet",`data-id="${j.id}" ${state.company.spec.narration_job===j.id?"disabled":""}`):""}${j.error?`<p>${esc(j.error)}</p>`:""}${["failed","interrupted"].includes(j.status)?button("Retry from checkpoint","retry","quiet",`data-id="${j.id}"`):""}${r?.findings?.length?`<details><summary>Remaining coverage</summary><ul class="small">${r.findings.map(f=>`<li>${esc(f)}</li>`).join("")}</ul></details>`:""}</div>`;}).join("");
}
function companyPage() {
  const p=state.company,s=p.spec;
  return head("Company & processes","Describe the enterprise once. Keep generated evidence tied to that identity.",button("Edit full contract","edit-project")+button("Build company","build","primary"))+
    `<div class="two-col"><div class="stack"><section class="panel"><div class="panel-head"><div><h2>Company profile</h2><p class="muted small">Changes are saved as a new revision.</p></div></div><form id="profile-form"><div class="form-grid">${field("Company name","name",companyName(p))}${field("Geography","geo",s.company.geo||"")}${field("Employees","employees",s.company.employees||"","number","Organisation size, not a record-generation quota.")}${field("Industry description","industry",s.company.industry||"")}</div><div class="field"><label for="about">How does this company operate?</label><textarea id="about" name="about" rows="3">${esc(s.company.about||"")}</textarea></div><button type="submit" class="primary">Save profile revision</button></form></section>
    <section class="panel"><div class="panel-head"><div><h2>Revenue divisions</h2><p class="muted small">This contract drives the generated divisions, books and sites.</p></div>${button("Edit divisions","edit-divisions")}</div><div class="unit-grid">${p.division_contract.map(u=>`<div class="unit"><h3>${esc(u.name)}</h3><small>${esc(label(u.kind))} · ${Math.round(u.share*100)}% revenue share</small><div class="counts">${u.categories.length} categories · ${u.site_formats.reduce((n,f)=>n+f.count,0)} declared sites</div></div>`).join("")}</div></section>
    <section class="panel"><div class="panel-head"><div><h2>Business units</h2><p class="muted small">Process ownership and company footprint.</p></div>${button("Edit structure","edit-structure")}</div>${companyMap()}</section>
    <section class="panel"><div class="panel-head"><div><h2>Lines of business</h2><p class="muted small">Accepted LOB roles enter the generated organisation.</p></div>${button("Edit LOBs","edit-lobs")}</div>${s.lobs.length?s.lobs.map(l=>`<div class="unit"><h3>${esc(l.title)}</h3><p class="small muted">${esc(l.purpose)}</p>${badge(`${l.roles.length} roles`)} ${badge(`${l.responsibilities.length} responsibilities`)}</div>`).join(""):'<p class="muted small">No additional LOB roles defined. Use the interview to author roles and process responsibilities.</p>'}</section></div>
    <aside class="stack"><section class="panel"><h2>Evidence timeline</h2><p class="muted small">Extend the same company through its registered domain episodes.</p>${s.episodes.length?`<ol class="small">${s.episodes.map(e=>`<li>${esc(e)}</li>`).join("")}</ol>`:'<p class="small muted">No domain episodes yet. Operational use cases can still generate their declared microdata.</p>'}<form id="episode-form">${field("Next period","period","","month")}<button type="submit">Add period</button></form></section><section class="panel"><h2>Generation boundaries</h2><dl class="definition"><dt>Engine</dt><dd>${esc(s.company.engine)}</dd><dt>Seed</dt><dd>${s.seed}</dd><dt>Batch budget</dt><dd>${s.max_batches}</dd><dt>Split policy</dt><dd>${esc(s.split_by)} isolation</dd></dl><hr>${findings()}</section></aside></div><section class="panel" id="process-panel"><div class="panel-head"><div><h2>Process catalogue</h2><p class="muted small">Authored definitions mapped to this company. These counts do not claim simulated transactions.</p></div></div><div class="filters"><input id="process-filter" aria-label="Search processes" placeholder="Search activity, unit or system…" value="${esc(state.filter)}"></div><div id="process-table">${processTable()}</div></section>`;
}
function processTable() {
  const all=state.company.processes?.rows||[],rows=all.filter(r=>`${r.activity} ${r.owner_bu} ${r.stream_name} ${r.sor_product}`.toLowerCase().includes(state.filter.toLowerCase())).slice(0,100);
  if(!all.length)return '<p class="muted small">Define the operating structure to bind the process catalogue.</p>';
  return `<div class="table-wrap"><table><thead><tr><th>Activity / stream</th><th>Owner</th><th>System</th><th>Binding</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(r.activity)}</strong><br><span class="muted tiny">${esc(r.stream_name)}</span></td><td>${esc(r.owner_bu)}<br><span class="muted tiny">${esc(r.country)}</span></td><td>${esc(r.sor_product)}<br><span class="muted tiny">${esc(r.sor_objects.join(", "))}</span></td><td>${badge(label(r.binding_status),r.binding_status==="bound"?"":"amber")}</td></tr>`).join("")}</tbody></table></div><p class="help">Showing ${rows.length} of ${all.length} authored activity bindings. Filter to narrow.</p>`;
}
function interviewPage() {
  const turns=state.company.interviews;
  return head("Interview the company","Work with your coding harness to turn business context into a reviewable company and eval contract.")+`<div class="two-col"><section class="panel"><div class="chat" id="chat">${turns.length?turns.map(t=>`<div class="message user"><div class="role">You</div><p>${esc(t.request.message)}</p></div>${t.reply?`<div class="message assistant"><div class="role">Coding harness</div><p>${esc(t.reply.message)}</p>${t.reply.questions.length?`<ul>${t.reply.questions.map(q=>`<li>${esc(q)}</li>`).join("")}</ul>`:""}${t.reply.proposal?button("Review proposed changes","review-proposal","primary",`data-id="${t.id}"`):""}</div>`:`<div class="message assistant"><div class="role">Request ready</div><p class="muted">Waiting for a harness response.</p>${button("Download request","download-request","quiet",`data-id="${t.id}"`)}</div>`}`).join(""):`<div class="message assistant"><div class="role">Company interview</div><h2>What work should this company evaluate?</h2><p>Describe the business units, the systems they use, and a few real tasks. Include what a successful outcome looks like.</p><p class="muted small">Your coding harness can ask follow-up questions and propose a contract. You review changes before applying them.</p></div>`}</div><form id="interview-form" class="composer"><label for="interview-message">Company context or answer</label><textarea id="interview-message" name="message" maxlength="8000" placeholder="We operate 80 stores and an online business. Replenishment teams investigate stockouts using…" required></textarea><div class="actions"><div>${button("Import response","import-response")}<input class="sr-only" type="file" id="response-file" accept="application/json,.json" aria-label="Import harness response"></div><div class="actions"><button type="submit" name="mode" value="export">Export request</button><button type="submit" name="mode" value="harness" class="primary" ${!state.harness?"disabled":""}>Send to harness</button></div></div></form></section><aside class="stack"><section class="panel"><h2>Interview coverage</h2><ul class="findings">${[["Company & geography",true],["Operating structure",!!state.company.spec.structure],["LOB roles",!!state.company.spec.lobs.length],["Use cases & outcomes",!!state.company.spec.use_cases.length],["Executable source contracts",state.company.spec.use_cases.length>0&&state.company.spec.use_cases.every(c=>c.scenario)]].map(([title,done])=>`<li class="spaced"><span>${title}</span>${badge(done?"Defined":"Open",done?"green":"")}</li>`).join("")}</ul><p class="help">Defined means declared. Generation and qualification establish what the evidence supports.</p></section><section class="panel"><h2>Your harness stays the writer</h2><p class="small muted">Use the request and response files with Codex, Claude Code or another coding harness. A configured adapter enables the Send button.</p>${button("Connection details","harness")}</section></aside></div>`;
}
function usecasesPage() {
  const cases=state.company.spec.use_cases;
  return head("Use cases → evaluations","Specify business outcomes. The compiler generates and checks the evidence needed to evaluate them.",button("Add use case","add-case")+button("Generate evalset","compile","primary",!state.company.ready?"disabled":""))+
    (cases.length?cases.map(c=>`<article class="usecase"><div class="usecase-top"><div><div class="eyebrow">${esc(c.owner||"Company-wide")}${c.lob?` / ${esc(c.lob)}`:""}</div><h2>${esc(c.title)}</h2></div>${badge(c.scenario?"Contract defined":"Needs workflow",c.scenario?"blue":"amber")}</div><p>${esc(c.objective)}</p><div class="usecase-meta">${badge(`${c.count} requested queries`)}${badge(c.simulation?"Operational evidence":"Company records")}${c.scenario?.connectors.map(v=>badge(v)).join("")||""}</div>${c.activities.length?`<p class="help">Process activities: ${esc(c.activities.join(", "))}</p>`:""}<div class="foot"><span class="small muted">${esc(c.scenario?.workflows.join(", ")||"No executable workflow selected")}</span><div class="actions">${button("Edit use case","edit-case","",`data-id="${c.id}"`)}${button("Inspect contract","inspect-case","quiet",`data-id="${c.id}"`)}</div></div></article>`).join(""):`<div class="empty"><h2>Start with the work</h2><p>Define a task, its owning team and a verifiable outcome.</p>${button("Add use case","add-case","primary")}</div>`)+`<div class="callout">One company can contain many different business situations. New names and row counts do not earn task diversity. Missing evidence keeps an evalset incomplete.</div>`;
}
function evalsPage() {
  const r=report();
  return head("Evaluations","Inspect the exact queries, ownership and evidence admitted by the compiler.",button("Refresh queries","load-evals")+button("Generate evalset","compile","primary",!state.company.ready?"disabled":""))+
    (r?`<div class="stats">${[["Qualified queries",r.accepted,`${r.target} requested`],["Task fingerprints",r.tasks,"Executable contracts"],["Evidence cases",r.cases,"Shared evidence stays in one split"],["Company",r.companies,"One canonical company snapshot"]].map(([name,v,d])=>`<div class="stat"><div class="label">${name}</div><strong>${fmt(v)}</strong><p>${d}</p></div>`).join("")}</div><div class="spaced"><div class="actions">${Object.entries(r.split_counts).map(([name,count])=>badge(`${name}: ${count}`)).join("")}</div>${badge(r.complete?"Evalset complete":"Coverage incomplete",r.complete?"green":"amber")}</div><br>`:"")+
    `<section class="panel">${state.evals.length?state.evals.map(q=>`<article class="query-card"><div class="query-top">${badge(q.split,"blue")}${badge(label(q.dimensions.workflow))}${badge(label(q.dimensions.failure))}<span class="identity">${esc(q.id.slice(0,12))}</span></div><p>${esc(q.query)}</p><div class="usecase-meta"><span>Use case: ${esc(q.lineage?.use_case||q.stratum)}</span><span>Owner: ${esc(q.lineage?.business_unit||"Company-wide")}</span><span>Task: <code>${esc(q.task_id.slice(0,10))}</code></span></div><details><summary>Evidence and lineage</summary><dl class="definition"><dt>Company</dt><dd><code>${esc(q.company_id)}</code></dd><dt>Evidence case</dt><dd><code>${esc(q.case_id)}</code></dd><dt>Source records</dt><dd>${q.evidence.length} shared evidence keys</dd><dt>Qualification</dt><dd><code>${esc(q.qualification)}</code></dd><dt>Revision</dt><dd><code>${esc(q.lineage?.revision||"")}</code></dd></dl>${button("Inspect source evidence","inspect-evidence","",`data-id="${esc(q.id)}"`)}</details></article>`).join(""):`<div class="empty"><h2>${r?"Load the generated queries":"No evaluations generated yet"}</h2><p>${r?"Inspect qualified rows and their company lineage.":"Generate an evalset from the company’s use cases. Incomplete runs retain candidates for review."}</p>${button(r?"Load queries":"Go to use cases",r?"load-evals":"go-usecases","primary")}</div>`}${state.evals.length?`<div class="actions end">${button("Previous","eval-prev","",state.offset===0?"disabled":"")}<span class="small muted">${state.offset+1}–${state.offset+state.evals.length}</span>${button("Next","eval-next","",state.evals.length<25?"disabled":"")}</div>`:""}</section>`;
}
function changesPage() {
  return head("Changes & runs","Every revision preserves its intent. Every run keeps its original company snapshot.",button("Refresh history","load-history")+button("Build company","build","primary"))+
    `<div class="two-col"><section class="panel"><div class="panel-head"><h2>Company history</h2></div>${state.history.length?state.history.map(h=>`<article class="revision"><div class="spaced"><h3>Revision ${h.ordinal} · ${esc(h.reason)}</h3>${h.revision===state.company.revision?badge("Current","blue"):button("Inspect","inspect-revision","quiet",`data-id="${h.revision}"`)}</div><p>${h.spec.use_cases.length} use cases · ${h.spec.episodes.length} periods · ${h.spec.structure?.bus.length||0} business units</p><span class="identity tiny muted"><code>${esc(h.revision)}</code></span></article>`).join(""):`<p class="muted small">Revision ${state.company.ordinal}: ${esc(state.company.reason)}</p>${button("Load revision history","load-history")}`}<details><summary>What changed in the current revision?</summary><ul class="change-list">${state.company.changes.map(c=>`<li><code>${esc(c.path)}</code></li>`).join("")}</ul></details></section><section class="panel"><div class="panel-head"><h2>Run ledger</h2>${button("Narrate evidence","narrate","quiet",!state.harness?"disabled":"")}</div><div id="run-list">${runList()}</div></section></div>`;
}
function jsonEditor(title, value, kind) {
  modal(title, `<p class="muted small">The full typed contract is validated before a new revision is saved.</p><form id="json-form" data-kind="${kind}"><label for="json-value">Contract JSON</label><textarea id="json-value" name="value" class="code" spellcheck="false">${esc(pretty(value))}</textarea>${field("Reason for change","reason","Updated "+title.toLowerCase())}<div class="actions end"><button type="submit" class="primary">Validate & save revision</button></div></form>`);
}
async function caseEditor(id) {
  const s=state.company.spec,existing=s.use_cases.find(c=>c.id===id);
  const units=s.structure?.bus||[];
  const patterns=[...["retail","banking"].includes(s.company.engine)?[["operational","Operational "+label(s.company.engine)+" review"]]:[],...state.catalogue.workflows.map(w=>[w.name,label(w.name)])];
  modal(existing?"Edit use case":"Add a use case",`<form id="case-form" data-id="${esc(id||"")}"><div class="form-grid">${field("Title","title",existing?.title||"")}${field("Stable use case ID","id",existing?.id||"","text","Lowercase letters, numbers and hyphens.")}</div><div class="field"><label for="case-objective">Business outcome</label><textarea id="case-objective" name="objective" rows="3" required>${esc(existing?.objective||"")}</textarea></div><div class="form-grid"><div class="field"><label for="case-owner">Owning business unit</label><select name="owner" id="case-owner">${option("","Company-wide",existing?.owner||"")}${units.map(b=>option(b.name,b.name,existing?.owner)).join("")}</select></div>${field("Requested evaluations","count",existing?.count||12,"number")}<div class="field"><label for="case-pattern">Executable workflow</label><select id="case-pattern" name="pattern">${existing?option("keep","Keep current contract","keep"):option("draft","Define in interview","draft")}${patterns.map(([key,title])=>option(key,title,"")).join("")}</select></div><div class="field"><label for="case-lob">Line of business</label><select id="case-lob" name="lob">${option("","None",existing?.lob||"")}${s.lobs.map(l=>option(l.name,l.title,existing?.lob)).join("")}</select></div></div>${field("Process activity IDs","activities",existing?.activities.join(", ")||"","text","Optional comma-separated IDs from this owner's process catalogue.")}<p class="help">Operational examples declare their own volumes. Inspect the contract to tune tables, periods, connector requirements and expected outcomes.</p><hr><div class="actions end">${existing?button("Remove use case","remove-case","danger",`data-id="${esc(existing.id)}"`):""}<button type="submit" class="primary">Save use case</button></div></form>`);
}
async function loadEvals() { const data=await api(route("evals")+`?offset=${state.offset}`);state.evals=data.rows;render(); }
async function run(operation, message="") { const job=await api(route("run"), {revision:state.company.revision, options:{operation,message}});await refresh();render();notify(`${label(operation)} queued. You can keep exploring while it runs.`);return job; }
async function action(name, target) {
  if(name.startsWith("go-")){state.page=name.slice(3);render();return;}
  if(name==="close"){$("#editor").close();return;}
  if(name==="new-company"){state.company=null;render();return;}
  if(name==="example"){const spec=await api("/api/preset");const p=await api("/api/projects",spec);state.projects.push(p);await selectCompany(p.id);return;}
  if(name==="harness"){modal("Connect your coding harness",`<p>Use your installed, signed-in Codex or Claude Code CLI. Studio sends bounded requests and validates the returned proposals.</p><pre>worldloom studio serve --harness codex
worldloom studio serve --harness claude</pre><p class="small muted">Custom adapters can use <code>--harness-command</code>. Commands are configured when Studio starts.</p><p>Without an adapter, use <strong>Export request</strong> and <strong>Import response</strong> in the interview.</p>`);return;}
  if(["compile","build","narrate"].includes(name)){await run(name);return;}
  if(name==="retry"){await api(`/api/jobs/${target.dataset.id}/retry`,{});await refresh();render();return;}
  if(name==="select-narration"){const spec=copy(state.company.spec);spec.narration_job=target.dataset.id;await revise(spec,"Selected accepted narration for evaluation evidence");return;}
  if(name==="edit-divisions"){jsonEditor("Revenue divisions",state.company.division_contract,"divisions");return;}
  if(name==="edit-project"){jsonEditor("Company contract",state.company.spec,"project");return;}
  if(name==="edit-structure"){let structure=state.company.spec.structure;if(!structure){const sample=await api("/api/preset?engine=retail&name="+encodeURIComponent(companyName(state.company)));structure=sample.structure;}jsonEditor("Operating structure",structure,"structure");return;}
  if(name==="edit-lobs"){jsonEditor("Lines of business",state.company.spec.lobs,"lobs");return;}
  if(name==="add-case"||name==="edit-case"){await caseEditor(target.dataset.id);return;}
  if(name==="inspect-case"){jsonEditor("Use case contract",state.company.spec.use_cases.find(c=>c.id===target.dataset.id),"case:"+target.dataset.id);return;}
  if(name==="remove-case"){const spec=copy(state.company.spec);spec.use_cases=spec.use_cases.filter(c=>c.id!==target.dataset.id);await revise(spec,"Removed use case "+target.dataset.id);$("#editor").close();return;}
  if(name==="load-evals"){state.page="evals";await loadEvals();return;}
  if(name==="inspect-evidence"){
    const row=state.evals.find(q=>q.id===target.dataset.id);
    const data=await api(route("evidence")+`?id=${encodeURIComponent(row.id)}&revision=${encodeURIComponent(row.lineage.revision)}`);
    modal("Evaluation evidence",`<p>${esc(data.row.query)}</p><p class="help">Verified against the committed dataset. Showing ${data.records.length} of ${data.total_records} source records. Expected evidence and proof are for operator review.</p><h3>Source records</h3>${data.records.map(record=>`<details><summary>${esc(record.connector)} · ${esc(record.id)}</summary><pre>${esc(pretty(record))}</pre></details>`).join("")}<details><summary>Qualification proof</summary><pre>${esc(pretty(data.proof))}</pre></details><details><summary>Expected facts and evidence</summary><pre>${esc(pretty({facts:data.expected_fact_ids,evidence:data.expected_evidence_ids}))}</pre></details>`);return;
  }
  if(name==="eval-next"||name==="eval-prev"){state.offset=Math.max(0,state.offset+(name==="eval-next"?25:-25));await loadEvals();return;}
  if(name==="load-history"){state.history=await api(route("history"));state.page="changes";render();return;}
  if(name==="inspect-revision"){const r=state.history.find(h=>h.revision===target.dataset.id);modal("Company revision "+r.ordinal,`<p>${esc(r.reason)}</p><pre>${esc(pretty(r.spec))}</pre>`);return;}
  if(name==="import-response"){$("#response-file").click();return;}
  if(name==="download-request"){const t=state.company.interviews.find(t=>t.id===target.dataset.id);download("worldloom-interview-request.json",t.request);return;}
  if(name==="review-proposal"){const t=state.company.interviews.find(t=>t.id===target.dataset.id);const old=await api(route()+"?revision="+t.revision);const deltas=Object.keys(t.reply.proposal).filter(k=>JSON.stringify(t.reply.proposal[k])!==JSON.stringify(old.spec[k]));modal("Review interview proposal",`<p>${esc(t.reply.message)}</p><p class="small">Changes: ${esc(deltas.join(", ")||"No contract changes")}</p>${t.revision!==state.company.revision?'<div class="callout amber">This proposal targets an earlier revision. Continue the interview against the current company before applying changes.</div>':""}<details><summary>Compare full contracts</summary><h3>Current at request</h3><pre>${esc(pretty(old.spec))}</pre><h3>Proposed</h3><pre>${esc(pretty(t.reply.proposal))}</pre></details><div class="actions end">${button("Apply reviewed proposal","apply-proposal","primary",`data-id="${t.id}" ${t.revision!==state.company.revision?"disabled":""}`)}</div>`);return;}
  if(name==="apply-proposal"){await api(route("interview-apply"),{request_id:target.dataset.id});$("#editor").close();await refresh();render();notify("Interview proposal applied as a new revision.");}
}
document.addEventListener("click", async event=>{
  const nav=event.target.closest("[data-page]");if(nav){state.page=nav.dataset.page;state.filter="";render();return;}
  const target=event.target.closest("[data-action]");if(!target||target.disabled)return;
  target.disabled=true;try{await action(target.dataset.action,target);}catch(error){notify(error.message);}finally{target.disabled=false;}
});
document.addEventListener("submit", async event=>{
  event.preventDefault();const form=event.target,values=Object.fromEntries(new FormData(form)),submit=event.submitter;if(submit)submit.disabled=true;
  try {
    if(form.id==="create-form"){
      const spec={company:{engine:values.engine,geo:values.geo,identity:{company_name:values.name.trim()}},seed:Number(values.seed)};
      const p=await api("/api/projects",spec);state.projects.push(p);await selectCompany(p.id);
    } else if(form.id==="profile-form"){
      const spec=copy(state.company.spec);spec.company.identity.company_name=values.name.trim();spec.company.geo=values.geo;spec.company.industry=values.industry;spec.company.about=values.about;
      if(values.employees)spec.company.employees=Number(values.employees);else delete spec.company.employees;
      if(spec.structure)spec.structure.name=values.name.trim();await revise(spec,"Updated company profile");
    } else if(form.id==="episode-form"){
      const spec=copy(state.company.spec);spec.episodes.push(values.period);await revise(spec,"Extended company timeline to "+values.period);
    } else if(form.id==="interview-form"){
      if(submit?.value==="harness")await run("interview",values.message);
      else {const request=await api(route("interview-request"),{revision:state.company.revision,message:values.message});download("worldloom-interview-request.json",request);await refresh();render();}
    } else if(form.id==="json-form"){
      const parsed=JSON.parse(values.value),kind=form.dataset.kind;let spec=copy(state.company.spec);
      if(kind==="project")spec=parsed;else if(kind.startsWith("case:"))spec.use_cases=spec.use_cases.map(c=>c.id===kind.slice(5)?parsed:c);else spec[kind]=parsed;
      await revise(spec,values.reason);$("#editor").close();
    } else if(form.id==="case-form"){
      const spec=copy(state.company.spec),old=spec.use_cases.find(c=>c.id===form.dataset.id);
      let c=old?copy(old):{};
      if(values.pattern==="operational"){const sample=await api("/api/preset?engine="+spec.company.engine+"&name="+encodeURIComponent(companyName(state.company)));c=copy(sample.use_cases[0]);}
      else if(!["keep","draft"].includes(values.pattern)){const workflow=state.catalogue.workflows.find(w=>w.name===values.pattern);c.scenario={name:values.id,industry:spec.company.engine,company_description:spec.company.about||companyName(state.company),workflows:[workflow.name],connectors:[...new Set([...workflow.sources,...workflow.destinations].map(r=>r.connector))],coverage:{failures:["none","partial_write"]}};c.simulation=null;c.incident_rule=null;}
      else if(values.pattern==="draft"){c.scenario=null;c.simulation=null;c.incident_rule=null;}
      Object.assign(c,{id:values.id,title:values.title,objective:values.objective,owner:values.owner,lob:values.lob,count:Number(values.count),activities:values.activities.split(",").map(s=>s.trim()).filter(Boolean)});
      if(old)spec.use_cases=spec.use_cases.map(v=>v.id===old.id?c:v);else spec.use_cases.push(c);
      await revise(spec,`${old?"Updated":"Added"} use case: ${values.title}`);$("#editor").close();
    }
  }catch(error){notify(error.message);}finally{if(submit)submit.disabled=false;}
});
document.addEventListener("change",async event=>{
  try{
    if(event.target.id==="company-switch")await selectCompany(event.target.value);
    if(event.target.id==="response-file"){
      const file=event.target.files[0];if(!file)return;if(file.size>4_000_000)throw new Error("Response exceeds 4 MB");
      await api(route("interview-accept"),JSON.parse(await file.text()));await refresh();render();notify("Response validated. Review any proposed changes before applying them.");
    }
  }catch(error){notify(error.message);}
});
document.addEventListener("input",event=>{if(event.target.id==="process-filter"){state.filter=event.target.value;$("#process-table").innerHTML=processTable();}});
async function poll() {
  if(!state.company||document.hidden||state.pending)return;
  const jobs=state.company.jobs.filter(j=>["queued","running"].includes(j.status));if(!jobs.length)return;
  state.pending=true;
  try{let finished=false;for(const job of jobs){const current=await api(`/api/jobs/${job.id}`);state.company.jobs=state.company.jobs.map(j=>j.id===job.id?current:j);finished ||= !["queued","running"].includes(current.status);}
    if($("#run-list"))$("#run-list").innerHTML=runList(state.page==="overview"?3:100);
    if(finished){await refresh();if(!$("#editor").open&&!document.activeElement?.matches("input,textarea,select"))render();notify("Run finished. Its result is available in Changes & runs.");}
  }catch(error){notify(error.message);}finally{state.pending=false;}
}
async function boot(){try{const data=await api("/api/bootstrap");state.projects=data.projects;state.catalogue=data.catalogue;state.harness=data.harness_configured;if(state.projects.length)await selectCompany(state.projects[0].id);else render();setInterval(poll,2000);}catch(error){$("#app").innerHTML=`<main class="startup"><h1>Workspace unavailable</h1><p>${esc(error.message)}</p><p>Restart Worldloom Studio and reload this page.</p></main>`;}}
boot();
