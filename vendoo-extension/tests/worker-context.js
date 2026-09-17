// Load the MV3 service worker scripts into one VM context with a stubbed chrome API,
// the same way Chrome shares globals across importScripts().
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '..');

function stubApi() {
  return new Proxy(function stub() {}, {
    get: (_target, key) => (key === 'addListener' ? () => {} : stubApi()),
    apply: () => Promise.resolve({}),
  });
}

function loadWorker() {
  const context = {
    console: { log() {}, error() {}, warn() {} },
    chrome: stubApi(),
    // Timers never fire: tests only call pure helpers, and the worker's
    // reconnect loop must not keep the test process alive.
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    fetch: async () => ({ ok: false, json: async () => ({}) }),
    WebSocket: function WebSocket() { this.close = () => {}; },
    URL,
    URLSearchParams,
    TextEncoder,
    crypto: globalThis.crypto,
  };
  context.self = context;
  context.importScripts = (...files) => {
    for (const file of files) {
      vm.runInContext(fs.readFileSync(path.join(ROOT, file), 'utf8'), context, { filename: file });
    }
  };
  vm.createContext(context);
  context.importScripts('background.js');
  return context;
}

/** Call a worker function and return a plain value (VM arrays/objects have their own prototypes). */
function call(context, name, ...args) {
  context.__args = JSON.parse(JSON.stringify(args));
  const result = vm.runInContext(`${name}(...__args)`, context);
  return result === undefined ? undefined : JSON.parse(JSON.stringify(result));
}

module.exports = { loadWorker, call };
