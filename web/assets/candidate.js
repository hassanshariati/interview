"use strict";
const token=decodeURIComponent(location.hash.slice(1));
const $=id=>document.getElementById(id);
let rtc=null,stream=null,recognition=null,known=new Set(),savedSomething=false;
let holding=false,releasePending=false,releaseTimer=null,voiceSegments=[],draftBeforeVoice="";
let voiceFinalizeCalled=false;
let audioTranscriptionAvailable=false,persianAudioAvailable=false;
let holdMode="",mediaRecorder=null,recordingStream=null,mediaChunks=[],maxRecordingTimer=null;
let questionAudioURL=null,recordedAudioURL=null,playbackVersion=0,transcribing=false;
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
function stopQuestionAudio(){
  playbackVersion++;
  const audio=$("question-audio");
  if(typeof audio.pause==="function")audio.pause();
  if(questionAudioURL&&typeof URL!=="undefined")URL.revokeObjectURL(questionAudioURL);
  questionAudioURL=null;
  audio.hidden=true;
  if(canSpeak)try{speechSynthesis.cancel();}catch{}
}
function localPersianSpeech(text){
  if(!canSpeak)return false;
  try{
    const voice=(speechSynthesis.getVoices?.()||[]).find(v=>/^fa[-_]/i.test(v.lang));
    if(!voice)return false;
    const utterance=new SpeechSynthesisUtterance(text);
    utterance.voice=voice;utterance.lang="fa-IR";utterance.rate=0.93;
    speechSynthesis.cancel();speechSynthesis.speak(utterance);
    return true;
  }catch{return false;}
}
async function speaking(text){
  if(!isChatProvider())return;
  stopQuestionAudio();
  const version=playbackVersion;
  if(!persianAudioAvailable){
    if(!localPersianSpeech(text))info("این مرورگر صدای فارسی ندارد. متن سؤال را بخوان یا صدای فارسی سرور را فعال کن.");
    return;
  }
  try{
    info("در حال آماده‌سازی صدای فارسی سؤال…");
    const response=await fetch("/api/v1/public/invitation/persian-speech",{
      method:"POST",headers:{"Content-Type":"application/json"},
      credentials:"same-origin",body:JSON.stringify({token})
    });
    if(!response.ok){
      const data=await response.json().catch(()=>({}));
      throw Error(data.detail||"سرویس صدای فارسی در دسترس نیست");
    }
    const blob=await response.blob();
    if(version!==playbackVersion)return; // Candidate started speaking or a new question arrived.
    questionAudioURL=URL.createObjectURL(blob);
    const audio=$("question-audio");
    audio.src=questionAudioURL;audio.hidden=false;
    try{
      await audio.play();
      info("سؤال به فارسی پخش می‌شود. پس از شنیدن، دکمه میکروفون را نگه دار.");
    }catch{
      info("برای شنیدن سؤال فارسی، دکمه پخشِ فایل صوتی را بزن.");
    }
  }catch{
    if(version!==playbackVersion)return;
    if(localPersianSpeech(text))info("سؤال با صدای فارسیِ نصب‌شده در مرورگر پخش می‌شود.");
    else info("سرویس صدای فارسی موقتاً در دسترس نیست و مرورگر هم صدای فارسی ندارد. سؤال را از متن بخوان.");
  }
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
    void speaking(result.question);
  }catch(err){info(err.message||"اتصال به سرویس هوش مصنوعی برقرار نشد.");}
  finally{
    aiBusy=false;$("start").disabled=false;$("send-text").disabled=false;
    $("hold-to-talk").disabled=!aiStarted||needsPersianRepair()||transcribing;
  }
}
function setHoldState(active){
  const btn=$("hold-to-talk");
  btn.setAttribute("aria-pressed",String(active));
  btn.classList.toggle("recording",active);
  btn.textContent=active?"🔴 در حال ضبط کامل پاسخ؛ برای پایان رها کن":"🎙 برای پاسخ‌دادن نگه دار";
}
function voiceText(parts){
  return parts.map(s=>String(s).trim()).filter(Boolean).join(" ").trim();
}
function finishBrowserTranscription(){
  if(!releasePending||voiceFinalizeCalled)return;
  voiceFinalizeCalled=true;releasePending=false;
  clearTimeout(releaseTimer);releaseTimer=null;
  const text=voiceText(voiceSegments);
  const draft=[draftBeforeVoice.trim(),text].filter(Boolean).join(" ").trim();
  if(draft)$("manual").value=draft.slice(0,6500);
  // Browser recognition frequently returns only a few early words.
  // Never silently send its potentially incomplete text to the LLM.
  info(text?"متن موقت مرورگر ثبت شد. آن را بررسی، با پاسخ کامل مقایسه و ویرایش و سپس «ارسال پاسخ» را بزن.":
      "مرورگر گفتار قابل‌اعتمادی تشخیص نداد. پاسخ را تایپ کن.");
  $("hold-to-talk").disabled=false;
}
function startRecognitionSegment(){
  if(!holding||!Recognition)return;
  let current;
  try{
    current=new Recognition();recognition=current;
    current.lang="fa-IR";current.continuous=true;current.interimResults=true;current.maxAlternatives=1;
    const finalized=new Map(),previews=new Map();
    current.onresult=e=>{
      for(let i=e.resultIndex;i<e.results.length;i++){
        const item=e.results[i];
        const text=String(item[0]?.transcript||"").trim();
        if(item.isFinal){finalized.set(i,text);previews.delete(i);}
        else previews.set(i,text);
      }
      const confirmed=voiceText([...finalized.entries()].sort((a,b)=>a[0]-b[0]).map(x=>x[1]));
      const partial=voiceText([...previews.entries()].sort((a,b)=>a[0]-b[0]).map(x=>x[1]));
      $("manual").value=[draftBeforeVoice,voiceText(voiceSegments),confirmed,partial].filter(Boolean).join(" ").trim().slice(0,6500);
    };
    current.onerror=e=>{
      if(["not-allowed","service-not-allowed","audio-capture","network"].includes(e.error)){
        holding=false;releasePending=false;setHoldState(false);
        info("تشخیص گفتار مرورگر قطع شد. پاسخ را به‌صورت متنی بنویس.");
      }
    };
    current.onend=()=>{
      if(recognition!==current)return;
      recognition=null;
      const confirmed=voiceText([...finalized.entries()].sort((a,b)=>a[0]-b[0]).map(x=>x[1]));
      const tentative=voiceText([...previews.entries()].sort((a,b)=>a[0]-b[0]).map(x=>x[1]));
      if(confirmed)voiceSegments.push(confirmed);
      else if(tentative)voiceSegments.push(tentative);
      if(releasePending)finishBrowserTranscription();
      else if(holding)setTimeout(()=>{if(holding)startRecognitionSegment();},150);
    };
    current.start();
  }catch{
    recognition=null;holding=false;releasePending=false;setHoldState(false);
    info("تشخیص گفتار مرورگر در دسترس نیست. پاسخ را تایپ کن.");
  }
}
function clearRecordingMedia(){
  clearTimeout(maxRecordingTimer);maxRecordingTimer=null;
  if(recordingStream){recordingStream.getTracks().forEach(track=>track.stop());recordingStream=null;}
  mediaRecorder=null;
}
async function sendFullRecording(blob){
  if(!releasePending)return;
  releasePending=false;
  if(blob.size<1024){info("ضبط صدا خالی است؛ دوباره امتحان کن یا پاسخ را بنویس.");return;}
  if(blob.size>8*1024*1024){info("حجم فایل صوتی بزرگ است. پاسخ را کوتاه‌تر ضبط کن یا بنویس.");return;}
  if(recordedAudioURL&&typeof URL!=="undefined")URL.revokeObjectURL(recordedAudioURL);
  recordedAudioURL=URL.createObjectURL(blob);
  const player=$("recorded-audio");
  player.src=recordedAudioURL;player.hidden=false;
  transcribing=true;
  $("hold-to-talk").disabled=true;$("send-text").disabled=true;$("finish").disabled=true;
  info("در حال تبدیل تمام صدای ضبط‌شده به متن فارسی…");
  try{
    const form=new FormData();
    form.append("token",token);
    const suffix=blob.type.includes("mp4")?"mp4":blob.type.includes("ogg")?"ogg":"webm";
    form.append("file",blob,"answer."+suffix);
    const response=await fetch("/api/v1/public/invitation/transcribe-audio",{
      method:"POST",credentials:"same-origin",body:form
    });
    const data=await response.json().catch(()=>({detail:"پاسخ سرویس صوتی معتبر نیست."}));
    if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"تبدیل صدا ناموفق بود.");
    const transcript=String(data.text||"").trim();
    const answer=[draftBeforeVoice.trim(),transcript].filter(Boolean).join(" ").trim();
    if(!transcript)throw Error("فایل ضبط شده متن قابل‌استفاده‌ای نداشت.");
    $("manual").value=answer.slice(0,6500);
    if(answer.length>6500){
      info("متن پاسخ بیش از حد طولانی است. آن را در کادر کوتاه کن و سپس ارسال کن.");
      return;
    }
    info("صدای کامل پردازش شد؛ پاسخ به مصاحبه‌گر ارسال می‌شود…");
    transcribing=false;
    await askAI(answer);
  }catch(error){
    info("تبدیل صدا ناموفق بود: "+error.message+"؛ صدای ضبط‌شده قابل پخش است. پاسخ را دستی بنویس و ارسال کن.");
  }finally{
    transcribing=false;$("send-text").disabled=false;$("finish").disabled=false;
    $("hold-to-talk").disabled=!aiStarted||needsPersianRepair()||aiBusy;
  }
}
async function startFullRecording(){
  const Recorder=window.MediaRecorder;
  let live;
  try{
    live=await navigator.mediaDevices.getUserMedia({
      audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}
    });
    if(!holding){
      live.getTracks().forEach(track=>track.stop());
      releasePending=false;info("برای ضبط، دکمه را تا بعد از فعال‌شدن میکروفون نگه دار.");
      return;
    }
    recordingStream=live;
    const types=["audio/webm;codecs=opus","audio/webm","audio/mp4","audio/ogg;codecs=opus"];
    const mime=types.find(type=>Recorder.isTypeSupported?.(type))||"";
    mediaRecorder=mime?new Recorder(live,{mimeType:mime}):new Recorder(live);
    mediaChunks=[];
    const current=mediaRecorder;
    current.ondataavailable=e=>{if(e.data&&e.data.size>0)mediaChunks.push(e.data);};
    current.onerror=()=>info("خطای ضبط صوت. برای پاسخ می‌توانی از متن استفاده کنی.");
    current.onstop=()=>{
      const blob=new Blob(mediaChunks,{type:current.mimeType||mime||"audio/webm"});
      clearRecordingMedia();
      if(releasePending)void sendFullRecording(blob);
    };
    current.start(1000);
    info("تمام صدای پاسخ در حال ضبط است. تا پایان صحبت دکمه را نگه دار (حداکثر ۳ دقیقه).");
    maxRecordingTimer=setTimeout(()=>{
      if(holding){info("حداکثر سه دقیقه ضبط تکمیل شد. در حال ارسال صدای کامل…");releaseHolding(true);}
    },180000);
  }catch{
    if(live)live.getTracks().forEach(track=>track.stop());
    clearRecordingMedia();holding=false;releasePending=false;setHoldState(false);
    info("مجوز میکروفون یا ضبط صدا فعال نشد. با مرورگر به‌روز Chrome یا Edge امتحان کن یا پاسخ را تایپ کن.");
  }
}
function beginHolding(event){
  if(!isChatProvider()||holding||releasePending||transcribing||aiBusy||!aiStarted||needsPersianRepair())return;
  if(!$("consent").checked){status("ابتدا رضایت پردازش صدا را ثبت کن.");return;}
  const canRecord=audioTranscriptionAvailable&&Boolean(
    window.MediaRecorder&&typeof navigator!=="undefined"&&navigator.mediaDevices?.getUserMedia);
  if(!canRecord&&!Recognition){
    info("این مرورگر ضبط و تشخیص گفتار ندارد. پاسخ را تایپ کن.");return;
  }
  stopQuestionAudio();
  holding=true;releasePending=false;voiceFinalizeCalled=false;voiceSegments=[];
  draftBeforeVoice=$("manual").value.trim();
  setHoldState(true);
  if(event?.pointerId!==undefined){
    try{$("hold-to-talk").setPointerCapture(event.pointerId);}catch{}
  }
  if(canRecord){holdMode="media";void startFullRecording();}
  else{
    holdMode="browser";
    info("تشخیص گفتار مرورگر ممکن است ناقص باشد؛ در پایان، متن را بررسی و دستی ارسال کن.");
    startRecognitionSegment();
  }
}
function releaseHolding(send=true){
  if(!holding)return;
  holding=false;releasePending=send;setHoldState(false);
  if(holdMode==="media"){
    clearTimeout(maxRecordingTimer);maxRecordingTimer=null;
    if(!send){releasePending=false;mediaChunks=[];}
    if(mediaRecorder&&mediaRecorder.state!=="inactive"){
      try{mediaRecorder.stop();}catch{clearRecordingMedia();releasePending=false;}
    }else if(!recordingStream&&send){
      releasePending=false;info("ضبط خیلی کوتاه بود؛ دوباره دکمه را نگه دار.");
    }
    return;
  }
  if(!send){
    releasePending=false;voiceSegments=[];
    if(recognition){const current=recognition;recognition=null;current.abort();}
    clearTimeout(releaseTimer);releaseTimer=null;
    info("ضبط لغو شد. می‌توانی دوباره صحبت کنی.");
    return;
  }
  if(recognition){
    try{recognition.stop();}catch{finishBrowserTranscription();}
    if(releasePending)releaseTimer=setTimeout(finishBrowserTranscription,2000);
  }else finishBrowserTranscription();
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
    persianAudioAvailable=Boolean(inv.persian_audio_available);
    audioTranscriptionAvailable=Boolean(inv.audio_transcription_available);
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
    $("hold-to-talk").disabled=!deepseek||!aiStarted||!inv.ai_enabled||transcribing;
    $("send-text").textContent=deepseek?"ارسال پاسخ و دریافت سؤال بعدی":"ثبت پاسخ متنی";
    $("start").disabled=deepseek?!inv.ai_enabled:!inv.voice_enabled;
    if(deepseek){
      showHistory(inv.ai_messages||[]);
      info(inv.ai_enabled?
        (audioTranscriptionAvailable?"ضبط کامل پاسخ فعال است؛ دکمه میکروفون را تا پایان صحبت نگه دار.":Recognition?"در این مرورگر فقط تشخیص گفتار موقت فعال است؛ بعد از ضبط، متن را بررسی کن.":"ضبط صوتی در دسترس نیست؛ پاسخ را تایپ کن."):
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
  if(mediaRecorder&&mediaRecorder.state!=="inactive")try{mediaRecorder.stop();}catch{}
  clearRecordingMedia();
  stopQuestionAudio();
  if(recordedAudioURL&&typeof URL!=="undefined")URL.revokeObjectURL(recordedAudioURL);
  recordedAudioURL=null;$("recorded-audio").hidden=true;
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
      if(last)void speaking(last.text);
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
  if(holding||releasePending||aiBusy||transcribing){
    info("ابتدا ضبط یا تبدیل صدای پاسخ را تمام کن و از ثبت پاسخ مطمئن شو، سپس مصاحبه را پایان بده.");
    return;
  }
  if(!confirm("مصاحبه پایان یابد و برای بررسی کارشناس ثبت شود؟"))return;
  try{stop();await api("finish");await refresh();}
  catch(error){status(error.message);}
});
refresh();
