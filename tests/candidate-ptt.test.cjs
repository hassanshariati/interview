"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

const script=fs.readFileSync(path.join(__dirname,"..","web","assets","candidate.js"),"utf8");
const flush=()=>new Promise(done=>setImmediate(done));

function harness({audioRecording=true,shortTranscript=false}={}){
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
        pause(){},play(){return Promise.resolve();},
        scrollTop:0,scrollHeight:0,
      });
    }
    return nodes.get(id);
  }
  let mediaRecorder=null,recognizer=null,trackStopped=false;
  const longAnswer=Array(36).fill("من در یک پروژه Kubernetes سرویس‌های متعدد را بررسی کردم").join("، ");
  const requests=[];
  class FakeRecognition{
    constructor(){recognizer=this;}
    start(){this.started=true;}
    stop(){this.stopped=true;this.onend?.();}
    abort(){this.aborted=true;this.onend?.();}
  }
  class FakeMediaRecorder{
    static isTypeSupported(type){return type==="audio/webm;codecs=opus";}
    constructor(media,{mimeType}={}){this.media=media;this.mimeType=mimeType||"audio/webm";this.state="inactive";mediaRecorder=this;}
    start(){this.state="recording";this.started=true;}
    stop(){
      this.state="inactive";
      this.ondataavailable?.({data:new Blob([Buffer.alloc(3000,43)],{type:"audio/webm"})});
      this.onstop?.();
    }
  }
  const context={
    location:{hash:"#"+("v".repeat(48))},
    window:{SpeechRecognition:FakeRecognition,
      ...(audioRecording?{MediaRecorder:FakeMediaRecorder}:{}),
      addEventListener(){}},
    navigator:audioRecording?{mediaDevices:{
      getUserMedia:async()=>({getTracks:()=>[{stop(){trackStopped=true;}}]})
    }}:{},
    document:{getElementById:node,addEventListener(){}},
    console,Date,JSON,Number,String,Array,Set,Map,Error,Blob,Buffer,FormData,
    URL:{createObjectURL(){return "blob:synthetic";},revokeObjectURL(){}},
    setTimeout,clearTimeout,
    fetch:async(url,options)=>{
      const payload=typeof options.body==="string"?JSON.parse(options.body):options.body;
      requests.push({url,payload});
      if(url.endsWith("/lookup"))return {ok:true,json:async()=>({
        status:"confirmed",candidate:"داوطلب آزمایشی",job:"برنامه‌نویس",
        cv_received:true,cv_skill_mentions:["Kubernetes"],consent:true,
        selected_slot:new Date().toISOString(),ai_provider:"gapgpt",ai_enabled:true,
        ai_messages:[],voice_enabled:false,
        persian_audio_available:false,
        audio_transcription_available:audioRecording,
      })};
      if(url.endsWith("/ai-turn"))return {ok:true,json:async()=>({
        question:payload.text
          ?"سلام! چگونه از صحت رفع خطای Kubernetes در پروژه مطمئن شدی؟"
          :"سلام! یک تجربه واقعی عیب‌یابی Kubernetes را توضیح بده.",
        turn_count:payload.text?2:1,already_started:false
      })};
      if(url.endsWith("/transcribe-audio"))return {ok:true,json:async()=>({
        text:shortTranscript?"سلام بله روزتون خوش کار کردم":longAnswer,
        characters:shortTranscript?30:longAnswer.length,language:"fa"
      })};
      throw Error("unexpected request "+url);
    },
  };
  vm.runInNewContext(script,context,{filename:"candidate.js"});
  return {node,requests,longAnswer,recognition:()=>recognizer,
    recorder:()=>mediaRecorder,stopped:()=>trackStopped};
}

test("entire long recording is sent to STT only after pointer release",async()=>{
  const h=harness();
  await flush();
  await h.node("start").handlers.get("click")();
  await flush();
  assert.equal(h.requests.filter(r=>r.url.endsWith("/ai-turn")).length,1);
  const button=h.node("hold-to-talk");
  assert.equal(button.disabled,false);
  button.handlers.get("pointerdown")({button:0,pointerId:7,preventDefault(){}});
  await flush();
  assert.equal(h.recorder().started,true);
  assert.ok(button.textContent.includes("در حال ضبط کامل"));
  await flush();
  assert.equal(h.requests.filter(r=>r.url.endsWith("/ai-turn")).length,1);
  assert.equal(h.requests.filter(r=>r.url.endsWith("/transcribe-audio")).length,0);
  button.handlers.get("pointerup")({preventDefault(){}});
  await flush();await flush();await flush();
  const sent=h.requests.filter(r=>r.url.endsWith("/transcribe-audio"));
  assert.equal(sent.length,1);
  assert.equal(sent[0].payload.get("token"),"v".repeat(48));
  assert.ok(sent[0].payload.get("file").size>=3000);
  // NEVER send to the LLM merely because the mic button was released.
  const beforeConfirmation=h.requests.filter(r=>r.url.endsWith("/ai-turn"));
  assert.equal(beforeConfirmation.length,1);
  assert.equal(h.node("manual").value,h.longAnswer);
  assert.equal(h.node("answer-review").hidden,false);
  assert.match(h.node("answer-review").textContent,/پیش‌نویس/);
  assert.match(h.node("send-text").textContent,/تأیید و ارسال/);
  assert.equal(h.recognition(),null); // no competing browser ASR during full MediaRecorder capture
  assert.equal(h.stopped(),true);
  // A candidate can edit the transcript before any follow-up is generated.
  h.node("manual").value+=" و جزئیات دیگری هم اضافه کردم";
  await h.node("send-text").handlers.get("click")();
  await flush();
  const turns=h.requests.filter(r=>r.url.endsWith("/ai-turn"));
  assert.equal(turns.length,2);
  assert.ok(turns[1].payload.text.endsWith("جزئیات دیگری هم اضافه کردم"));
  assert.ok(turns[1].payload.text.length>500);
  assert.equal(h.node("manual").value,"");
  assert.equal(h.node("answer-review").hidden,true);
});

test("short transcript is displayed for review and NEVER auto-submitted",async()=>{
  const h=harness({shortTranscript:true});
  await flush();
  await h.node("start").handlers.get("click")();
  h.node("hold-to-talk").handlers.get("pointerdown")({button:0,pointerId:4,preventDefault(){}});
  await flush();
  h.node("hold-to-talk").handlers.get("pointerup")({preventDefault(){}});
  await flush();await flush();
  assert.equal(h.node("manual").value,"سلام بله روزتون خوش کار کردم");
  assert.equal(h.node("answer-review").hidden,false);
  assert.equal(h.requests.filter(r=>r.url.endsWith("/ai-turn")).length,1);
  assert.ok(h.node("recorded-audio").src.startsWith("blob:"));
  // Clicking while a recording/transcription is active must not send a partial draft.
});

test("browser-only short recognition is not silently sent as a complete answer",async()=>{
  const h=harness({audioRecording:false});
  await flush();
  await h.node("start").handlers.get("click")();
  const button=h.node("hold-to-talk");
  button.handlers.get("pointerdown")({button:0,pointerId:3,preventDefault(){}});
  assert.equal(h.recognition().started,true);
  h.recognition().onresult({
    resultIndex:0,
    results:[{0:{transcript:"من Kubernetes را بررسی کردم"},isFinal:false}]
  });
  button.handlers.get("pointerup")({preventDefault(){}});
  await flush();
  assert.equal(h.requests.filter(r=>r.url.endsWith("/ai-turn")).length,1);
  assert.ok(h.node("manual").value.includes("Kubernetes"));
  assert.equal(h.node("answer-review").hidden,false);
  assert.ok(h.node("answer-review").textContent.includes("ناقص"));
  await h.node("send-text").handlers.get("click")();
  await flush();
  assert.equal(h.requests.filter(r=>r.url.endsWith("/ai-turn")).length,2);
});

test("no recognised browser speech does not create an empty AI answer",async()=>{
  const h=harness({audioRecording:false});
  await flush();await h.node("start").handlers.get("click")();
  const btn=h.node("hold-to-talk");
  btn.handlers.get("pointerdown")({button:0,pointerId:1,preventDefault(){}});
  btn.handlers.get("pointerup")({preventDefault(){}});
  await flush();
  assert.equal(h.requests.filter(r=>r.url.endsWith("/ai-turn")).length,1);
});
