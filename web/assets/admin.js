"use strict";
const $=id=>document.getElementById(id);
let csrf="",jobs=[],candidates=[],summary=null;
const viewTitles={overview:"مرکز گزارش‌های مصاحبه",jobs:"مدیریت فرصت‌های شغلی",
  candidates:"متقاضیان و رزومه‌ها",reviews:"گزارش عملکرد و ارزیابی",invitations:"دعوت به مصاحبه"};
const persian=n=>Number(n||0).toLocaleString("fa-IR");
const create=(tag,cls,value)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(value!==undefined)el.textContent=value;return el;};
async function api(path,options={}) {
  const headers={...(options.headers||{})};
  if(csrf&&options.method&&options.method.toUpperCase()!=="GET")headers["X-CSRF-Token"]=csrf;
  const response=await fetch("/api/v1/"+path,{credentials:"same-origin",...options,headers});
  const data=await response.json().catch(()=>({detail:"پاسخ معتبر دریافت نشد"}));
  if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"خطا در سرویس");
  return data;
}
function toast(message,bad=false) {
  const el=$("admin-toast");el.hidden=false;el.textContent=message;
  el.style.background=bad?"#482832":"#1c4241";el.style.color=bad?"#ffb2b4":"#b9fff0";
}
function activate(view) {
  for(const panel of document.querySelectorAll("[data-panel]"))panel.hidden=panel.dataset.panel!==view;
  for(const link of document.querySelectorAll("[data-view]"))link.classList.toggle("active",link.dataset.view===view);
  $("view-title").textContent=viewTitles[view]||view;
  window.scrollTo({top:0,behavior:"smooth"});
}
function fillSelect(id,items,label) {
  const select=$(id),selected=select.value;select.replaceChildren();
  for(const item of items) {const option=create("option",null,label(item));option.value=item.id;select.append(option);}
  if(items.some(x=>String(x.id)===selected))select.value=selected;
}
function renderStats(data) {
  const stats=[
    ["موقعیت‌های شغلی",data.counts.jobs,"شامل مشاغل نمونه"],
    ["داوطلبان",data.counts.candidates,"شامل "+persian(data.counts.demo_candidates)+" پرونده نمونه"],
    ["مصاحبه‌های تکمیل‌شده",data.counts.finished,"شامل داده آزمایشی"],
    ["ارزیابی‌های واقعی انسانی",data.counts.assessments,"امتیازهای نمونه جدا هستند"]
  ];
  const row=$("stat-grid");row.replaceChildren();
  for(const [name,count,label] of stats) {
    const card=create("div","stat-card");
    card.append(create("small",null,name),create("strong",null,persian(count)),create("span","accent",label));
    row.append(card);
  }
}
function empty(element,message="داده‌ای برای نمایش وجود ندارد.") {
  element.replaceChildren(create("div","empty-dark",message));
}
function renderBars(id,items,valueKey,maxBar=100) {
  const root=$(id);root.replaceChildren();
  if(!items.length||items.every(x=>!x[valueKey]))return empty(root,"پس از ثبت اطلاعات، نمودار این بخش تکمیل می‌شود.");
  const max=Math.max(...items.map(x=>Number(x[valueKey])||0),1);
  for(const item of items.slice(0,8)) {
    const row=create("div","chart-row");
    const label=create("span",null,item.name);label.title=item.name;
    const track=create("div","chart-track"),bar=create("i");
    bar.style.setProperty("--w",(Math.max(0,Math.min(maxBar,Number(item[valueKey])/max*100)))+"%");
    track.append(bar);
    const numeric=valueKey==="average"?Number(item.average).toLocaleString("fa-IR",{maximumFractionDigits:2}):persian(item[valueKey]);
    row.append(label,track,create("b",null,numeric));
    root.append(row);
  }
}
function renderTrend(data) {
  const root=$("chart-trend");root.replaceChildren();
  const values=data.map(x=>x.count),max=Math.max(1,...values);
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.classList.add("trend-svg");svg.setAttribute("viewBox","0 0 500 180");
  svg.setAttribute("role","img");svg.setAttribute("aria-label","روند ۱۴ روزه تعداد درخواست‌های ثبت‌شده");
  for(const y of [25,68,111,154]) {
    const line=document.createElementNS(svg.namespaceURI,"line");
    for(const [key,val] of Object.entries({x1:10,x2:490,y1:y,y2:y,stroke:"#284558","stroke-width":1}))line.setAttribute(key,val);
    svg.append(line);
  }
  const points=values.map((value,i)=>[12+i*(476/Math.max(1,values.length-1)),154-(value/max)*122]);
  const polygon=document.createElementNS(svg.namespaceURI,"polygon");
  polygon.setAttribute("points",[[12,154],...points,[488,154]].map(pair=>pair.join(",")).join(" "));
  polygon.setAttribute("fill","#35dbc116");svg.append(polygon);
  const path=document.createElementNS(svg.namespaceURI,"polyline");
  path.setAttribute("points",points.map(pair=>pair.join(",")).join(" "));
  path.setAttribute("fill","none");path.setAttribute("stroke","#47dcc6");
  path.setAttribute("stroke-width","4");path.setAttribute("stroke-linejoin","round");svg.append(path);
  points.forEach(([x,y],i)=>{
    if(i%3!==0&&i!==points.length-1)return;
    const circle=document.createElementNS(svg.namespaceURI,"circle");
    for(const [k,v] of Object.entries({cx:x,cy:y,r:4,fill:"#87fbe7"}))circle.setAttribute(k,v);
    const title=document.createElementNS(svg.namespaceURI,"title");
    title.textContent=data[i].day+" — "+persian(data[i].count)+" درخواست";circle.append(title);svg.append(circle);
  });
  root.append(svg);
  root.append(create("p","small",persian(values.reduce((a,b)=>a+b,0))+" درخواست در ۱۴ روز گذشته"));
}
function renderStatus(items) {
  const root=$("chart-status");root.replaceChildren();
  const colors=["#efb96b","#6b85ff","#39d4b7"];
  const total=items.reduce((a,item)=>a+item.value,0);
  if(!total)return empty(root);
  let progress=0;
  const sections=items.map((item,i)=>{
    const start=progress;progress+=item.value/total*100;
    return colors[i]+" "+start+"% "+progress+"%";
  });
  const donut=create("div","chart-donut");donut.style.background="conic-gradient("+sections.join(",")+")";
  donut.append(create("b",null,persian(total)));
  const legend=create("div","chart-legend");
  const titles={pending:"در انتظار",confirmed:"تأییدشده",finished:"پایان‌یافته"};
  items.forEach((item,i)=>{
    const span=create("span");
    const dot=create("i","legend-dot");dot.style.background=colors[i];
    span.append(dot,document.createTextNode((titles[item.name]||item.name)+" "+persian(item.value)));
    legend.append(span);
  });
  root.append(donut,legend);
}
function td(row,value) {row.append(create("td",null,value));}
function tableHead(columns) {
  const table=create("table"),thead=create("thead"),tr=create("tr");
  columns.forEach(title=>tr.append(create("th",null,title)));
  thead.append(tr);table.append(thead);return table;
}
function statusBadge(status) {
  const dictionary={pending:"در انتظار",confirmed:"تأییدشده",finished:"پایان‌یافته"};
  return create("span","status "+status,dictionary[status]||status);
}
function renderRecent(recent) {
  const rows=$("recent-rows");rows.replaceChildren();
  if(!recent.length){const tr=create("tr");const cell=create("td",null,"هنوز مصاحبه‌ای ثبت نشده است.");cell.colSpan=5;tr.append(cell);rows.append(tr);return;}
  for(const item of recent) {
    const tr=create("tr");td(tr,item.candidate+(item.is_demo?" · نمونه آزمایشی":""));td(tr,item.job);
    const st=create("td");st.append(statusBadge(item.status));tr.append(st);
    td(tr,item.is_demo?persian(item.demo_ratings)+" (نمونه)":persian(item.human_ratings));
    const cell=create("td"),button=create("button","btn-outline","نمایش گزارش");
    button.type="button";button.style.padding="8px 12px";
    button.addEventListener("click",()=>openReport(item.candidate_id,item.job_id));
    cell.append(button);tr.append(cell);rows.append(tr);
  }
}
function renderLists() {
  const jobRoot=$("admin-jobs"),candidateRoot=$("admin-candidates");
  jobRoot.replaceChildren();candidateRoot.replaceChildren();
  if(!jobs.length)empty(jobRoot,"موقعیتی ثبت نشده است.");
  else {
    const table=tableHead(["موقعیت","حوزه کاری","مهارت‌ها"]),body=create("tbody");
    for(const job of jobs) {const tr=create("tr");td(tr,job.title);td(tr,job.category);td(tr,job.required_skills.join("، "));body.append(tr);}
    table.append(body);jobRoot.append(table);
  }
  if(!candidates.length)empty(candidateRoot,"متقاضی ثبت نشده است.");
  else {
    const table=tableHead(["نام","ایمیل","شناسه"]),body=create("tbody");
    for(const person of candidates.slice(0,100)) {const tr=create("tr");td(tr,person.full_name+(person.is_demo?" · نمونه آزمایشی":""));td(tr,person.email);td(tr,persian(person.id));body.append(tr);}
    table.append(body);candidateRoot.append(table);
  }
  for(const id of ["report-job","invite-job"])fillSelect(id,jobs,x=>x.title);
  for(const id of ["report-candidate","invite-candidate"])fillSelect(id,candidates,x=>x.full_name+" — "+x.email);
}
async function loadInvitations() {
  const records=await api("invitations"),root=$("invitations-table");root.replaceChildren();
  if(!records.length)return empty(root,"دعوتی ثبت نشده است.");
  const table=tableHead(["شناسه","داوطلب","موقعیت","وضعیت","وضعیت ایمیل"]),body=create("tbody");
  for(const record of records) {
    const tr=create("tr");
    td(tr,persian(record.id));
    td(tr,candidates.find(x=>x.id===record.candidate_id)?.full_name||persian(record.candidate_id));
    td(tr,jobs.find(x=>x.id===record.job_id)?.title||persian(record.job_id));
    const cell=create("td");cell.append(statusBadge(record.status));tr.append(cell);
    td(tr,record.email_status);body.append(tr);
  }
  table.append(body);root.append(table);
}
async function refresh() {
  try {
    const [a,j,c]=await Promise.all([api("admin/analytics"),api("jobs"),api("candidates")]);
    summary=a;jobs=j;candidates=c;
    renderStats(a);renderTrend(a.activity);renderStatus(a.statuses);
    renderBars("chart-jobs",a.by_job,"count");
    const realScores=a.competencies.some(x=>x.count>0);
    $("chart-skills-title").textContent=realScores?
      "میانگین ارزیابی انسانی واقعی (از ۴)":"نمودار نمایشی — امتیازهای مصنوعی (از ۴)";
    renderBars("chart-skills",realScores?a.competencies:a.demo_competencies,"average");
    renderRecent(a.recent);renderLists();
    await loadInvitations();
  }catch(error){toast(error.message,true);}
}
function signedIn(user) {
  csrf=user.csrf_token;$("current-user").textContent=user.email;
  $("auth-screen").hidden=true;$("workspace").hidden=false;refresh();
}
async function checkSession() {
  try{signedIn(await api("auth/me"))}
  catch{csrf="";$("auth-screen").hidden=false;$("workspace").hidden=true;}
}
$("login-form").addEventListener("submit",async event=>{
  event.preventDefault();const formElement=event.currentTarget,button=$("login-button");
  button.disabled=true;$("login-error").textContent="";
  try{
    const form=new FormData(formElement);
    const user=await api("auth/login",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({email:form.get("email"),password:form.get("password")})});
    formElement.reset();signedIn(user);
  }catch(error){$("login-error").textContent="ورود انجام نشد: "+error.message;}
  finally{button.disabled=false;}
});
$("logout-button").addEventListener("click",async()=>{
  try{await api("auth/logout",{method:"POST"});}catch(error){toast(error.message,true);return;}
  csrf="";$("auth-screen").hidden=false;$("workspace").hidden=true;
  $("admin-toast").hidden=true;
});
$("refresh-button").addEventListener("click",refresh);
document.querySelectorAll("[data-view]").forEach(btn=>btn.addEventListener("click",()=>activate(btn.dataset.view)));
$("job-form").addEventListener("submit",async event=>{
  event.preventDefault();const formElement=event.currentTarget,f=new FormData(formElement);
  try{
    await api("jobs",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({title:f.get("title"),description:f.get("description"),
        required_skills:String(f.get("skills")).split(/[,،]/).map(x=>x.trim()).filter(Boolean)})});
    formElement.reset();toast("موقعیت جدید ثبت شد.");await refresh();
  }catch(error){toast(error.message,true);}
});
$("cv-form").addEventListener("submit",async event=>{
  event.preventDefault();const formElement=event.currentTarget,formData=new FormData(formElement);
  try{
    const result=await api("candidates/upload",{method:"POST",body:formData});
    formElement.reset();toast("رزومه "+result.full_name+" ثبت شد.");await refresh();
  }catch(error){toast(error.message,true);}
});
async function openReport(candidateId,jobId){
  $("report-candidate").value=String(candidateId);$("report-job").value=String(jobId);
  activate("reviews");await showReport();
}
async function showReport() {
  const candidateId=Number($("report-candidate").value),jobId=Number($("report-job").value);
  if(!candidateId||!jobId){toast("ابتدا داوطلب و موقعیت را انتخاب کن.",true);return;}
  const root=$("report-container");root.replaceChildren(create("p",null,"در حال دریافت گزارش…"));
  try {
    const r=await api("reports/"+candidateId+"/"+jobId);root.replaceChildren();
    root.append(create("h3",null,r.candidate+" | "+r.job));
    if(r.is_demo)root.append(create("p","notice","پرونده، پاسخ و امتیازهای این بخش کاملاً مصنوعی و فقط برای نمایش آزمایشی هستند."));
    root.append(create("p","small","تصمیم نهایی: بررسی انسانی الزامی است."));
    root.append(create("h4",null,r.is_demo?"امتیازهای نمایشی ساختگی":"ارزیابی‌های مستند"));
    if(!r.human_assessments.length)root.append(create("p",null,"هنوز ارزیابی انسانی ثبت نشده؛ امتیازی تخصیص داده نمی‌شود."));
    for(const item of r.human_assessments){
      const section=create("section");
      section.append(create("span","report-score",item.competency+" · "+persian(item.score)+" از ۴"));
      section.append(create("p",null,"شاهد: "+item.observed_answer));
      if(item.reviewer_notes)section.append(create("p","small",item.reviewer_notes));
      root.append(section);
    }
    root.append(create("h4",null,r.is_demo?"گفت‌وگوی نمونه ساختگی":"متن مصاحبه‌ها (ارسالی از مرورگر، تأییدنشده)"));
    if(!r.interviews.length)root.append(create("p",null,"مصاحبه‌ای برای این موقعیت موجود نیست."));
    for(const session of r.interviews.slice(0,5)) {
      const panel=create("div");
      panel.append(create("p","small","جلسه "+persian(session.id)+" · "+session.status));
      if(!session.transcript.length)panel.append(create("p",null,"متن مصاحبه ثبت نشده است."));
      for(const row of session.transcript.slice(0,150)) {
        panel.append(create("p",null,(row.role==="candidate"?"داوطلب: ":"مصاحبه‌گر: ")+row.text));
      }
      const hasAIAnswers=session.transcript.some(item=>item.source==="candidate_ai");
      if(session.status==="finished"&&hasAIAnswers){
        const action=create("button","btn-outline","تحلیل شواهد فنی با AI");
        action.type="button";
        const output=create("div","ai-review-output");
        action.addEventListener("click",async()=>{
          action.disabled=true;
          output.replaceChildren(create("p","small","در حال تحلیل پاسخ‌های مصاحبه توسط سرویس AI…"));
          try{
            const response=await api("reports/"+candidateId+"/"+jobId+"/ai-analysis",{
              method:"POST",headers:{"Content-Type":"application/json"},
              body:JSON.stringify({invitation_id:session.id})
            });
            output.replaceChildren();
            output.append(create("h4",null,"گزارش فنی مبتنی بر شواهد · "+response.provider));
            output.append(create("p",null,response.summary));
            const sections=[
              ["شواهد مهارت و تجربه","evidence_strengths"],
              ["ابهام‌ها و موارد نیازمند راستی‌آزمایی","evidence_gaps"],
              ["سؤالات پیشنهادی برای کارشناس انسانی","follow_up_questions"]
            ];
            for(const [heading,key] of sections){
              output.append(create("h4",null,heading));
              const values=response[key]||[];
              if(!values.length){output.append(create("p","small","شاهد کافی در پاسخ‌ها ثبت نشده است."));continue;}
              const list=create("ul");
              for(const value of values)list.append(create("li",null,value));
              output.append(list);
            }
            output.append(create("p","small",response.limitations));
          }catch(error){output.replaceChildren(create("p","error-text",error.message));}
          finally{action.disabled=false;}
        });
        panel.append(action,output);
      }else if(session.status==="finished"){
        panel.append(create("p","small","برای تحلیل فنی، پاسخ‌های ثبت‌شده از جریان مصاحبه AI لازم است. نوشته‌های ارسالیِ تأییدنشده به‌تنهایی برای این گزارش استفاده نمی‌شوند."));
      }
      root.append(panel);
    }
  }catch(error){root.replaceChildren(create("p","error-text",error.message));}
}
$("show-report").addEventListener("click",showReport);
$("show-match").addEventListener("click",async()=>{
  const id=Number($("report-candidate").value),job=Number($("report-job").value);
  if(!id||!job)return toast("ابتدا داوطلب و موقعیت را انتخاب کن.",true);
  const output=$("match-result");output.hidden=false;
  try{output.textContent=JSON.stringify(await api("matches/"+id+"/"+job),null,2);}
  catch(error){output.textContent=error.message;}
});
$("assessment-form").addEventListener("submit",async event=>{
  event.preventDefault();const formElement=event.currentTarget,f=new FormData(formElement);
  try{
    await api("assessments",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({candidate_id:Number($("report-candidate").value),job_id:Number($("report-job").value),
        competency:f.get("competency"),score:Number(f.get("score")),
        observed_answer:f.get("observed_answer"),reviewer_notes:f.get("reviewer_notes")})});
    formElement.reset();toast("ارزیابی انسانی ثبت شد.");
    await refresh();await showReport();
  }catch(error){toast(error.message,true);}
});
$("invite-form").addEventListener("submit",async event=>{
  event.preventDefault();const formElement=event.currentTarget,f=new FormData(formElement),slots=[];
  for(const key of ["slot1","slot2","slot3"]){const value=f.get(key);if(value)slots.push(new Date(value).toISOString());}
  try{
    const result=await api("invitations",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({candidate_id:Number($("invite-candidate").value),job_id:Number($("invite-job").value),slots})});
    toast(result.email_status==="sent"?"دعوت ثبت و ایمیل شد.":"دعوت ثبت شد؛ ارسال ایمیل انجام نشد، تنظیمات را بررسی کن.",result.email_status!=="sent");
    formElement.reset();await refresh();
  }catch(error){toast(error.message,true);}
});
checkSession();