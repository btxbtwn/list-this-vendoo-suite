// Actual pipeline builder/runner; isolated VM with stubbed step I/O and Chrome APIs.
// This does not control Chrome or submit an automation job.
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const src=fs.readFileSync(path.resolve(__dirname,'../../vendoo-extension/background.js'),'utf8');
const ctx=vm.createContext({importScripts(){},console:{log(){},error(){}},URL,Date,
  chrome:{runtime:{onMessage:{addListener(){}}},storage:{local:{set:async()=>{},remove:async()=>{},get:async()=>({})}}}});
vm.runInContext(src.slice(0,src.lastIndexOf('// Initialize\n')),ctx);
vm.runInContext(`
  globalThis.events=[];
  globalThis.closed=[];
  send=(msg)=>events.push(msg);
  collectDiagnostics=()=>{};
  stopJobPreview=async()=>{};
  closeListingTab=async(id)=>closed.push(id);
  addCompletedJobId=async()=>{};
  const realBuildJobSteps=buildJobSteps;
  globalThis.stageNames=realBuildJobSteps({options:{platforms:['ebay','poshmark','mercari','depop','etsy']}}).map(x=>x.step);
`,ctx);
(async()=>{
  const results=[];
  for(const stage of ctx.stageNames){
    ctx.failedStage=stage;
    await vm.runInContext(`(async()=>{
      events.length=0;closed.length=0;
      activeJob={job_id:'isolated-audit',tabId:1,options:{platforms:['ebay','poshmark','mercari','depop','etsy']}};
      buildJobSteps=(job)=>realBuildJobSteps(job).map(s=>({step:s.step,fn:async()=>s.step===failedStage?{ok:false,error:'Isolated stage failure'}:{ok:true}}));
      await runJob('isolated-audit');
    })()`,ctx);
    results.push(vm.runInContext(`({stage:failedStage,reported_failures:events.filter(x=>x.type==='job.step_failed').map(x=>x.payload.step),completed:events.some(x=>x.type==='job.completed'),extension_active_job_retained:Boolean(activeJob),tab_closed:closed.length>0})`,ctx));
  }
  const result={scope:'Actual pipeline order and failure runner; stubbed Chrome/step I/O; no live selector, login, upload or save claims.',count:results.length,results};
  fs.writeFileSync(path.join(__dirname,'extension-pipeline-probe.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({count:results.length,correctFailureReports:results.filter(x=>x.reported_failures.length===1&&x.reported_failures[0]===x.stage&&!x.completed).length,activeJobRetained:results.filter(x=>x.extension_active_job_retained).length}));
})();
