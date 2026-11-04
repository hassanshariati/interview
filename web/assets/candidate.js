"use strict";
const token=decodeURIComponent(location.hash.slice(1));
const $=id=>document.getElementById(id);
let rtc=null,stream=null,recognition=null,known=new Set(),savedSomething=false;
let holding=false,releasePending=false,releaseTimer=null,voiceSegments=[],draftBeforeVoice="";
let voiceFinalizeCalled=false;
let aiProvider="openai",aiStarted=false,aiHistory=[],aiBusy=false,hasTranscript=false;
const isChatProvider=()=>["deepseek","gapgpt"].includes(aiProvider);
const aiName=()=>aiProvider==="gapgpt"?"GapGPT":"DeepSeek";
function persianQuestion(text){
  const fa=(String(text).match(/[\u0621-\u064A\u067E\u0686\u0698\u06A9\u06AF\u06CC]/g)||[]).length;
  const en=(String(text).match(/[A-Za-z]/g)||[]).length;
  return fa>=16&&fa>=en*0.65;
}
function needsPersianRepair(){
  const last=[...aiHistory].reverse().find(item=>item.role==="interviewer");
  return Boolean(last&&!persianQuestion(last.text));
}
const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
const canSpeak=typeof window.speechSynthesis!=="undefined"&&typeof window.SpeechSynthesisUtterance==="function";
const addText=(line)=>{
  const box=$("messages");
  if(!hasTranscript){box.textContent="";hasTranscript=true;}
  box.textContent+=line+"\n\n";
  box.scrollTop=box.scrollHeight;
};
function status(text){$("status").textContent=text;}
function info(text){$("rtc-status").textContent=text;}
async function api(endpoint,fields={}) {
  const response=await fetch("/api/v1/public/invitation/"+endpoint,{
    method:"POST",headers:{"Content-Type":"application/json"},
    credentials:"same-origin",body:JSON.stringify({token,...fields})});
  const data=await response.json().catch(()=>({detail:"خطا در سرویس"}));
  if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"درخواست ناموفق بود");
  return data;
}
function showHistory(items) {
  aiHistory=items;hasTranscript=false;
  $("messages").textContent="";
  for(const item of items)
    addText((item.role==="candidate"?"داوطلب: ":"مصاحبه‌گر AI: ")+item.text);
  if(!items.length)$("messages").textContent="بعد از شروع مصاحبه، سؤال‌ها و جواب‌ها اینجا نمایش داده می‌شوند.";
  aiStarted=items.some(item=>item.role==="interviewer");
  $("start").textContent=needsPersianRepair()?"بازنویسی سؤال به فارسی":(aiStarted?"🔊 پخش دوباره سؤال":"شروع مصاحبه فارسی با "+aiName());
  $("hold-to-talk").disabled=!aiStarted||needsPersianRepair()||aiBusy;
}
function speaking(text) {
  if(!canSpeak){info("متن سؤال نمایش داده شد؛ این مرورگر تبدیل متن به صدا ندارد.");return;}
  try{
    speechSynthesis.cancel();
    const utterance=new SpeechSynthesisUtterance(text);
    utterance.lang=$("speech-lang").value;
    utterance.rate=0.93;
    utterance.onerror=()=>info("پخش صدا در مرورگر ممکن نیست؛ سؤال را از متن بخوان.");
    speechSynthesis.speak(utterance);
  }catch{info("پخش صدا پشتیبانی نمی‌شود؛ می‌توانی سؤال را بخوانی.");}
}
async function askAI(text=null) {
  if(aiBusy)return;
  if(!$("consent").checked){status("ابتدا رضایت پردازش اطلاعات را ثبت کن.");return;}
  if(text!==null&&!String(text).trim()){info("ابتدا پاسخ را بنویس یا با میکروفون بگو.");return;}
  if(text!==null&&!aiStarted){info("ابتدا با دکمه شروع، سؤال اول را دریافت کن.");return;}
  aiBusy=true;$("start").disabled=true;$("send-text").disabled=true;$("hold-to-talk").disabled=true;
  info(text===null?"در حال آماده‌سازی سؤال اول…":"در حال تحلیل پاسخ و تولید سؤال بعدی…");
  try{
    const result=await api("ai-turn",text===null?{}:{text:String(text).trim()});
    if(result.was_corrected){
      const index=aiHistory.map(item=>item.role).lastIndexOf("interviewer");
      if(index>=0)aiHistory[index]={role:"interviewer",text:result.question};
    }else{
      if(text!==null)aiHistory.push({role:"candidate",text:String(text).trim()});
      if(text!==null||!aiStarted)aiHistory.push({role:"interviewer",text:result.question});
    }
    showHistory(aiHistory);
    $("manual").value="";
    info("سؤال "+Number(result.turn_count).toLocaleString("fa-IR")+" آماده است. جواب را بگو یا بنویس.");
    speaking(result.question);
  }catch(err){info(err.message||"اتصال به سرویس هوش مصنوعی برقرار نشد.");}
  finally{
    aiBusy=false;$("start").disabled=false;$("send-text").disabled=false;
    $("hold-to-talk").disabled=!aiStarted||needsPersianRepair();
  }
}
function setHoldState(active){
  const btn=$("hold-to-talk");
  btn.setAttribute("aria-pressed",String(active));
  btn.classList.toggle("recording",active);
  btn.textContent=active?"🔴 در حال ضبط؛ برای ارسال رها کن":"🎙 برای پاسخ‌دادن نگه دار";
}
function voiceText(parts){
  return parts.map(s=>String(s).trim()).filter(Boolean).join(" ").trim();
}
function completeHeldAnswer(){
  if(!releasePending||voiceFinalizeCalled)return;
  voiceFinalizeCalled=true;releasePending=false;
  clearTimeout(releaseTimer);releaseTimer=null;
  const recognized=voiceText(voiceSegments);
  const answer=[draftBeforeVoice.trim(),recognized].filter(Boolean).join(" ").trim();
  if(!recognized){
    info("گفتار قابل‌اعتمادی ثبت نشد؛ پاسخ را در کادر بنویس و دکمه ارسال را بزن.");
    return;
  }
  $("manual").value=answer;
  if(answer.length>2000){
    info("پاسخ طولانی است. متن شناسایی‌شده را کوتاه کن و با دکمه ارسال بفرست.");
    return;
  }
  info("صحبت تمام شد؛ پاسخ در حال ارسال به مصاحبه‌گر است…");
  askAI(answer);
}
function startRecognitionSegment(){
  if(!holding||!Recognition)return;
  let current;
  try{
    current=new Recognition();
    recognition=current;
    current.lang="fa-IR";
    current.continuous=true;
    current.interimResults=true;
    current.maxAlternatives=1;
    const finalized=new Map(),previews=new Map();
    current.onresult=event=>{
      for(let i=event.resultIndex;i<event.results.length;i++){
        const result=event.results[i];
        const text=String(result[0]?.transcript||"").trim();
        if(result.isFinal){finalized.set(i,text);previews.delete(i);}
        else previews.set(i,text);
      }
      const finalText=voiceText([...finalized.entries()].sort((a,b)=>a[0]-b[0]).map(x=>x[1]));
      const partialText=voiceText([...previews.entries()].sort((a,b)=>a[0]-b[0]).map(x=>x[1]));
      $("manual").value=[draftBeforeVoice,voiceText(voiceSegments),finalText,partialText].filter(Boolean).join(" ").trim();
    };
    current.onerror=event=>{
      if(["not-allowed","service-not-allowed","audio-capture","network"].includes(event.error)){
        holding=false;releasePending=false;setHoldState(false);
        info("تشخیص گفتار متوقف شد: "+event.error+"؛ پاسخ را تایپ کن.");
      }
    };
    current.onend=()=>{
      if(recognition!==current)return;
      recognition=null;
      const complete=voiceText([...finalized.entries()].sort((a,b)=>a[0]-b[0]).map(x=>x[1]));
      if(complete)voiceSegments.push(complete);
      if(releasePending){
        // Final speech-recognition results arrive at or before this event.
        completeHeldAnswer();
      }else if(holding){
        // Browsers may end recognition after a pause. Keep listening while held.
        setTimeout(()=>{if(holding)startRecognitionSegment();},180);
      }
    };
    current.start();
  }catch{
    recognition=null;holding=false;releasePending=false;setHoldState(false);
    info("میکروفون یا تشخیص فارسی در این مرورگر آماده نیست؛ پاسخ را تایپ کن.");
  }
}
function beginHolding(event){
  if(!isChatProvider()||holding||releasePending||aiBusy||!aiStarted||needsPersianRepair())return;
  if(!$("consent").checked){status("ابتدا رضایت پردازش پاسخ را ثبت کن.");return;}
  if(!Recognition){info("این مرورگر گفتار فارسی را تشخیص نمی‌دهد؛ از کادر متن استفاده کن.");return;}
  if(canSpeak)speechSynthesis.cancel();
  holding=true;releasePending=false;voiceFinalizeCalled=false;voiceSegments=[];
  draftBeforeVoice=$("manual").value.trim();
  setHoldState(true);
  if(event?.pointerId!==undefined){
    try{$("hold-to-talk").setPointerCapture(event.pointerId);}catch{/* unsupported */}
  }
  info("میکروفون فعال است؛ صحبت کن و تا پایان پاسخ دکمه را نگه دار.");
  startRecognitionSegment();
}
function releaseHolding(send=true){
  if(!holding)return;
  holding=false;releasePending=send;setHoldState(false);
  if(!send){
    if(recognition){try{recognition.abort();}catch{}recognition=null;}
    clearTimeout(releaseTimer);releaseTimer=null;
    info("ضبط لغو شد. برای پاسخ مجدد دکمه را نگه دار.");
    return;
  }
  info("ضبط تمام شد؛ در حال تکمیل متن گفتار…");
  if(recognition){
    try{recognition.stop();}catch{completeHeldAnswer();}
    // Safety net for browsers that never dispatch onend after stop().
    if(releasePending)releaseTimer=setTimeout(completeHeldAnswer,2000);
  }else completeHeldAnswer();
}
$("hold-to-talk").addEventListener("pointerdown",event=>{
  if(event.button!==undefined&&event.button!==0)return;
  event.preventDefault();beginHolding(event);
});
$("hold-to-talk").addEventListener("pointerup",event=>{
  event.preventDefault();releaseHolding(true);
});
$("hold-to-talk").addEventListener("pointercancel",()=>releaseHolding(false));
$("hold-to-talk").addEventListener("lostpointercapture",()=>{if(holding)releaseHolding(true);});
$("hold-to-talk").addEventListener("keydown",event=>{
  if(!["Space","Enter"].includes(event.code)||event.repeat)return;
  event.preventDefault();beginHolding();
});
$("hold-to-talk").addEventListener("keyup",event=>{
  if(!["Space","Enter"].includes(event.code))return;
  event.preventDefault();releaseHolding(true);
});
window.addEventListener("blur",()=>releaseHolding(false));
document.addEventListener("visibilitychange",()=>{
  if(document.hidden)releaseHolding(false);
});
async function refresh() {
  try{
    if(!token||token.length<30)throw Error("لینک خصوصی معتبر نیست.");
    const inv=await api("lookup");
    aiProvider=inv.ai_provider;
    $("details").textContent=inv.candidate+" — "+inv.job;
    $("cv-status").textContent=inv.cv_received?
      "رزومه شما خوانده شد. موضوعات مرتبط: "+(inv.cv_skill_mentions.length?inv.cv_skill_mentions.join("، "):"تجربه‌ها و پروژه‌های رزومه"):
      "رزومه‌ای دریافت نشده؛ پرسش‌ها براساس مهارت‌های موقعیت شغلی خواهند بود.";
    $("choose").hidden=inv.status!=="pending";
    $("voice").hidden=inv.status!=="confirmed";
    if(inv.status==="finished"){status("مصاحبه پایان یافته و جهت بررسی انسانی ثبت شده است.");return;}
    if(inv.status==="pending"){
      const select=$("slot");select.replaceChildren();
      for(const value of inv.slots){
        const option=document.createElement("option");option.value=value;
        option.textContent=new Date(value).toLocaleString("fa-IR",{dateStyle:"full",timeStyle:"short"});
        select.append(option);
      }
      status("زمان مناسب را انتخاب کن.");
    }else{
      status("جلسه آماده است · "+new Date(inv.selected_slot).toLocaleString("fa-IR",{dateStyle:"short",timeStyle:"short"}));
    }
    $("consent").checked=inv.consent;
    const deepseek=isChatProvider();
    $("speech-tools").hidden=!deepseek;
    $("hold-to-talk").hidden=!deepseek;
    $("hold-to-talk").disabled=!deepseek||!aiStarted||!inv.ai_enabled;
    $("send-text").textContent=deepseek?"ارسال پاسخ و دریافت سؤال بعدی":"ثبت پاسخ متنی";
    $("start").disabled=deepseek?!inv.ai_enabled:!inv.voice_enabled;
    if(deepseek){
      showHistory(inv.ai_messages||[]);
      info(inv.ai_enabled?
        (Recognition?aiName()+" برای مصاحبه آماده است. می‌توانی با میکروفون یا متن جواب بدهی.":aiName()+" برای مصاحبه متنی آماده است؛ تشخیص صدا در این مرورگر پشتیبانی نمی‌شود."):
        "کلید "+aiName()+" در سرور تنظیم نشده است یا مقدار آن نمونه است.");
    }else{
      $("start").textContent="🎙 شروع گفت‌وگو با AI";
      if(!inv.voice_enabled)info("مصاحبه صوتی OpenAI روی سرور فعال نیست؛ ثبت متن دستی به‌تنهایی مصاحبه AI نیست.");
    }
  }catch(error){status(error.message);$("choose").hidden=true;$("voice").hidden=true;}
}
$("confirm").addEventListener("click",async()=>{
  try{await api("confirm",{selected_slot:$("slot").value});await refresh();}
  catch(error){status(error.message);}
});
$("consent").addEventListener("change",async()=>{
  if(!$("consent").checked){status("برای لغو پردازش قبلی با پشتیبانی تماس بگیر.");return;}
  try{await api("consent",{accepted:true});status("رضایت پردازش ثبت شد.");}
  catch(error){status(error.message);$("consent").checked=false;}
});
async function save(role,text) {
  if(typeof text!=="string"||!text.trim())return;
  text=text.slice(0,2000);const key=role+":"+text;
  if(known.has(key))return;
  await api("transcript",{role,text});known.add(key);
  addText((role==="candidate"?"داوطلب: ":"مصاحبه‌گر: ")+text);
}
$("send-text").addEventListener("click",async()=>{
  if(!$("consent").checked){status("ابتدا رضایت را ثبت کن.");return;}
  if(isChatProvider()){await askAI($("manual").value);return;}
  try{await save("candidate",$("manual").value);$("manual").value="";}
  catch(error){status(error.message);}
});
function stop() {
  if(holding)releaseHolding(false);
  if(recognition){const current=recognition;recognition=null;current.abort();}
  releasePending=false;clearTimeout(releaseTimer);releaseTimer=null;
  if(canSpeak)speechSynthesis.cancel();
  if(rtc){rtc.close();rtc=null;}
  if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;}
  $("audio").srcObject=null;
}
$("stop").addEventListener("click",()=>{stop();info("میکروفون و پخش صدا متوقف شد.");});
$("start").addEventListener("click",async()=>{
  if(!$("consent").checked){status("ابتدا با پردازش صدا و متن موافقت کن.");return;}
  if(isChatProvider()){
    if(!aiStarted||needsPersianRepair())await askAI();
    else {
      const last=[...aiHistory].reverse().find(x=>x.role==="interviewer");
      if(last)speaking(last.text);
      info("به سؤال گوش کن؛ وقتی آماده شدی دکمه «برای پاسخ‌دادن نگه دار» را فشار بده.");
    }
    return;
  }
  stop();info("در حال دریافت مجوز میکروفون…");
  try{
    const secret=await api("voice-secret");
    rtc=new RTCPeerConnection();
    stream=await navigator.mediaDevices.getUserMedia({audio:true});
    for(const track of stream.getTracks())rtc.addTrack(track,stream);
    rtc.ontrack=event=>{$("audio").srcObject=event.streams[0];};
    rtc.onconnectionstatechange=()=>{
      if(rtc&&["failed","disconnected"].includes(rtc.connectionState))info("ارتباط قطع شده است.");
    };
    const channel=rtc.createDataChannel("oai-events");
    channel.onopen=()=>{info("اتصال برقرار است؛ می‌توانی صحبت کنی.");channel.send(JSON.stringify({type:"response.create"}));};
    channel.onmessage=event=>{
      try{
        const data=JSON.parse(event.data);
        if(data.type==="error"){info("خطای سرویس صوتی: "+(data.error?.message||"ارتباط ناموفق بود"));return;}
        if(data.type==="conversation.item.input_audio_transcription.completed")
          save("candidate",data.transcript).catch(()=>status("ثبت بخشی از متن ناموفق بود."));
        if(data.type==="response.output_audio_transcript.done")
          save("interviewer",data.transcript).catch(()=>status("ثبت بخشی از متن ناموفق بود."));
      }catch{/* malformed events are ignored */}
    };
    const offer=await rtc.createOffer();await rtc.setLocalDescription(offer);
    const response=await fetch("https://api.openai.com/v1/realtime/calls",{
      method:"POST",headers:{"Authorization":"Bearer "+secret.value,"Content-Type":"application/sdp"},body:offer.sdp});
    if(!response.ok)throw Error("برقراری ارتباط صوتی ناموفق بود: "+response.status);
    await rtc.setRemoteDescription({type:"answer",sdp:await response.text()});
  }catch(error){info(error.message);stop();}
});
$("finish").addEventListener("click",async()=>{
  if(holding||releasePending||aiBusy){
    info("ابتدا ضبط را تمام کن و از ثبت پاسخ مطمئن شو، سپس مصاحبه را پایان بده.");
    return;
  }
  if(!confirm("مصاحبه پایان یابد و برای بررسی کارشناس ثبت شود؟"))return;
  try{stop();await api("finish");await refresh();}
  catch(error){status(error.message);}
});
refresh();
