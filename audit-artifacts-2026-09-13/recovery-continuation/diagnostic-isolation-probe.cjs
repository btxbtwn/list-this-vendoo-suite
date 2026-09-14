// Reproduce Chrome executeScript function serialization in a separate VM.
// No browser, account, extension dispatch, or application mutation.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../../vendoo-extension/diagnostic-collector.js'), 'utf8');
const worker = vm.createContext({});
vm.runInContext(source, worker);
const serialized = vm.runInContext('collectPageDiagnostics.toString()', worker);
const page = vm.createContext({document:{querySelectorAll:()=>[],title:'Disposable empty form'},window:{location:{href:'https://example.invalid/audit'}},setTimeout:(fn)=>fn()});
(async()=>{
  let result;
  try { result={ok:true,result:await vm.runInContext(`(${serialized})({mode:'passive'})`,page)}; }
  catch(error){result={ok:false,error:String(error),scope:'Serialized actual collector in isolated empty DOM fixture; no real page modified.'};}
  fs.writeFileSync(path.join(__dirname,'diagnostic-isolation-probe.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
})();
