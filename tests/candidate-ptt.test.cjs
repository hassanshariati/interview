"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

const script=fs.readFileSync(path.join(__dirname,"..","web","assets","candidate.js"),"utf8");

function harness(){
  const nodes=new Map();
  function node(id){
    if(!nodes.has(id)){
      const handlers=new Map();
      nodes.set(id,{
        id,handlers,value:"",textContent:"",hidden:false,disabled:false,checked:false,
        classList:{toggle(){}},
        addEventListener(name,callback){handlers.set(name,callback);},
        setAttribute(){},setPointerCapture(){},
        replaceChildren(){this.textContent="";},append(){},
        scrollTop:0,scrollHeight:0,
      });
    }
    return nodes.get(id);
  }
  const requests=[];
  let recognizer=null;
  class FakeRecognition{
    constructor(){recognizer=this;this.onresult=null;this.onend=null;this.onerror=null;}
    start(){this.started=true;}
    stop(){this.stopped=true;this.onend?.();}
    abort(){this.aborted=true;this.onend?.();}
  }
  const context={
    location:{hash:"#"+("v".repeat(48))},
    window:{SpeechRecognition:FakeRecognition,addEventListener(){}},
    document:{getElementById:node,addEventListener(){}},
    console,Date,JSON,Number,String,Array,Set,Map,Error,
    setTimeout,clearTimeout,
    fetch:async(url,options)=>{
      const payload=JSON.parse(options.body);
      requests.push({url,payload});
      if(url.endsWith("/lookup"))return {
        ok:true,json:async()=>({
          status:"confirmed",candidate:"داوطلب آزمایشی",job:"برنامه‌نویس",
          cv_received:true,cv_skill_mentions:["Kubernetes"],
          consent:true,selected_slot:new Date().toISOString(),
          ai_provider:"gapgpt",ai_enabled:true,ai_messages:[],voice_enabled:false,
        })
      };
      if(url.endsWith("/ai-turn")){
        return {ok:true,json:async()=>({
          question:payload.text
            ?"سلام! چگونه از صحت رفع خطای Kubernetes مطمئن شدی؟"
            :"سلام! یک تجربه عیب‌یابی واقعی Kubernetes را توضیح بده.",
          turn_count:payload.text?2:1,already_started:false,
        })};
      }
      throw Error("unexpected API request "+url);
    },
  };
  vm.runInNewContext(script,context,{filename:"candidate.js"});
  return {node,requests,recognition:()=>recognizer};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test("AI waits for pointer release before sending speech answer",async()=>{
  const h=harness();
  await flush();
  await h.node("start").handlers.get("click")();
  await flush();
  assert.equal(h.requests.filter(r=>r.url.endsWith("/ai-turn")).length,1);
  const button=h.node("hold-to-talk");
  assert.equal(button.disabled,false);
  button.handlers.get("pointerdown")({button:0,pointerId:3,preventDefault(){}});
  assert.equal(h.recognition().started,true);
  assert.equal(button.textContent.includes("در حال ضبط"),true);
  h.recognition().onresult({
    resultIndex:0,
    results:[{0:{transcript:"من با kubectl describe مشکل را بررسی کردم"},isFinal:false}]
  });
  await flush();
  assert.equal(h.requests.filter(r=>r.url.endsWith("/ai-turn")).length,1);
  h.recognition().onresult({
    resultIndex:0,
    results:[{0:{transcript:"من با kubectl describe مشکل را بررسی کردم"},isFinal:true}]
  });
  await flush();
  assert.equal(h.requests.filter(r=>r.url.endsWith("/ai-turn")).length,1);
  button.handlers.get("pointerup")({preventDefault(){}});
  await flush();await flush();
  const turns=h.requests.filter(r=>r.url.endsWith("/ai-turn"));
  assert.equal(turns.length,2);
  assert.equal(turns[1].payload.text,"من با kubectl describe مشکل را بررسی کردم");
  assert.ok(h.node("messages").textContent.includes("داوطلب"));
  assert.equal(h.node("hold-to-talk").disabled,false);
});

test("releasing without recognized speech does not send an empty AI response",async()=>{
  const h=harness();
  await flush();
  await h.node("start").handlers.get("click")();
  const button=h.node("hold-to-talk");
  button.handlers.get("pointerdown")({button:0,pointerId:1,preventDefault(){}});
  button.handlers.get("pointerup")({preventDefault(){}});
  await flush();
  assert.equal(h.requests.filter(r=>r.url.endsWith("/ai-turn")).length,1);
});
