// Execute all console views against a real service response, without a browser.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const data = JSON.parse(fs.readFileSync(0, "utf8"));
const elements = new Map();
const document = {
  hidden: false,
  activeElement: null,
  addEventListener() {},
  querySelector(key) {
    if (!elements.has(key)) elements.set(key, {innerHTML: "", textContent: "", open: false,
      showModal() {this.open = true;}, close() {this.open = false;}});
    return elements.get(key);
  },
};
const context = vm.createContext({document, structuredClone, Blob, URL, setTimeout() {}, setInterval() {},
  fetch: async (path) => ({ok: true, json: async () => path === "/api/bootstrap"
    ? {projects: [data.company], catalogue: data.catalogue, harness_configured: false} : data.company})});
vm.runInContext(fs.readFileSync(new URL("../src/worldloom/studio/static/app.js", import.meta.url), "utf8"), context);
await new Promise(setImmediate);
assert.ok(document.querySelector("#app").innerHTML.includes("Company map"), "bootstrap should render the company");
for (const page of ["overview", "company", "interview", "usecases", "evals", "changes"]) {
  vm.runInContext(`state.page = ${JSON.stringify(page)}; render();`, context);
  assert.ok(document.querySelector("#app").innerHTML.includes('id="main"'), page);
}
await vm.runInContext("caseEditor();", context);
assert.ok(document.querySelector("#dialog-content").innerHTML.includes('id="case-form"'));
await vm.runInContext("state.evals=[{id:'earlier-row'}]; state.history=[{}]; state.company={...state.company,revision:'earlier-revision'}; refresh();", context);
assert.equal(vm.runInContext("state.evals.length + state.history.length", context), 0, "a new revision must clear stale views");
vm.runInContext("state.company.spec.company.identity.company_name = '<img src=x onerror=evil()>'; state.page='overview'; render();", context);
assert.ok(!document.querySelector("#app").innerHTML.includes("<img src=x"), "company input must be escaped");
vm.runInContext("state.company=null; render();", context);
assert.ok(document.querySelector("#app").innerHTML.includes('id="create-form"'));
process.stdout.write("All six views, create/edit surfaces and HTML escaping passed.\n");
