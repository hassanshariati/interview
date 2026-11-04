"use strict";
const token=decodeURIComponent(location.hash.slice(1));
const $=id=>document.getElementById(id);
let rtc=null,stream=null,known=new Set(),savedSomething=false;
function status(text){$("status").textContent=text;}
async function api(endpoint,fields={}) {
  const response=await fetch("/api/v1/public/invitation/"+endpoint,{
    method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token,...fields})});
  const data=await response.json().catch(()=>({detail:"خطا در سرویس"}));
  if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"درخواست ناموفق بود");
  return data;
}
async function refresh() {
  try{
    if(!token||token.length<30)throw Error("لینک خصوصی معتبر نیست.");
    const inv=await api("lookup");
    $("details").textContent=inv.candidate+" — "+inv.job;
    $("cv-status").textContent=inv.cv_received?
      "رزومه شما خوانده شد. موضوعات مرتبط: "+(inv.cv_skill_mentions.length?inv.cv_skill_mentions.join("، "):"پروژه‌ها و تجربه‌های درج‌شده در رزومه"):
      "رزومه‌ای دریافت نشده؛ سؤال‌ها بر اساس مهارت‌های شغل و توضیحات شما خواهند بود.";
    $("choose").hidden=inv.status!=="pending";
    $("voice").hidden=inv.status!=="confirmed";
    if(inv.status==="finished"){status("مصاحبه پایان یافته و جهت بررسی انسانی ثبت شده است.");return;}
    if(inv.status==="pending") {
      const select=$("slot");select.replaceChildren();
      for(const value of inv.slots) {
        const option=document.createElement("option");option.value=value;
        option.textContent=new Date(value).toLocaleString("fa-IR",{dateStyle:"full",timeStyle:"short"});
        select.append(option);
      }
      status("زمان مناسب را انتخاب کن.");
    } else {
      status("جلسه آماده است · "+new Date(inv.selected_slot).toLocaleString("fa-IR",{dateStyle:"short",timeStyle:"short"}));
    }
    $("consent").checked=inv.consent;
    $("start").disabled=!inv.voice_enabled;
    if(!inv.voice_enabled)$("rtc-status").textContent="اتصال صوتی AI هنوز روی سرور پیکربندی نشده است. ثبت متن دستی جایگزین مصاحبه AI نیست.";
  }catch(error){status(error.message);$("choose").hidden=true;$("voice").hidden=true;}
}
$("confirm").addEventListener("click",async()=>{
  try{await api("confirm",{selected_slot:$("slot").value});await refresh();}
  catch(error){status(error.message);}
});
$("consent").addEventListener("change",async()=>{
  if(!$("consent").checked){status("برای ادامه موافقت قبلی برقرار است؛ لغو پردازش را از پشتیبانی درخواست کن.");return;}
  try{await api("consent",{accepted:true});status("رضایت ثبت شد.");}
  catch(error){status(error.message);$("consent").checked=false;}
});
async function save(role,text) {
  if(typeof text!=="string"||!text.trim())return;
  text=text.slice(0,2000);const key=role+":"+text;
  if(known.has(key))return;
  await api("transcript",{role,text});known.add(key);
  const box=$("messages");
  if(!savedSomething){box.textContent="";savedSomething=true;}
  box.textContent+=(role==="candidate"?"داوطلب: ":"مصاحبه‌گر: ")+text+"\n\n";
  box.scrollTop=box.scrollHeight;
}
$("send-text").addEventListener("click",async()=>{
  if(!$("consent").checked){status("ابتدا رضایت خود را ثبت کن.");return;}
  try{await save("candidate",$("manual").value);$("manual").value="";}
  catch(error){status(error.message);}
});
function stop() {
  if(rtc){rtc.close();rtc=null;}
  if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;}
  $("audio").srcObject=null;
}
$("stop").addEventListener("click",()=>{stop();$("rtc-status").textContent="میکروفون قطع شد."});
$("start").addEventListener("click",async()=>{
  if(!$("consent").checked){status("ابتدا رضایت با پردازش صوت را ثبت کن.");return;}
  stop();$("rtc-status").textContent="در حال دریافت مجوز میکروفون…";
  try {
    const secret=await api("voice-secret");
    rtc=new RTCPeerConnection();
    stream=await navigator.mediaDevices.getUserMedia({audio:true});
    for(const track of stream.getTracks())rtc.addTrack(track,stream);
    rtc.ontrack=event=>{$("audio").srcObject=event.streams[0];};
    rtc.onconnectionstatechange=()=>{
      if(rtc&&["failed","disconnected"].includes(rtc.connectionState))$("rtc-status").textContent="ارتباط قطع شده است.";
    };
    const channel=rtc.createDataChannel("oai-events");
    channel.onopen=()=>{
      $("rtc-status").textContent="اتصال برقرار است؛ می‌توانی صحبت کنی.";
      channel.send(JSON.stringify({type:"response.create"}));
    };
    channel.onmessage=event=>{
      try {
        const data=JSON.parse(event.data);
        if(data.type==="error"){$("rtc-status").textContent="خطای سرویس صوتی: "+(data.error?.message||"ارتباط ناموفق بود");return;}
        if(data.type==="conversation.item.input_audio_transcription.completed")
          save("candidate",data.transcript).catch(()=>{status("ثبت بخشی از متن ناموفق بود.");});
        if(data.type==="response.output_audio_transcript.done")
          save("interviewer",data.transcript).catch(()=>{status("ثبت بخشی از متن ناموفق بود.");});
      }catch{/* ignore malformed voice events */}
    };
    const offer=await rtc.createOffer();await rtc.setLocalDescription(offer);
    const response=await fetch("https://api.openai.com/v1/realtime/calls",{
      method:"POST",headers:{"Authorization":"Bearer "+secret.value,"Content-Type":"application/sdp"},body:offer.sdp});
    if(!response.ok)throw Error("برقراری ارتباط صوتی ناموفق بود: "+response.status);
    await rtc.setRemoteDescription({type:"answer",sdp:await response.text()});
  }catch(error){$("rtc-status").textContent=error.message;stop();}
});
$("finish").addEventListener("click",async()=>{
  if(!confirm("مصاحبه پایان یابد و برای بررسی کارشناس ثبت شود؟"))return;
  try{stop();await api("finish");await refresh();}
  catch(error){status(error.message);}
});
refresh();