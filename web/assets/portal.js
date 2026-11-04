"use strict";
const $ = id => document.getElementById(id);
let allJobs = [];
const shorten = (text, max=170) => text && text.length > max ? text.slice(0,max).trim() + "…" : (text || "جزئیات این موقعیت توسط تیم جذب تکمیل می‌شود.");
function node(tag, className, text) {
  const item=document.createElement(tag);
  if(className)item.className=className;
  if(text!==undefined)item.textContent=text;
  return item;
}
function categories() {
  const options=[...new Set(allJobs.map(job=>job.category))].sort((a,b)=>a.localeCompare(b,'fa'));
  for(const id of ["category","side-category"]) {
    const field=$(id);
    for(const value of options) {
      const option=document.createElement("option");option.value=value;option.textContent=value;
      field.append(option);
    }
  }
}
function draw() {
  const search=$("side-search").value.trim().toLocaleLowerCase("fa");
  const category=$("side-category").value;
  const shown=allJobs.filter(job=>(!category||job.category===category) &&
    (!search||[job.title,job.description,...job.required_skills].join(" ").toLocaleLowerCase("fa").includes(search)));
  const list=$("jobs-list");list.replaceChildren();
  $("result-count").textContent=shown.length.toLocaleString("fa-IR")+" فرصت";
  if(!shown.length) {
    const empty=node("div","empty-state");
    empty.append(node("strong",null,allJobs.length?"موردی با این فیلتر پیدا نشد":"هنوز موقعیت شغلی منتشر نشده است"));
    empty.append(node("p",null,allJobs.length?"عبارت جستجو یا حوزه کاری را تغییر بده.":"موقعیت‌های جدید پس از انتشار مدیر اینجا دیده می‌شوند."));
    list.append(empty);return;
  }
  for(const job of shown) {
    const card=node("article","job-card");
    const info=node("div");
    const head=node("div","job-head");
    head.append(node("span","job-icon","✦"));
    const title=node("div");
    title.append(node("span","pill",job.category),node("h3",null,job.title));
    head.append(title);info.append(head);
    info.append(node("p",null,shorten(job.description)));
    const skills=node("div");
    for(const skill of job.required_skills.slice(0,5))skills.append(node("span","tag",skill));
    info.append(skills);
    const action=node("div","job-action");
    const btn=node("button","btn-primary","شروع مصاحبه ←");
    btn.type="button";
    btn.addEventListener("click",()=>openApply(job));
    action.append(btn,node("small",null,"مصاحبه تخصصی آنلاین"));
    card.append(info,action);list.append(card);
  }
}
function syncFilter(source,target) { $(target).value=$(source).value;draw(); }
function openApply(job) {
  $("apply-job").value=job.id;
  $("apply-title").textContent="مصاحبه "+job.title;
  $("apply-error").textContent="";
  $("apply-dialog").showModal();
}
$("close-dialog").addEventListener("click",()=>$("apply-dialog").close());
$("apply-dialog").addEventListener("click",event=>{
  if(event.target===$("apply-dialog"))$("apply-dialog").close();
});
$("side-category").addEventListener("change",()=>syncFilter("side-category","category"));
$("category").addEventListener("change",()=>syncFilter("category","side-category"));
$("side-search").addEventListener("input",()=>{$("search").value=$("side-search").value;draw();});
$("search").addEventListener("input",()=>{$("side-search").value=$("search").value;draw();});
$("reset-filters").addEventListener("click",()=>{
  for(const id of ["search","side-search","category","side-category"])$(id).value="";
  draw();
});
$("hero-search").addEventListener("submit",event=>{
  event.preventDefault();syncFilter("category","side-category");
  document.getElementById("jobs").scrollIntoView({behavior:"smooth",block:"start"});
});
$("apply-form").addEventListener("submit",async event=>{
  event.preventDefault();
  const button=$("submit-apply"),error=$("apply-error");
  error.textContent="";button.disabled=true;button.textContent="در حال ثبت درخواست…";
  try {
    const response=await fetch("/api/v1/public/applications",{method:"POST",
      credentials:"same-origin",body:new FormData(event.currentTarget)});
    const data=await response.json().catch(()=>({detail:"پاسخ نامعتبر سرویس"}));
    if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"ثبت درخواست موفق نبود");
    if(typeof data.interview_path!=="string"||!data.interview_path.startsWith("/candidate/#"))
      throw Error("لینک مصاحبه نامعتبر است");
    location.assign(data.interview_path);
  } catch (error) {
    error.textContent=error.message||"خطا در اتصال به سرویس";
  } finally {button.disabled=false;button.textContent="ورود به مصاحبه ←";}
});
(async function loadJobs() {
  try {
    const response=await fetch("/api/v1/public/jobs",{headers:{"Accept":"application/json"}});
    if(!response.ok)throw Error("خطا در بارگذاری فرصت‌های شغلی");
    allJobs=await response.json();
    $("hero-job-count").textContent=allJobs.length.toLocaleString("fa-IR");
    categories();draw();
  } catch(error) {
    $("jobs-list").replaceChildren(node("div","empty-state",error.message));
    $("result-count").textContent="خطا در دریافت";
  }
})();