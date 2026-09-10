// Execute all console views against a real service response, without a browser.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const data = JSON.parse(fs.readFileSync(0, "utf8"));
const elements = new Map();
const listeners = new Map();
const requests = [];
let jobResponse = {};
const document = {
  hidden: false,
  activeElement: null,
  addEventListener(name, callback) {listeners.set(name, callback);},
  querySelector(key) {
    if (!elements.has(key)) elements.set(key, {innerHTML: "", textContent: "", open: false,
      showModal() {this.open = true;}, close() {this.open = false;}});
    return elements.get(key);
  },
};
const context = vm.createContext({document, structuredClone, Blob, URL,
  FormData: class {constructor(form) {return Object.entries(form.values);}},
  setTimeout() {}, setInterval() {},
  fetch: async (path, options) => {
    requests.push({path, body:options.body?JSON.parse(options.body):undefined});
    return {ok:true,json:async()=>path==="/api/bootstrap"
      ? {projects:[data.company],catalogue:data.catalogue,harness_configured:false}
      : path.startsWith("/api/jobs/")?jobResponse:data.company};
  }});
vm.runInContext(fs.readFileSync(new URL("../src/worldloom/studio/static/app.js", import.meta.url), "utf8"), context);
await new Promise(setImmediate);
assert.ok(document.querySelector("#app").innerHTML.includes("Company map"), "bootstrap should render the company");
for (const page of ["overview", "company", "interview", "usecases", "foundry", "native", "evals", "changes"]) {
  vm.runInContext(`state.page = ${JSON.stringify(page)}; render();`, context);
  assert.ok(document.querySelector("#app").innerHTML.includes('id="main"'), page);
}
await vm.runInContext("caseEditor();", context);
assert.ok(document.querySelector("#dialog-content").innerHTML.includes('id="case-form"'));
vm.runInContext("state.page='foundry'; render();", context);
assert.ok(document.querySelector("#app").innerHTML.includes("Publication pending"));
assert.ok(document.querySelector("#app").innerHTML.includes("No target-agent measurements recorded"));
assert.ok(!document.querySelector("#app").innerHTML.includes("Explore frozen evaluations"));
await vm.runInContext("action('edit-calibration',{});", context);
assert.ok(document.querySelector("#dialog-content").innerHTML.includes('id="calibration-form"'));
await listeners.get("submit")({preventDefault(){},target:{id:"calibration-form",values:{cohort:"pilot-v1",target_low:"30",target_high:"70",reader_share:"10",min_support:"20",max_training_attempts:"128",max_holdout_attempts:"64",max_turns:"32",variants:'[{"name":"clean","budget":{},"niche":"baseline"}]',reason:"Measured pilot"}}});
const saved=requests.findLast(r=>r.path.endsWith("/revise"));
assert.deepEqual(saved.body.spec.calibration,{cohort:"pilot-v1",target_low:.3,target_high:.7,reader_share:.1,min_support:20,max_training_attempts:128,max_holdout_attempts:64,max_turns:32,variants:[{name:"clean",budget:{},niche:"baseline"}]});
assert.equal(saved.body.revision,data.company.revision);
await vm.runInContext("action('foundry',{});", context);
assert.equal(requests.findLast(r=>r.path.endsWith("/run")).body.options.operation,"foundry");
vm.runInContext(`state.company=structuredClone(state.company);state.company.jobs=[{id:'foundry-test',revision:state.company.revision,options:{operation:'foundry'},status:'complete',progress:{stage:'selection',status:'holdout_failed',stages:{requirements:{status:'complete'},selection:{status:'holdout_failed'}},calibration:{status:'holdout_failed',selected_variant:'clean',variants:[{name:'clean',training:{review:{trials:20,successes:10,predicted_pass_rate:.5,interval_low:.299,interval_high:.701,status:'fitted',provenance_complete:true}},holdout:{review:{trials:20,successes:0,predicted_pass_rate:.045,interval_low:0,interval_high:.161,status:'fitted',provenance_complete:true}}}]}}}];render();`,context);
let rendered=document.querySelector("#app").innerHTML;
assert.ok(rendered.includes("50.0% estimated pass rate"));
assert.ok(rendered.includes("0 / 20 passed"),"observed zero successes are measured");
assert.ok(rendered.includes("Publication pending"),"failed holdout must remain unpublished");
assert.ok(!rendered.includes("Explore frozen evaluations"));
vm.runInContext(`state.company.jobs[0].progress.report={accepted:22,target:24,tasks:20,cases:22,split_groups:22,remaining:{[state.company.spec.use_cases[0].id]:2}};state.company.jobs[0].progress.stages.quality={status:'complete',variants:{clean:{coverage:{accepted:22,target:24},reader:{review:{passed:false}},findings:['<script>invalid evidence</script>'],requested_noise:{staleness:1},actual_noise:{staleness:1}}}};render();`,context);
rendered=document.querySelector("#app").innerHTML;
assert.ok(rendered.includes("22 / 24 baseline queries qualified"));
assert.ok(rendered.includes("Remaining"));
assert.ok(rendered.includes("Rejected"),"reader rejection must be visible independently of trial outcomes");
assert.ok(!rendered.includes("<script>invalid evidence"),"quality findings must be escaped");
vm.runInContext("state.page='changes';render();",context);
assert.ok(document.querySelector("#app").innerHTML.includes("Not frozen"),"completed execution must not imply a frozen dataset");
jobResponse={revision:data.company.revision,progress:{stages:{selection:{status:"holdout_failed",finding:"held-out interval misses target"}}}};
await vm.runInContext("action('inspect-stage',{dataset:{id:'foundry-test',stage:'selection'}});",context);
assert.ok(document.querySelector("#dialog-content").innerHTML.includes("held-out interval misses target"),"stage inspection must fetch its current checkpoint");
vm.runInContext("state.company.jobs[0].status='interrupted';state.page='foundry';render();",context);
assert.ok(document.querySelector("#app").innerHTML.includes("Resume foundry run"));
await vm.runInContext("action('retry',{dataset:{id:'foundry-test'}});",context);
assert.ok(requests.some(r=>r.path==="/api/jobs/foundry-test/retry"));
vm.runInContext(`state.company=structuredClone(state.company);state.company.jobs=[{id:'frozen-test',revision:state.company.revision,options:{operation:'foundry'},status:'complete',result:{frozen_dataset:'selected-dataset'},progress:{stage:'freeze',status:'complete'}}];state.page='foundry';render();`,context);
assert.ok(document.querySelector("#app").innerHTML.includes("Explore frozen evaluations"));
vm.runInContext("state.company.jobs[0].revision='earlier-revision';render();",context);
assert.ok(!document.querySelector("#app").innerHTML.includes("Explore frozen evaluations"),"old revisions must not supply the current frozen dataset");
await vm.runInContext("state.evals=[{id:'earlier-row'}]; state.history=[{}]; state.company={...state.company,revision:'earlier-revision'}; refresh();", context);
assert.equal(vm.runInContext("state.evals.length + state.history.length", context), 0, "a new revision must clear stale views");
vm.runInContext("state.company.spec.company.identity.company_name = '<img src=x onerror=evil()>'; state.page='overview'; render();", context);
assert.ok(!document.querySelector("#app").innerHTML.includes("<img src=x"), "company input must be escaped");
vm.runInContext("state.company=null; render();", context);
assert.ok(document.querySelector("#app").innerHTML.includes('id="create-form"'));
assert.ok(document.querySelector("#app").innerHTML.includes("Load connected retail pilot"));
process.stdout.write("All seven views, calibration edits, run/resume, measured intervals, publication boundaries and HTML escaping passed.\n");

const nativeSummary=vm.runInContext("nativeCalibrationResults({calibrated:false,calibration:{configured:true,training:{estimates:{read:{use_case_id:'retail',operation:'read',successes:2,trials:4,interval_low:0.1,interval_high:0.9,status:'insufficient_support'}}},findings:['training_not_supported']}})",context);
assert.ok(nativeSummary.includes("Calibration incomplete"));
assert.ok(nativeSummary.includes("2 / 4"));
assert.ok(nativeSummary.includes("training_not_supported"));

vm.runInContext(`state.company=${JSON.stringify(data.company)};state.company.workflow={stages:[{id:'native',title:'Prepare documents',status:'ready',detail:'Accepted company sources are available',action:{kind:'prepare_native',label:'Prepare file evaluations'}}],next_action:{kind:'prepare_native',label:'Prepare file evaluations'},findings:[{message:'<script>unsupported</script>'}]};state.page='overview';render();`,context);
assert.ok(document.querySelector('#app').innerHTML.includes('Your next step'));
assert.ok(document.querySelector('#app').innerHTML.includes('Accepted company sources are available'));
assert.ok(!document.querySelector('#app').innerHTML.includes('<script>unsupported'));
await vm.runInContext(`action('workflow',{dataset:{workflow:JSON.stringify({kind:'prepare_native'})}})`,context);
assert.ok(document.querySelector('#dialog-content').innerHTML.includes('id="native-suite-form"'));
const beforePreparation=requests.filter(r=>r.path.endsWith('/revise')).length;
// Preparation queues work; only an explicitly reviewed completed job supplies a proposal.
const proposalSpec=structuredClone(data.company.spec);
proposalSpec.native_corpus=[];proposalSpec.native_tasks=[];
context.proposalResponse={id:"prepare-test",revision:data.company.revision,status:"queued",options:{operation:"prepare_native"}};
const originalFetch=context.fetch;
context.fetch=async(path,options)=>path.endsWith('/prepare-native')
  ? (requests.push({path,body:JSON.parse(options.body)}),{ok:true,json:async()=>context.proposalResponse})
  : originalFetch(path,options);
await listeners.get('submit')({preventDefault(){},target:{id:'native-suite-form',values:{use_case_id:data.company.spec.use_cases[0].id,format_docx:'on',operation_read:'on',minimum_units:'200',max_cases:'12'}}});
const prepared=requests.findLast(r=>r.path.endsWith('/prepare-native'));
assert.deepEqual(prepared.body.request.formats,['docx']);
assert.deepEqual(prepared.body.request.operations,['read']);
assert.equal(prepared.body.request.minimum_units,200);
assert.equal(requests.filter(r=>r.path.endsWith('/revise')).length,beforePreparation,'preparation must not apply a revision');
assert.equal(document.querySelector('#editor').open,false,'queuing closes preparation form');
assert.equal(vm.runInContext('state.nativeProposal',context),null,'queued work cannot supply an applicable proposal');
jobResponse={id:'prepare-test',revision:data.company.revision,status:'complete',options:{operation:'prepare_native'},result:{revision:data.company.revision,spec:proposalSpec,summary:{tasks:3}}};
context.completedPreparation=jobResponse;
vm.runInContext("state.company.jobs=[completedPreparation];state.page='changes';render()",context);
assert.ok(document.querySelector('#app').innerHTML.includes('Review file proposal'));
await vm.runInContext("action('review-native-proposal',{dataset:{id:'prepare-test'}})",context);
assert.ok(document.querySelector('#dialog-content').innerHTML.includes('Review file evaluation proposal'));
assert.equal(requests.filter(r=>r.path.endsWith('/revise')).length,beforePreparation,'review does not apply a proposal');
await vm.runInContext("action('apply-native-proposal',{})",context);
assert.equal(requests.filter(r=>r.path.endsWith('/revise')).length,beforePreparation+1);
vm.runInContext("state.nativeProposal={spec:state.company.spec,project:state.company.id,revision:'old'}",context);
await assert.rejects(vm.runInContext("action('apply-native-proposal',{})",context),/Company changed/);
await vm.runInContext("action('select-narration',{dataset:{id:'accepted-evidence'}})",context);
assert.equal(requests.findLast(r=>r.path.endsWith('/select-narration')).body.job_id,'accepted-evidence');
await vm.runInContext("action('edit-native-calibration',{})",context);
assert.ok(document.querySelector('#dialog-content').innerHTML.includes('id="native-calibration-form"'));
await listeners.get('submit')({preventDefault(){},target:{id:'native-calibration-form',values:{cohort:'agent-v1',target_low:'30',target_high:'70',min_support:'32',holdout_percent:'25',max_training_attempts:'384',max_holdout_attempts:'128',noise_enabled:'on',noise_name_0:'baseline',noise_files_0:'0',noise_name_1:'context',noise_files_1:'2',reason:'Measure distraction'}}});
assert.deepEqual(requests.findLast(r=>r.path.endsWith('/revise')).body.spec.native_calibration.noise_variants,[{name:'baseline',distractor_files:0},{name:'context',distractor_files:2}]);
const supportSummary=vm.runInContext("nativeCalibrationResults({calibration:{configured:true,support:{train:{a:{use_case_id:'review',operation:'read',available:3,planned:3,required:32}}}}})",context);
assert.ok(supportSummary.includes('29 more independent samples needed'));
process.stdout.write('Guided actions, native proposal review, stale revision protection, narration selection and noise configuration passed.\n');

vm.runInContext("state.company.ready=true;state.company.workflow={capabilities:{connector_ready:false}};state.page='evals';render()",context);
assert.match(document.querySelector('#app').innerHTML,/data-action="compile" disabled/,'native-only contracts cannot enable connector compilation');
vm.runInContext("state.page='foundry';render()",context);
assert.match(document.querySelector('#app').innerHTML,/data-action="foundry" disabled/);
vm.runInContext("state.company.jobs=[{id:'native-blocked',revision:state.company.revision,options:{operation:'native'},status:'complete',result:{status:'blocked'}}];state.page='changes';render()",context);
assert.ok(document.querySelector('#app').innerHTML.includes('badge red">blocked'),'completed native job must show its blocked result');
vm.runInContext("state.company.jobs[0].result.status='prepared';render()",context);
assert.ok(document.querySelector('#app').innerHTML.includes('badge amber">prepared'),'prepared does not claim measured completion');
vm.runInContext("state.nativeProposal={spec:state.company.spec,project:state.company.id,revision:state.company.revision,summary:{tasks:0}}",context);
await assert.rejects(vm.runInContext("action('apply-native-proposal',{})",context),/No executable tasks/);
