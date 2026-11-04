"use strict";
/* Regression: an event's currentTarget becomes null after an async listener yields.
 * The login must reset the captured form element, not event.currentTarget.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("web/assets/admin.js", "utf8");
const objects = new Map();
const element = id => {
  if(!objects.has(id))objects.set(id,{
    id,hidden:false,value:"",textContent:"",style:{},listeners:{},resetCount:0,
    addEventListener(name,fn){this.listeners[name]=fn;},
    reset(){this.resetCount++;},
    replaceChildren(){},
    append(){},
    classList:{toggle(){}}
  });
  return objects.get(id);
};
const login=element("login-form");
login.fields={email:"admin@example.com",password:"correct-test-password"};
class FakeFormData {
  constructor(node){this.fields=node.fields||{};}
  get(name){return this.fields[name];}
}
async function mockFetch(url,options={}) {
  let status=503,payload={detail:"Not used in this regression test"};
  if(url.endsWith("/auth/me")){status=401;payload={detail:"Login required"};}
  if(url.endsWith("/auth/login")) {
    assert.equal(options.method,"POST");
    const data=JSON.parse(options.body);
    assert.equal(data.email,"admin@example.com");
    status=200;payload={email:"admin@example.com",role:"admin",csrf_token:"fake-csrf"};
  }
  return {ok:status===200,json:async()=>payload};
}
vm.runInNewContext(source,{
  document:{getElementById:element,querySelectorAll:()=>[]},
  fetch:mockFetch,FormData:FakeFormData,
  window:{scrollTo(){}},
  Intl,Number,JSON,String,Date,Promise,console,Error,
});
async function check() {
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(typeof login.listeners.submit,"function");
  const event={currentTarget:login,preventDefault(){}};
  const running=login.listeners.submit(event);
  event.currentTarget=null;
  await running;
  assert.equal(login.resetCount,1,"login form must reset after the await");
  assert.equal(element("auth-screen").hidden,true);
  assert.equal(element("workspace").hidden,false);
  assert.equal(element("login-error").textContent,"");
  console.log("Admin login async form regression: PASS");
}
check().catch(error=>{console.error(error);process.exitCode=1;});
