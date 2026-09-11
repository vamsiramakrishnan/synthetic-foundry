/* Creation controls share the same revisioned service as the SDK. */
"use strict";
const creationState = {proposal:null, simulations:[], selectedSources:new Set(), sources:null,
  sourceSearch:"", sourceOffset:0, suiteContext:null, tab:"corpus", queries:null,
  queryOperation:"", queryFormat:"", queryUseCase:"", queryOffset:0, sourceRequest:0, queryRequest:0,
  corpusOffset:0,corpusFormat:""};
function resetCreation() {
  creationState.sourceRequest++;creationState.queryRequest++;
  Object.assign(creationState,{proposal:null,simulations:[],sources:null,sourceSearch:"",sourceOffset:0,
    suiteContext:null,queries:null,queryOperation:"",queryFormat:"",queryUseCase:"",queryOffset:0,corpusOffset:0,corpusFormat:""});
  creationState.selectedSources.clear();
}
function creationScope() { return {project:state.company.id,revision:state.company.revision}; }
function sameCreationScope(scope) { return scope?.project===state.company?.id&&scope.revision===state.company?.revision; }
function completedNativeRun() {
  return state.company.jobs.find(j=>j.revision===state.company.revision&&j.options.operation==="native"&&j.status==="complete"&&j.result?.corpus_artifacts);
}
function creationPage() {
  const s=state.company.spec,job=completedNativeRun(),r=job?.result;
  const metric=(title,value,detail)=>`<div class="stat"><div class="label">${title}</div><strong>${fmt(value)}</strong><p>${detail}</p></div>`;
  return head("Create data & evals","Size the company world, select its evidence, then generate executable evaluations.",button("Connector results","go-evals")+button("Size company data","size-data","primary"))+
    `<div class="stats">${metric("Company periods",s.episodes.length,"Declared monthly history")}${metric("Requested connector queries",s.use_cases.filter(c=>c.scenario).reduce((n,c)=>n+c.count,0),"Demand, not measured coverage")}${metric("Generated corpus files",r?.artifacts||0,job?"Completed run; verified on access":"No file run for this revision")}${metric("Observed target trials",r?.observed_trials||0,r?.calibrated?"Difficulty band verified":"Difficulty not verified")}</div>
    <div class="creation-steps"><section class="panel"><div class="eyebrow">01 · Company data</div><h2>Define scale and history</h2><p class="small muted">Resize existing business mechanisms and set query demand. Review row counts before applying a revision.</p>${button("Configure data","size-data")}${button("Build company history","build","quiet")}<p class="help">Operational records materialize during connector generation; company history supplies the file corpus.</p></section>
    <section class="panel"><div class="eyebrow">02 · Grounded corpus</div><h2>Choose evidence and file size</h2><p class="small muted">Select accepted source artifacts. Distinct sections become documents, slides and worksheets—without filler.</p>${button("Select sources & prepare","prepare-native")}${!s.narration_job?`<p class="help">Accepted narration is required. ${button("Review next step","go-overview","quiet")}</p>`:""}</section>
    <section class="panel"><div class="eyebrow">03 · Executable evals</div><h2>Generate and verify</h2><p class="small muted">Run connector workflows or read, analyze, update and create file tasks. Reference qualification and target-agent performance are reported separately.</p>${button("Generate connector queryset","compile","",!connectorReady()?"disabled":"")}${button(state.harness?"Generate & evaluate":"Generate file queryset","native","primary",!s.native_corpus.length||!s.native_tasks.length?"disabled":"")}</section></div>
    <section class="panel creation-results"><div class="panel-head"><div><h2>Corpus & evaluation workspace</h2><p class="small muted">${job?`${fmt(r.tasks)} reference-qualified tasks · ${fmt(r.evidence_components)} independent evidence components · ${esc(label(r.status))}`:"Contracts are plans until the file run succeeds."}</p></div>${button("Difficulty settings","edit-native-calibration","quiet")}</div>
    <div class="tabs" role="group" aria-label="Creation results">${[["corpus","Corpus files"],["queries","File evaluations"]].map(([key,title])=>button(title,"creation-tab",creationState.tab===key?"active":"",`data-tab="${key}" aria-pressed="${creationState.tab===key}"`)).join("")}</div>
    ${creationState.tab==="corpus"?creationCorpus(job):creationQueries(job)}</section>`;
}
function creationCorpus(job) {
  if(!job){const plans=state.company.spec.native_corpus;return `<div class="empty"><h3>${plans.length?`${fmt(plans.length)} file plans ready to generate`:"No corpus prepared yet"}</h3><p>Choose accepted sources, review the proposed tasks, then generate the actual files.</p>${button("Prepare grounded corpus","prepare-native","primary")}</div>`;}
  const artifacts=Object.entries(job.result.corpus_artifacts).filter(([,a])=>!creationState.corpusFormat||a.format===creationState.corpusFormat);
  const offset=creationState.corpusOffset,page=artifacts.slice(offset,offset+12);
  const titles=Object.fromEntries(state.company.spec.native_corpus.map(p=>[p.artifact_id,p.title]));
  return `<div class="query-filters"><div class="field"><label for="creation-corpus-format">File format</label><select id="creation-corpus-format">${option("","All formats",creationState.corpusFormat)}${["docx","pptx","xlsx"].map(v=>option(v,v.toUpperCase(),creationState.corpusFormat)).join("")}</select></div><p class="small muted">${fmt(artifacts.length)} matching files</p></div><p class="help">Downloads authenticate the run and file checksums. Content units are sections, slides or worksheet evidence rows; they are not interchangeable with pages.</p><div class="corpus-grid">${page.map(([id,a])=>`<article class="corpus-card"><div class="spaced">${badge(a.format.toUpperCase(),"blue")}${badge("Generated","green")}</div><h3>${esc(a.title||titles[id]||id)}</h3><dl class="corpus-metrics"><div><dt>Content units</dt><dd>${fmt(a.content_units)}</dd></div><div><dt>Distinct facts</dt><dd>${fmt(a.distinct_fact_count)}</dd></div></dl><p class="identity tiny muted">${esc(id)}</p><a href="${route("native-artifact")}?job=${encodeURIComponent(job.id)}&artifact=${encodeURIComponent(id)}" download="${esc(id)}.${esc(a.format)}">Download ${esc(a.format.toUpperCase())}</a></article>`).join("")||'<p>No generated files match this format.</p>'}</div><div class="actions end">${button("Previous files","corpus-page","",`data-offset="${Math.max(0,offset-12)}" ${offset===0?"disabled":""}`)}${button("Next files","corpus-page","",`data-offset="${offset+12}" ${offset+12>=artifacts.length?"disabled":""}`)}</div>`;
}
function creationQueries(job) {
  if(!job)return '<div class="empty"><h3>Generate files to inspect their queryset</h3><p>Only tasks from completed, authenticated runs appear here.</p></div>';
  const q=creationState.queries?.job===job.id?creationState.queries:null;
  const select=(id,title,values,current)=>`<div class="field"><label for="${id}">${title}</label><select id="${id}">${option("","All",current)}${values.map(([v,t])=>option(v,t,current)).join("")}</select></div>`;
  return `<div class="query-filters">${select("creation-operation","Operation",["read","analyze","update","create"].map(v=>[v,label(v)]),creationState.queryOperation)}${select("creation-format","Format",["docx","pptx","xlsx"].map(v=>[v,v.toUpperCase()]),creationState.queryFormat)}${select("creation-use-case","Use case",state.company.spec.use_cases.map(c=>[c.id,c.title]),creationState.queryUseCase)}${button(q?"Refresh":"Load queryset","load-native-queries","primary")}</div>
    <p class="help">Public task instructions only. Expected answers and private grading oracles are not included. Reference qualification does not measure target-agent success.</p>
    ${q?`<p class="small">${fmt(q.total)} matching tasks of ${fmt(q.unfiltered_total)} · ${fmt(q.observed_trials)} target trials recorded</p>${q.rows.map(row=>`<article class="query-card"><div class="query-top">${badge(label(row.operation),"blue")}${badge([...row.inputs.map(i=>i.format),...(row.output?[row.output.format]:[])].map(v=>v.toUpperCase()).filter((v,i,a)=>a.indexOf(v)===i).join(" / "))}${badge(label(row.split||"unassigned"))}<span class="small muted">${esc(row.use_case_id)}</span></div><p>${esc(row.prompt)}</p><div class="identity">${esc(row.id)} · Evidence component ${esc(row.evidence_component)}</div><details><summary>Public execution contract</summary><pre>${esc(pretty(row))}</pre></details></article>`).join("")||'<div class="empty"><p>No tasks match these filters.</p></div>'}<div class="actions end">${button("Previous","native-query-page","",`data-offset="${Math.max(0,q.offset-25)}" ${q.offset===0?"disabled":""}`)}${button("Next","native-query-page","",`data-offset="${q.next_offset??0}" ${q.next_offset===null?"disabled":""}`)}</div>`:""}`;
}
async function dataEditor() {
  const scope=creationScope(),data=await api(route("creation")+`?revision=${encodeURIComponent(scope.revision)}`);
  if(!sameCreationScope(scope))throw new Error("Company changed. Reopen data settings.");
  creationState.simulations=data.simulations||[];creationState.proposal=null;
  const s=state.company.spec;
  modal("Size company data",`<p class="small muted">Plan generation inputs without running the generator. Nothing changes until you review and apply the proposal.</p><form id="data-creation-form" data-project="${esc(scope.project)}" data-revision="${esc(scope.revision)}">
    <fieldset class="choice-group"><legend>Company history</legend><label><input type="checkbox" name="history_enabled"> Replace the declared monthly timeline</label></fieldset><div class="form-grid">${field("First period","start_period",s.episodes[0]||"2026-01","month")}${field("Number of periods (1–120)","periods",s.episodes.length||12,"number")}</div>
    <fieldset class="choice-group"><legend>Source invalidation</legend><label><input type="checkbox" name="acknowledge_invalidation"> I understand that changing history clears selected narration, file plans, file tasks and native calibration from the new revision.</label></fieldset><p class="help">Earlier revisions and generated files are retained. Rebuild, narrate and prepare fresh file tasks after a history change.</p>
    <hr><div class="field"><label for="data-simulation">Operational data mechanism</label><select name="simulation_target" id="data-simulation">${option("","Keep operational data unchanged","")}${creationState.simulations.filter(v=>v.supported).map(v=>option(v.target,`${label(v.mechanism)} · ${v.target}`,"")).join("")}</select></div><div id="simulation-dimensions"></div>
    ${creationState.simulations.filter(v=>!v.supported).map(v=>`<p class="help">${esc(v.target)}: ${esc(v.reason||"Custom program; edit its contract explicitly.")}</p>`).join("")}
    <hr><h3>Requested connector evaluations</h3><p class="small muted">Demand is not a diversity measurement. File-task coverage is prepared separately from accepted sources.</p><div class="form-grid">${s.use_cases.filter(c=>c.scenario).map(c=>field(esc(c.title),`query_${c.id}`,c.count,"number")).join("")||'<p>No connector workflows are defined.</p>'}</div><div class="actions end"><button type="submit" class="primary">Review data proposal</button></div></form>`);
}
function simulationFields(target) {
  const simulation=creationState.simulations.find(v=>v.target===target);
  if(!simulation)return "";
  return `<div class="form-grid">${Object.entries(simulation.dimensions).map(([key,value])=>field(label(key),key,value,"number")).join("")}</div><p class="help">Current program: ${fmt(simulation.total_rows)} declared rows. Resizing preserves authored parameter values. These rows are operational records, not independent evidence components.</p>`;
}
function reviewDataProposal(proposal) {
  creationState.proposal=proposal;
  const s=proposal.summary,invalidated=s.invalidated;
  modal("Review data creation proposal",`<p>Apply generation inputs as a new company revision. This proposal has not generated files or measured query diversity.</p>
    ${s.history.changed?`<div class="callout amber">Company history changes. ${fmt(invalidated.native_corpus)} file plans and ${fmt(invalidated.native_tasks)} file tasks will be cleared from the new revision. Selected narration and native calibration must be renewed.</div>`:""}
    ${s.simulation?`<h3>${esc(label(s.simulation.mechanism))}</h3><div class="table-wrap"><table><caption>Planned program rows</caption><thead><tr><th>Table</th><th class="right">Rows</th></tr></thead><tbody>${Object.entries(s.simulation.table_rows).map(([name,count])=>`<tr><td>${esc(name)}</td><td class="right">${fmt(count)}</td></tr>`).join("")}</tbody></table></div><p>${fmt(s.simulation.total_rows)} total operational rows</p>`:""}
    <p>${fmt(s.requested_query_total)} requested connector queries. Actual coverage is measured after generation.</p><ul class="findings">${s.limitations.map(v=>`<li>${esc(v)}</li>`).join("")}</ul><details><summary>Full plan and invalidations</summary><pre>${esc(pretty(s))}</pre></details><div class="actions end">${button("Apply data revision","apply-data-proposal","primary")}</div>`);
}
async function loadSources(offset=0) {
  const scope=creationScope(),request=++creationState.sourceRequest;
  creationState.sources=null;
  if($("#source-selection-list"))$("#source-selection-list").innerHTML='<p class="small muted" role="status">Loading accepted sources…</p>';
  const data=await api(route("native-sources")+`?revision=${encodeURIComponent(scope.revision)}&group_by=artifact&limit=20&offset=${offset}&search=${encodeURIComponent(creationState.sourceSearch)}`);
  if(!sameCreationScope(scope))throw new Error("Company changed. Reopen the source selection.");
  if(request!==creationState.sourceRequest)return false;
  creationState.sources=data;creationState.sourceOffset=offset;return true;
}
function sourceCards() {
  const data=creationState.sources;
  if(data?.status!=="accepted")return `<div class="callout amber">${data?.status==="stale_narration"?"Company history changed. Rebuild and select fresh narration before preparing files.":"No accepted narration selected. Build the company, narrate its evidence, then select the accepted run."}</div>`;
  return `<p class="small muted">${fmt(data.total)} matching source artifacts. Selecting an artifact makes all its accepted sections available to the compiler; shared facts still count as one evidence component.</p><div class="source-cards">${(data.sources||[]).map(a=>`<article class="source-card"><label><input type="checkbox" data-source-id="${esc(a.source_artifact_id)}" ${creationState.selectedSources.has(a.source_artifact_id)?"checked":""}><span>${esc(a.title)}<span class="help">${fmt(a.section_count)} accepted sections · ${fmt(a.fact_ids.length)} distinct facts</span></span></label><p class="small muted">${esc(a.sections.map(s=>s.heading).join(" · "))}</p><details><summary>Source provenance & preview</summary><p class="identity tiny">${esc(a.source_artifact_id)}</p><p class="small">${esc(a.preview)}</p></details></article>`).join("")||'<p>No accepted sources match this search.</p>'}</div><div class="actions end">${button("Previous sources","source-page","",`data-offset="${Math.max(0,creationState.sourceOffset-20)}" ${creationState.sourceOffset===0?"disabled":""}`)}${button("Next sources","source-page","",`data-offset="${data.next_offset??0}" ${data.next_offset===null?"disabled":""}`)}</div>`;
}
async function sourceSuiteEditor() {
  const cases=state.company.spec.use_cases;
  if(!cases.length){state.page="usecases";render();notify("Add a business use case before preparing file evaluations.");return;}
  if(!await loadSources())return;
  const scope=creationScope();creationState.suiteContext=scope;
  const choices=(name,values,title)=>`<fieldset class="choice-group"><legend>${title}</legend>${values.map(v=>`<label><input type="checkbox" name="${name}_${v}" checked> ${esc(label(v))}</label>`).join("")}</fieldset>`;
  modal("Prepare file evaluations",`<form id="native-suite-form" data-project="${esc(scope.project)}" data-revision="${esc(scope.revision)}"><p class="small muted">Choose the business outcome and the accepted company sources that support it. Review the proposed corpus and executable tasks before saving.</p><div class="field"><label for="native-use-case">Business use case</label><select name="use_case_id" id="native-use-case">${cases.map(c=>option(c.id,c.title,cases[0].id)).join("")}</select></div>
    <div class="source-toolbar"><div class="field"><label for="source-search">Search accepted sources</label><input type="search" id="source-search" value="${esc(creationState.sourceSearch)}" maxlength="200" placeholder="Title, section or source ID"></div>${button("Search","search-sources")}${button("Clear selection","clear-sources","quiet")}</div><p id="source-selection-count" class="small">${fmt(creationState.selectedSources.size)} source artifacts selected</p><div id="source-selection-list">${sourceCards()}</div><p class="help">No selection uses all eligible sources for company-wide cases. Scoped use cases require an explicit selection; confirm that the sources support the chosen business unit, LOB and process.</p><hr>
    ${choices("format",["docx","pptx","xlsx"],"File formats")}${choices("operation",["read","analyze","update","create"],"Evaluated operations")}<div class="form-grid">${field("Minimum content units per file","minimum_units",2,"number","A unit is a document section, slide or worksheet evidence row. Up to 10,000; bounded by distinct evidence.")}${field("Maximum evaluation cases","max_cases",12,"number","Up to 256. Each case can produce several format/operation tasks.")}</div><p class="help">Spreadsheet analysis requires comparable numeric facts; unsupported combinations are reported. Large-file requests never manufacture filler.</p><div class="actions end"><button type="submit" class="primary" ${creationState.sources?.status!=="accepted"?"disabled":""}>Prepare proposal</button></div></form>`);
}
async function loadNativeQueries(offset=0) {
  const job=completedNativeRun();if(!job)throw new Error("Generate a file queryset for this revision first.");
  const scope=creationScope(),request=++creationState.queryRequest;
  creationState.queries=null;
  if(state.page==="creation"&&creationState.tab==="queries")render();
  const data=await api(route("native-queryset")+`?job=${encodeURIComponent(job.id)}&offset=${offset}&operation=${encodeURIComponent(creationState.queryOperation)}&format=${encodeURIComponent(creationState.queryFormat)}&use_case_id=${encodeURIComponent(creationState.queryUseCase)}`);
  if(!sameCreationScope(scope))throw new Error("Company changed. Reload its queryset.");
  if(request!==creationState.queryRequest||completedNativeRun()?.id!==job.id)return;
  creationState.queries=data;creationState.queryOffset=offset;render();
}
async function creationAction(name,target) {
  if(name==="corpus-page"){creationState.corpusOffset=Number(target.dataset.offset);render();return true;}
  if(name==="size-data"){await dataEditor();return true;}
  if(name==="apply-data-proposal"){
    const p=creationState.proposal;
    if(!sameCreationScope(p))throw new Error("Company changed. Prepare a fresh data proposal.");
    await revise(p.spec,"Applied reviewed data sizing and query demand");$("#editor").close();state.page="creation";render();return true;
  }
  if(name==="native-sources"){await sourceSuiteEditor();return true;}
  if(name==="search-sources"||name==="source-page"){
    if(name==="search-sources")creationState.sourceSearch=$("#source-search").value;
    if(await loadSources(name==="source-page"?Number(target.dataset.offset):0))$("#source-selection-list").innerHTML=sourceCards();return true;
  }
  if(name==="clear-sources"){
    creationState.selectedSources.clear();$("#source-selection-list").innerHTML=sourceCards();$("#source-selection-count").textContent="0 source artifacts selected";return true;
  }
  if(name==="creation-tab"){
    creationState.tab=target.dataset.tab;render();
    if(creationState.tab==="queries"&&completedNativeRun())await loadNativeQueries();return true;
  }
  if(name==="load-native-queries"||name==="native-query-page"){
    await loadNativeQueries(name==="native-query-page"?Number(target.dataset.offset):0);return true;
  }
  return false;
}
async function creationSubmit(form,values) {
  if(form.id==="native-suite-form"&&!sameCreationScope({project:form.dataset?.project,revision:form.dataset?.revision}))throw new Error("Company changed. Reopen file preparation.");
  if(form.id!=="data-creation-form")return false;
  const scope={project:form.dataset.project,revision:form.dataset.revision};
  if(!sameCreationScope(scope))throw new Error("Company changed. Reopen data settings.");
  const request={query_counts:Object.fromEntries(state.company.spec.use_cases.filter(c=>c.scenario).map(c=>[c.id,Number(values[`query_${c.id}`])]))};
  if(values.history_enabled)Object.assign(request,{start_period:values.start_period,periods:Number(values.periods),acknowledge_invalidation:!!values.acknowledge_invalidation});
  if(values.simulation_target){request.simulation_target=values.simulation_target;for(const key of ["stores","products","borrowers","ticks"])if(values[key]!==undefined)request[key]=Number(values[key]);}
  const proposal=await api(route("prepare-data"),{revision:scope.revision,request});
  if(!sameCreationScope(scope))throw new Error("Company changed. Prepare a fresh data proposal.");
  reviewDataProposal(proposal);return true;
}
async function creationChange(target) {
  if(target.id==="creation-corpus-format"){creationState.corpusFormat=target.value;creationState.corpusOffset=0;render();return true;}
  if(target.id==="data-simulation"){$("#simulation-dimensions").innerHTML=simulationFields(target.value);return true;}
  if(target.dataset?.sourceId){
    if(target.checked)creationState.selectedSources.add(target.dataset.sourceId);else creationState.selectedSources.delete(target.dataset.sourceId);
    $("#source-selection-count").textContent=`${fmt(creationState.selectedSources.size)} source artifacts selected`;return true;
  }
  const filters={"creation-operation":"queryOperation","creation-format":"queryFormat","creation-use-case":"queryUseCase"};
  if(filters[target.id]){creationState[filters[target.id]]=target.value;await loadNativeQueries();return true;}
  return false;
}
