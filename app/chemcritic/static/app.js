"use strict";
const $ = id => document.getElementById(id);
const form = $("experiment-form");
const field = name => form.elements.namedItem(name);
const assays = {unknown:"未知",isolated:"分离收率",gc:"GC收率",nmr:"NMR收率",lc:"LC收率",conversion:"转化率"};
const goals = {below_target:"未达到用户目标",met:"已达到用户目标",unavailable:"暂不能比较用户目标"};
const productLabels = {
  missing:"未提供结构表征证据。",
  contradictory:"记录中存在不支持目标产物的表征信息，请先核查。",
  user_report_only:"用户报告与目标匹配，但未附方法或观测值；系统未独立审核。",
  structured_documented:"已记录观测值，但本地无法完成核对（缺分子式或参照）；仍非独立核验。",
  structured_consistent:"用户所报数据经本地机械核对一致；不代表独立确证。",
  structured_warning:"用户所报数据存在待核查项，请查看警告原因；不代表独立确证。",
  structured_inconsistent:"用户所报数据与声明不一致，请先核对抄录与加合物。",
  human_review_recorded:"已记录人工复核信息，系统未读取其原始材料。",
};
const reasonLabels = {assay_mismatch:"结果口径不同，禁止直接比较数值。",assay_unknown:"结果口径未知，不能比较数值。",comparability_policy_pending:"同口径仍需核查条件；可比性规则未冻结，暂不进行数值比较。",mvp_numeric_disabled:"依B v0.2，MVP文献数值比较关闭；同口径也不能放行。"};
const reactionTypes = {suzuki_miyaura:"Suzuki–Miyaura 偶联",buchwald_hartwig:"Buchwald–Hartwig 胺化",heck:"Heck 反应",sonogashira:"Sonogashira 偶联",hydrogenation:"氢化 / 还原",oxidation:"氧化",condensation:"缩合 / 酯化 / 酰胺化",substitution:"取代 / 加成",other:"其他 / 未归类"};
const reactantRoles = {aryl_halide:"芳基卤化物 / 芳基磺酸酯",boronic_acid_or_ester:"硼酸 / 硼酸酯",amine:"胺（亲核试剂）",alkene:"烯烃",alkyne:"炔烃",electrophile:"亲电试剂",nucleophile:"亲核试剂",reagent:"试剂（氧化剂/还原剂）",other:"其他 / 未分类"};
const additiveTypes = {base:"碱",acid:"酸",salt:"盐 / 缓冲剂",oxidant:"氧化剂",reductant:"还原剂",ligand:"配体",cocatalyst:"助催化剂",phase_transfer:"相转移催化剂",surfactant:"表面活性剂 / 添加剂",other:"其他"};
// Engine tier vocabulary, mirrored from schema_v2.CLASSIFICATION_FIELDS.
const classificationFields = {
  catalyst_form:{label:"催化剂物理形态",values:{molecular_complex:"可溶分子配合物",in_situ_salt:"原位生成盐/配合物",nanoparticle:"纳米颗粒",supported:"负载型",bulk_metal:"块体金属"}},
  ligand_family:{label:"配体族",values:{phosphine:"膦类配体",non_phosphine:"非膦配体",none:"无配体"}},
  support:{label:"载体",values:{none:"无载体",solid_support:"固体载体"}},
  medium:{label:"反应介质",values:{aqueous:"水相",organic:"有机相",solventless:"无溶剂"}},
  activation_mode:{label:"活化方式",values:{thermal:"热",mechanochemical:"机械化学",microwave:"微波",photochemical:"光化学"}},
};
const ENGINE_SCOPE_LABEL = "Suzuki–Miyaura（芳基卤化物 + 硼酸/硼酸酯）";
let bootstrap, revision=0, evaluated=null, busy=false;

function fillSelect(select, options){
  select.replaceChildren();
  for(const [value,label] of Object.entries(options)) select.add(new Option(label,value));
}
for (const select of document.querySelectorAll(".assay-options")) fillSelect(select, assays);
fillSelect($("reaction-type"), reactionTypes);
for(const [key,spec] of Object.entries(classificationFields)){
  const label=document.createElement("label");
  label.textContent=spec.label;
  const select=document.createElement("select");
  select.name="classification_"+key;
  select.add(new Option("未声明 / 未知",""));
  for(const [value,text] of Object.entries(spec.values))select.add(new Option(text,value));
  label.append(select);$("classification-fields").append(label);
}
function message(text) { $("message").textContent=text; $("message").hidden=!text; }
function markDirty() {
  revision++; $("save").disabled=true; $("download").disabled=true;
  if(agentJob)$("agent-status").textContent="输入已修改；下方Agent回答对应上次提交的记录。";
  $("stale").hidden=!evaluated; $("saved-info").textContent="";
  if (evaluated) $("result-state").textContent="输入已修改";
}
function syncGoal() {
  const active=field("has_goal").checked;
  $("goal-fields").hidden=!active;
  field("minimum_yield_pct").required=active;
  field("minimum_yield_pct").disabled=!active;
  field("goal_metric").disabled=!active;
}
function selectedRoles(){return new Set([...document.querySelectorAll(".reactant-role")].map(select=>select.value));}
function currentScope(){
  const type=field("reaction_type").value;
  const label=type==="other"?(field("reaction_type_label").value.trim()||"其他"):(reactionTypes[type]||type);
  if(type!=="suzuki_miyaura"){
    return {in_scope:false,label,reason:`固定判定引擎只覆盖 ${ENGINE_SCOPE_LABEL}；本次记为「${label}」，只做事实复盘、证据缺口与目标判断，不做可比性判定或文献数值比较。`};
  }
  const roles=selectedRoles(), missing=[];
  const roleList=[...document.querySelectorAll(".reactant-role")].map(s=>s.value);
  const additiveList=[...document.querySelectorAll(".additive-type")].map(s=>s.value);
  const unsupported=[];
  for(const role of ["aryl_halide","boronic_acid_or_ester"])if(roleList.filter(r=>r===role).length>1)unsupported.push("同一角色有多条反应物");
  for(const kind of ["base","ligand"])if(additiveList.filter(t=>t===kind).length>1)unsupported.push("同类型碱或配体有多条记录");
  const reactantRows=[...document.querySelectorAll("#reactant-rows tr")];
  if(reactantRows.some(r=>r.querySelector(".reactant-limiting").checked&&r.querySelector(".reactant-role").value!=="aryl_halide"))unsupported.push("当量基准不是芳基卤化物");
  const declaredLigand=field("ligand").value.trim();
  if(declaredLigand&&[...document.querySelectorAll("#additive-rows tr")].some(r=>r.querySelector(".additive-type").value==="ligand"&&r.querySelector(".additive-name").value.trim()!==declaredLigand))unsupported.push("两处配体声明不同");
  if(field("metric").value==="lc")unsupported.push("固定引擎不支持LC口径");
  if(unsupported.length)return {in_scope:false,label,reason:unsupported.join("；")+"。保留完整记录，但不静默选取或换算引擎输入。"};
  if(!roles.has("aryl_halide"))missing.push("芳基卤化物");
  if(!roles.has("boronic_acid_or_ester"))missing.push("硼酸 / 硼酸酯");
  if(!field("product_name").value.trim())missing.push("目标产物");
  if(missing.length)return {in_scope:false,label,reason:`本次记为 Suzuki–Miyaura，但角色未声明：${missing.join("、")}。角色由你声明、系统不推断，因此暂不判定。`};
  return {in_scope:true,label,reason:`本次属于 ${ENGINE_SCOPE_LABEL} 档案，会运行固定引擎（固定库 44 条记录）。`};
}
function classificationMissing(){
  return Object.keys(classificationFields).filter(key=>!(field("classification_"+key)||{}).value);
}
function syncScope(){
  const scope=currentScope();
  const missing=scope.in_scope?classificationMissing():[];
  $("reaction-type-other-wrap").hidden=field("reaction_type").value!=="other";
  $("agent-start").textContent=scope.in_scope?"评估并生成下一轮方案":"生成事实复盘与下一步核查";
  // One scope line only: the form banner duplicated this text, so it is gone and
  // the classification gap is reported here instead.
  if(!agentJob)$("agent-scope").textContent="当前表单 "+(scope.in_scope?"可判定":"不判定")+" — "+scope.reason+
    (missing.length?` 催化体系分类还缺 ${missing.map(key=>classificationFields[key].label).join("、")}，档内定位会保持“无法判定”。`:"");
}
function makeInput(type,value,className,extra){
  const input=document.createElement("input");input.type=type;input.className=className||"";
  if(value!==null&&value!==undefined&&value!=="")input.value=String(value);
  if(extra)Object.assign(input,extra);
  return input;
}
function makeSelect(options,value,className){
  const select=document.createElement("select");select.className=className||"";
  for(const [optionValue,label] of Object.entries(options))select.add(new Option(label,optionValue));
  select.value=options[value]!==undefined?value:Object.keys(options)[0];
  return select;
}
function addRemoveCell(row){
  const cell=document.createElement("td"),button=document.createElement("button");
  button.type="button";button.className="button text-button";button.textContent="删除";
  button.addEventListener("click",()=>{row.remove();syncScope();markDirty();});
  cell.append(button);row.append(cell);
}
function addReactantRow(item){
  const row=document.createElement("tr");
  for(const control of [makeInput("text",item?.name,"reactant-name",{required:true,placeholder:"名称"}),
                        makeSelect(reactantRoles,item?.role||"other","reactant-role"),
                        makeInput("number",item?.equivalents,"reactant-eq",{min:"0",step:"any"}),
                        (()=>{const box=makeInput("checkbox",null,"reactant-limiting");box.checked=Boolean(item?.limiting);return box;})()]){
    const cell=document.createElement("td");cell.append(control);row.append(cell);
  }
  addRemoveCell(row);$("reactant-rows").append(row);
}
function addAdditiveRow(item){
  const row=document.createElement("tr");
  for(const control of [makeInput("text",item?.name,"additive-name",{required:true,placeholder:"名称"}),
                        makeSelect(additiveTypes,item?.type||"base","additive-type"),
                        makeInput("number",item?.equivalents,"additive-eq",{min:"0",step:"any"}),
                        makeInput("number",item?.loading_mol_pct,"additive-molpct",{min:"0",step:"any"})]){
    const cell=document.createElement("td");cell.append(control);row.append(cell);
  }
  addRemoveCell(row);$("additive-rows").append(row);
}
// Evidence rows collect observation values, not just a verdict: a bare "matches"
// and a peak list that survives arithmetic are different evidence, and the
// backend grades them differently.
function addEvidenceRow(item){
  const row=document.createElement("tr");
  const method=makeInput("text",item?.method,"evidence-method",{placeholder:"如1H NMR"});
  const supports=makeSelect({true:"与目标一致",false:"与目标不一致"},String(item?.supports_target!==false),"evidence-supports");
  const observed=makeInput("text",item?.observation_text,"evidence-text",{placeholder:"δ 7.58 (d, J=8.8 Hz, 2H)…"});
  const integral=makeInput("number",item?.proton_integral,"evidence-integral",{min:"0",step:"any",placeholder:"积分总数"});
  const mass=makeInput("number",item?.mz,"evidence-mz",{min:"0",step:"any",placeholder:"实测 m/z"});
  const formula=makeInput("text",item?.formula,"evidence-formula",{placeholder:"如 C13H12O"});
  const reference=makeInput("text",item?.spectrum_reference,"evidence-spectrum",{placeholder:"谱图/附件编号"});
  for(const control of [method,supports,observed,integral,mass,formula,reference]){
    const cell=document.createElement("td");cell.append(control);row.append(cell);
  }
  // Provenance, review reference and adduct are preserved without re-asking.
  row.dataset.provenance=item?.provenance||"user_report";
  row.dataset.reviewReference=item?.review_reference||"";
  row.dataset.adduct=item?.mz_adduct||"";
  row.dataset.rawSpectrum=item?.raw_spectrum_provided?"1":"";
  if(row.dataset.provenance==="human_review"){
    const badge=document.createElement("span");badge.className="evidence-badge";badge.textContent="人工复核";
    method.parentElement.append(badge);
  }
  addRemoveCell(row);$("evidence-rows").append(row);
}
function readEvidenceRows(){
  return [...document.querySelectorAll("#evidence-rows tr")].map(row=>{
    const method=row.querySelector(".evidence-method").value.trim();
    if(!method)return null;
    const data=row.dataset||{};
    const entry={method,supports_target:row.querySelector(".evidence-supports").value==="true",
      provenance:data.provenance||"user_report",raw_spectrum_provided:Boolean(data.rawSpectrum)};
    if(entry.provenance==="human_review"&&data.reviewReference)entry.review_reference=data.reviewReference;
    const observed=row.querySelector(".evidence-text").value.trim();
    if(observed)entry.observation_text=observed;
    const integral=row.querySelector(".evidence-integral").value;
    if(integral!=="")entry.proton_integral=Number(integral);
    const mass=row.querySelector(".evidence-mz").value;
    if(mass!=="")entry.mz=Number(mass);
    const formula=row.querySelector(".evidence-formula").value.trim();
    if(formula)entry.formula=formula;
    const reference=row.querySelector(".evidence-spectrum").value.trim();
    if(reference)entry.spectrum_reference=reference;
    if(data.adduct)entry.mz_adduct=data.adduct;
    return entry;
  }).filter(Boolean);
}
function readRows(bodyId,nameClass,extra){
  return [...document.querySelectorAll("#"+bodyId+" tr")].map(row=>{
    const name=row.querySelector("."+nameClass).value.trim();
    if(!name)return null;
    return Object.assign({name},extra(row));
  }).filter(Boolean);
}
function readExperiment() {
  const text=name=>{const element=field(name);return element&&element.value.trim()?element.value.trim():null;};
  const number=name=>{const element=field(name);return !element||element.value===""?null:Number(element.value);};
  const reactants=readRows("reactant-rows","reactant-name",row=>({
    role:row.querySelector(".reactant-role").value,
    equivalents:row.querySelector(".reactant-eq").value===""?null:Number(row.querySelector(".reactant-eq").value),
    limiting:row.querySelector(".reactant-limiting").checked,
    role_source:"user_stated"}));
  const additives=readRows("additive-rows","additive-name",row=>({
    type:row.querySelector(".additive-type").value,
    equivalents:row.querySelector(".additive-eq").value===""?null:Number(row.querySelector(".additive-eq").value),
    loading_mol_pct:row.querySelector(".additive-molpct").value===""?null:Number(row.querySelector(".additive-molpct").value)}));
  if(!reactants.length)throw new Error("至少填写一条反应物及其角色。");
  if(!text("product_name"))throw new Error("请填写目标产物。");
  const limitingIndex=reactants.findIndex(item=>item.limiting);
  if(reactants.filter(item=>item.limiting).length>1)throw new Error("只能勾选一个限量试剂（当量基准）。");
  const classification={};
  for(const key of Object.keys(classificationFields))classification[key]=(field("classification_"+key).value||null);
  return {schema_version:"chemcritic.experiment.v0.2",experiment_id:text("experiment_id"),simulated:field("simulated").value==="true",
    reaction:{type:field("reaction_type").value,type_label:text("reaction_type_label"),reactants,
      product:{name:text("product_name")},
      equivalents_basis:limitingIndex>=0?{reactant_index:limitingIndex,label:reactants[limitingIndex].name}:null},
    catalyst:{name:text("catalyst"),loading_mol_pct:number("catalyst_loading_mol_pct"),loading_basis:text("catalyst_loading_basis"),
      ligand:{name:text("ligand"),loading_mol_pct:number("ligand_loading_mol_pct")},classification},
    additives,
    additives_listed_complete:field("additives_complete").checked?true:null,
    additive_declarations:{},
    conditions:{solvent_system:{primary:text("solvent_primary"),cosolvent:text("solvent_cosolvent"),ratio:text("solvent_ratio"),
        volume_ml:number("solvent_volume_ml"),water_content:field("water_content").value},
      temperature_C:number("temperature_C"),time_h:number("time_h"),atmosphere:text("atmosphere"),
      scale_mmol:number("scale_mmol"),pressure_bar:number("pressure_bar"),irradiation:text("irradiation"),addition_mode:text("addition_mode")},
    results:{value_pct:number("value_pct"),metric:text("metric")||"unknown",basis:text("basis"),method:text("results_method"),
      internal_standard:text("internal_standard"),
      characterization:readEvidenceRows(),
      repeat_attempts:number("repeat_attempts"),replicates:[]},
    user_goal:field("has_goal").checked?{minimum_yield_pct:number("minimum_yield_pct"),metric:text("goal_metric")||"unknown"}:null};
}
function payload() {return {experiment:readExperiment(),sciencepal_text:$("source-text").value};}
async function api(path,body) {
  const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok) throw new Error([data.error,data.field,data.message].filter(Boolean).join(" · "));
  return data;
}
function appendText(parent,tag,text,className) {
  const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;parent.append(node);return node;
}
function appendReportInline(parent,text){
  for(const part of text.split(/(\*\*[^*]+\*\*)/g)){
    if(part)appendText(parent,part.startsWith("**")&&part.endsWith("**")?"strong":"span",part.startsWith("**")&&part.endsWith("**")?part.slice(2,-2):part);
  }
}
function renderTeamBody(parent,text){
  const lines=text.split(/\r?\n/);let list=null;
  const cells=line=>line.trim().replace(/^\|/,"").replace(/\|$/,"").split("|").map(s=>s.trim());
  for(let i=0;i<lines.length;i++){
    const line=lines[i];if(!line.trim()){list=null;continue;}
    if(line.trim().startsWith("|")&&i+1<lines.length&&cells(lines[i+1]).every(s=>/^:?-{3,}:?$/.test(s))){
      list=null;const wrap=appendText(parent,"div","","team-table-scroll");const table=appendText(wrap,"table","");
      const head=appendText(table,"thead","");const row=appendText(head,"tr","");
      for(const value of cells(line))appendReportInline(appendText(row,"th",""),value);
      const body=appendText(table,"tbody","");i++;
      while(i+1<lines.length&&lines[i+1].trim().startsWith("|")){
        const tr=appendText(body,"tr","");for(const value of cells(lines[++i]))appendReportInline(appendText(tr,"td",""),value);
      }
      continue;
    }
    if(/^\s*```/.test(line)){
      list=null;const code=[];while(i+1<lines.length&&!/^\s*```/.test(lines[i+1]))code.push(lines[++i]);
      if(i+1<lines.length)i++;appendText(parent,"pre",code.join("\n"));continue;
    }
    const numbered=line.match(/^\s*(\d+)[.)、]\s*(.+)$/);
    if(numbered){
      if(!list||list.__listKind!=="ol"){list=appendText(parent,"ol","");list.__listKind="ol";list.start=Number(numbered[1]);}
      appendReportInline(appendText(list,"li",""),numbered[2]);
    }else if(/^\s*[-*]\s+/.test(line)){
      if(!list||list.__listKind!=="ul"){list=appendText(parent,"ul","");list.__listKind="ul";}appendReportInline(appendText(list,"li",""),line.replace(/^\s*[-*]\s+/,""));
    }else{
      list=null;appendReportInline(appendText(parent,/^\s*#{1,6}\s/.test(line)?"h4":"p",""),line.replace(/^\s*#{1,6}\s+/,""));
    }
  }
}
function render(result) {
  $("empty-result").hidden=true;$("result").hidden=false;
  $("stale").hidden=true;$("simulation-banner").hidden=!result.simulated;
  $("result-state").textContent=result.status==="S3"?"S3 · 证据不足":"评估完成 · 分维度报告";
  const goal=result.goal_comparison;
  $("goal-title").textContent=goals[goal.state];
  const noGoal={goal_not_set:"用户未设目标，系统不以文献替用户定义成功。",outcome_missing:"缺少实测结果。",assay_unknown:"实测或目标口径未知。",assay_mismatch:"实测与目标口径不同，不能直接判断。",evidence_gap:"结构证据缺失或矛盾，依B v0.2先补证据，暂不输出数值结论。"};
  $("goal-description").textContent=goal.state==="unavailable"?noGoal[goal.reason]:goal.gap_pp>0?`按用户所报数据，距目标差${goal.gap_pp}个百分点。`:`按用户所报数据，${goal.gap_pp===0?"恰好达到目标":"超过目标"+Math.abs(goal.gap_pp)+"个百分点"}。`;
  $("next-checks").replaceChildren();
  if(!result.next_checks?.length)appendText($("next-checks"),"p",result.next_checks?"当前规则未触发额外优先行动；不代表科学证据已全部核验。":"旧版历史快照未生成优先行动；修改后重新评估可使用新版规则。","hint");
  for(const action of result.next_checks||[]){
    const card=appendText($("next-checks"),"div","","action-card");
    appendText(card,"h4",`${action.priority}. ${action.title}`);appendText(card,"p",action.why);
    const list=appendText(card,"ul","");for(const material of action.requested_materials)appendText(list,"li",material);
    appendText(card,"p","补齐后："+action.expected_resolution);appendText(card,"p",action.limits,"hint");
    if(action.related_sources.length){appendText(card,"p","相关条件记录（用于核查字段，不是原因证据）：","hint");
      for(const source of action.related_sources){const p=appendText(card,"p",""),link=appendText(p,"a",source.record_id+" · "+source.locator);const url=new URL(source.url);if(["http:","https:"].includes(url.protocol)){link.href=url.href;link.target="_blank";link.rel="noopener noreferrer";}}
    }
  }
  const evidence=result.product_evidence||{};
  $("product-evidence").textContent=(productLabels[evidence.state]||evidence.label||evidence.state||productLabels.missing)+
    (evidence.reasons?.length?" 依据："+evidence.reasons.slice(0,3).join("；")+"。":"")+
    (evidence.traceability==="attachment_recorded"?"（已登记谱图/附件编号）":"");
  const retrieval=result.retrieval;
  const modeLabels={local_library_exact_pair:"团队本地库 · 完整底物对匹配",local_library_out_of_engine_scope:"团队本地库仅含 Suzuki 记录 · 本次反应不在判定范围",sciencepal_file_import:"SciencePal文件导入",provided_records:"用户提供先例"};
  $("retrieval-summary").textContent=`${modeLabels[retrieval.mode]||retrieval.mode} · ${retrieval.record_count}条结果记录 · ${retrieval.independent_publication_count??"未统计"}篇可识别DOI的论文。未进行实时检索。`;
  $("sources").replaceChildren();
  if(!result.precedent_comparisons.length) appendText($("sources"),"p",retrieval.no_match?"本地案例库未命中该底物对；不代表公开文献不存在先例。":"未提供文献先例；不表示不存在相关文献。","hint");
  for(const source of result.precedent_comparisons) {
    const card=appendText($("sources"),"div","","source-card");
    appendText(card,"p",source.record_id,"label");
    appendText(card,"p",reasonLabels[source.reason]||source.reason);
    appendText(card,"p",source.locator,"hint");
    const link=appendText(card,"a","打开文献原文 ↗");
    const url=new URL(source.url);
    if(["http:","https:"].includes(url.protocol)){link.href=url.href;link.target="_blank";link.rel="noopener noreferrer";}
    for(const [index,address] of (source.source_links||[]).entries()){
      if(address===source.url)continue;
      const parsed=new URL(address);if(!["http:","https:"].includes(parsed.protocol))continue;
      const p=appendText(card,"p",""),extra=appendText(p,"a",`来源入口${index+1}（原文 / SI） ↗`);
      extra.href=parsed.href;extra.target="_blank";extra.rel="noopener noreferrer";
    }
    appendText(card,"p",source.provenance==="team_workbook_report_unverified_locally"?"团队工作簿先例 · 本工程未独立核验原文":"SciencePal文件报告 · 原文与工具日志未独立核验","hint");
    for(const warning of source.import_metadata?.warnings||[])appendText(card,"p",warning,"hint");
    if(source.reported_outcome){const outcome=source.reported_outcome;
      appendText(card,"p",`文献报告值：${outcome.value_pct??"未知"}${outcome.value_pct==null?"":"%"}；${outcome.original_metric||assays[outcome.yield_type]||"口径未知"}。仅展示来源报告，不与本次结果作高低判断。`);
    }
    if(source.field_comparisons?.length){
      const details=document.createElement("details");card.append(details);appendText(details,"summary","查看逐字段差异（相同 / 不同 / 未知）");
      const scroll=appendText(details,"div","","comparison-scroll"),table=appendText(scroll,"table","","comparison-table");
      const head=appendText(table,"thead",""),headRow=appendText(head,"tr","");for(const label of ["维度","本次记录","文献记录","关系"])appendText(headRow,"th",label);
      const body=appendText(table,"tbody","");
      const display=value=>value==null?"未知":Array.isArray(value)?value.map(v=>v??"未知").join(" + "):({present:"已加入",absent:"明确未加入",unknown:"未知"}[value]||assays[value]||String(value));
      for(const item of source.field_comparisons){const row=appendText(body,"tr","");for(const value of [item.label,display(item.actual),display(item.precedent),{same:"相同",different:"不同",unknown:"未知"}[item.state]])appendText(row,"td",value);}
      appendText(details,"p","关系仅按记录值及少量明确别名对齐，不代表化学体系等价、反应活性相同或因果解释。","hint");
    }
    if(source.gate_diagnostics){
      const details=appendText(card,"details","");appendText(details,"summary","查看八维门槛工程诊断（试接入）");
      appendText(details,"p","仅用于核对引擎接入，未授权文献数值比较；不改变上方复盘判断。","hint");
      const peers=source.gate_diagnostics.reference_set?.same_publication_record_ids||[];
      if(peers.length)appendText(details,"p",`与 ${peers.join("、")} 来自同一DOI论文，不计为独立文献来源。`,"hint");
      appendText(details,"pre",JSON.stringify(source.gate_diagnostics,null,2));
    }
    if(Object.keys(source.field_evidence||{}).length){const details=document.createElement("details");card.append(details);appendText(details,"summary","查看逐字段来源定位");appendText(details,"pre",JSON.stringify(source.field_evidence,null,2));}
    for(const limit of source.limitations||[])appendText(card,"p",limit,"hint");
  }
  const boundaries={causal_attribution:"不能据此确定未达目标的具体原因。",precedent_numeric:"当前不进行文献收率高低或优劣判断。",repeatability:"当前不评价实验重复性；重复次数本身不足以证明稳定。",target_comparison:"用户目标比较暂不可用。",engine_scope:"本次反应不在固定判定引擎范围内，未做可比性判定。"};
  $("boundaries").replaceChildren();for(const key of result.blocked_dimensions)appendText($("boundaries"),"li",boundaries[key]||key);
  $("policy-note").textContent=`B v0.2：MVP文献数值比较关闭。${(result.pending_decisions||[]).join(" ")} 当前未启用LLM或原因诊断。`;
  $("followups").replaceChildren();for(const followup of result.followups)appendText($("followups"),"li",followup.question);
  if(!result.followups.length)appendText($("followups"),"li","当前规则未发现额外必问字段；不代表化学记录已完整核验。");
  $("raw-result").textContent=JSON.stringify(result,null,2);$("save").disabled=false;$("download").disabled=false;
}
function fill(data,sourceText) {
  form.reset();
  const e=data||{},c=e.conditions||{},s=c.solvent_system||{},cat=e.catalyst||{},lig=cat.ligand||{},r=e.results||{},g=e.user_goal||{};
  field("experiment_id").value=e.experiment_id||"";
  field("simulated").value=String(e.simulated===true);
  const reaction=e.reaction||{};
  field("reaction_type").value=reactionTypes[reaction.type]?reaction.type:"other";
  field("reaction_type_label").value=reaction.type_label||"";
  $("reactant-rows").replaceChildren();
  for(const item of reaction.reactants||[])addReactantRow(item);
  if(!(reaction.reactants||[]).length)addReactantRow({role:"aryl_halide"});
  field("product_name").value=(reaction.product||{}).name||"";
  field("catalyst").value=cat.name||"";
  field("catalyst_loading_mol_pct").value=cat.loading_mol_pct??"";
  field("catalyst_loading_basis").value=cat.loading_basis||"";
  field("ligand").value=lig.name||"";
  field("ligand_loading_mol_pct").value=lig.loading_mol_pct??"";
  const declared=cat.classification||{};
  for(const key of Object.keys(classificationFields))(field("classification_"+key)||{value:""}).value=declared[key]||"";
  $("additive-rows").replaceChildren();
  for(const item of e.additives||[])addAdditiveRow(item);
  field("additives_complete").checked=e.additives_listed_complete===true;
  field("solvent_primary").value=s.primary||"";
  field("solvent_cosolvent").value=s.cosolvent||"";
  field("solvent_ratio").value=s.ratio||"";
  field("solvent_volume_ml").value=s.volume_ml??"";
  field("water_content").value=s.water_content||"unknown";
  field("temperature_C").value=c.temperature_C??"";
  field("time_h").value=c.time_h??"";
  field("atmosphere").value=c.atmosphere||"";
  field("scale_mmol").value=c.scale_mmol??"";
  field("pressure_bar").value=c.pressure_bar??"";
  field("irradiation").value=c.irradiation||"";
  field("addition_mode").value=c.addition_mode||"";
  field("value_pct").value=r.value_pct??"";
  field("metric").value=r.metric||"unknown";
  field("basis").value=r.basis||"";
  field("results_method").value=r.method||"";
  field("internal_standard").value=r.internal_standard||"";
  const evidence=r.characterization||[];
  $("evidence-rows").replaceChildren();
  for(const item of evidence)addEvidenceRow(item);
  field("repeat_attempts").value=r.repeat_attempts??"";
  field("has_goal").checked=Boolean(g&&g.minimum_yield_pct!=null);
  field("minimum_yield_pct").value=g.minimum_yield_pct??"";
  field("goal_metric").value=g.metric||"unknown";
  $("source-text").value=sourceText||""; $("source-file").value="";
  $("source-name").textContent=sourceText?"已载入SciencePal原始JSON；可展开查看。":"当前不提供先例。";
  syncGoal(); syncScope(); markDirty();
}
form.addEventListener("input",event=>{if(event.target.id!=="source-file"){syncGoal();syncScope();markDirty();}});
form.addEventListener("change",event=>{if(event.target.id!=="source-file"){syncGoal();syncScope();markDirty();}});
$("add-reactant").addEventListener("click",()=>{addReactantRow({});syncScope();markDirty();});
$("add-additive").addEventListener("click",()=>{addAdditiveRow({});markDirty();});
$("add-evidence").addEventListener("click",()=>{addEvidenceRow({});markDirty();});
$("source-text").addEventListener("input",()=>{$("source-name").textContent="已编辑原始JSON，需重新复盘。";});
$("source-file").addEventListener("change",async()=>{
  const file=$("source-file").files[0];if(!file)return;markDirty();const version=revision;
  try {if(file.size>1024*1024)throw new Error("先例文件不能超过1MB。");const text=await file.text();JSON.parse(text.replace(/^\uFEFF/,""));if(revision!==version)return;$("source-text").value=text;$("source-name").textContent="已选择："+file.name;message("");}
  catch(error){message(error.message);$("source-file").value="";}
});
$("clear-source").addEventListener("click",()=>{$("source-text").value="";$("source-file").value="";$("source-name").textContent="当前不提供先例。";markDirty();});
$("load-library").addEventListener("click",async()=>{
  if(busy)return;const version=revision;$("load-library").disabled=true;
  try{const library=await api("/api/library");if(revision!==version){message("输入已变化，请再次载入先例库。");return;}$("source-text").value=JSON.stringify(library);$("source-file").value="";$("source-name").textContent=`已载入团队库：${library.metadata.record_count}条结果记录、${library.metadata.independent_publication_count}篇论文。评估时按底物对匹配。`;markDirty();message("");}catch(error){message(error.message);}finally{$("load-library").disabled=false;}
});
$("load-example").addEventListener("click",()=>{if(bootstrap){fill(bootstrap.experiment,bootstrap.sciencepal_text);message("已载入模拟示例。修改后点击开始复盘。");}});
form.addEventListener("submit",async event=>{
  if(event.submitter?.id!=="evaluate"){event.preventDefault();message("请点击右侧按钮提交给Agent，避免意外创建任务。");return;}
  event.preventDefault();if(busy)return;busy=true;$("evaluate").disabled=true;$("save").disabled=true;$("download").disabled=true;message("正在评估…");
  const version=revision;
  try {const input=payload();const {result}=await api("/api/review",input);if(version!==revision){message("评估期间输入已修改，请重新复盘。");return;}evaluated={payload:input,result,revision:version};render(result);$("saved-info").textContent="尚未保存";message("");}
  catch(error){message(error.message);$("stale").hidden=!evaluated;}
  finally{busy=false;$("evaluate").disabled=false;}
});
$("save").addEventListener("click",async()=>{
  if(!evaluated||evaluated.revision!==revision||busy)return;busy=true;$("save").disabled=true;
  const version=revision;
  try{const record=await api("/api/reviews",evaluated.payload);if(version===revision)$("saved-info").textContent="已保存 · "+new Date(record.created_at).toLocaleString()+" · "+record.id;await loadHistory();}
  catch(error){message(error.message);if(version===revision)$("save").disabled=false;}
  finally{busy=false;}
});
$("download").addEventListener("click",()=>{
  if(!evaluated||evaluated.revision!==revision)return;
  const blob=new Blob([JSON.stringify({...evaluated.payload,result:evaluated.result},null,2)],{type:"application/json;charset=utf-8"});
  const url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download="chemcritic-review.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
async function loadHistory() {
  const records=await api("/api/history");$("history").replaceChildren();
  if(!records.length)appendText($("history"),"p","还没有保存记录。完成复盘后点击保存。","hint");
  for(const record of records){const row=appendText($("history"),"div","","history-row"),info=appendText(row,"div","");
    appendText(info,"strong",record.display_title||record.experiment_id);
    appendText(info,"small",`实验编号：${record.experiment_id}`);
    appendText(info,"small",`${record.simulated?"模拟":"真实记录"} · ${new Date(record.created_at).toLocaleString()} · ${goals[record.goal_state]||record.goal_state}`);
    const button=appendText(row,"button","打开","button secondary");button.addEventListener("click",async()=>{if(busy)return;
      try{const recordData=await api("/api/history/"+record.id);fill(recordData.experiment,recordData.sciencepal_text);evaluated={payload:{experiment:recordData.experiment,sciencepal_text:recordData.sciencepal_text},result:recordData.result,revision};render(recordData.result);$("save").disabled=true;$("saved-info").textContent="历史快照 · "+new Date(recordData.created_at).toLocaleString()+" · "+recordData.id;message("已打开历史快照。修改后重新评估，可另存新记录。");$("result-title").scrollIntoView({behavior:"smooth"});}catch(error){message(error.message);}});
  }
}
$("refresh-history").addEventListener("click",()=>loadHistory().catch(error=>message(error.message)));
let agentJob=null,agentVersion=null,agentInput=null,agentRequest=null;
function adviceWithoutRatingTable(text){
  const lines=text.split(/\r?\n/),out=[];let number=0;
  const cells=line=>line.trim().replace(/^\|/,"").replace(/\|$/,"").split("|").map(v=>v.trim());
  for(let i=0;i<lines.length;i++){
    if(lines[i].trim().startsWith("|")&&/优先级/.test(lines[i])&&i+1<lines.length&&cells(lines[i+1]).every(v=>/^:?-{3,}:?$/.test(v))){
      i++;
      while(i+1<lines.length&&lines[i+1].trim().startsWith("|")){
        const row=cells(lines[++i]);
        if(row.length>=2)out.push(`${++number}. **${row[1]}**${row[2]?"。"+row[2]:""}`);
      }
    }else out.push(lines[i].replace(/[★☆]+/g,""));
  }
  return out.join("\n");
}
function chineseReportContent(body,kind){
  // Display-only: exact answers and exports retain every original paragraph.
  if(!["evaluation","advice","missing"].includes(kind))return body;
  const narrative=line=>!/[\u3400-\u9fff]/.test(line)&&
    (line.match(/[A-Za-z]+(?:['’-][A-Za-z]+)*/g)||[]).length>=8&&
    !/https?:\/\/|\bDOI\b|^\s*\|/i.test(line);
  const lines=body.split(/\r?\n/);
  const filtered=lines.filter(line=>!narrative(line)).join("\n").trim();
  return filtered||"本分区未返回中文正文，请展开完整原始回答核查。";
}
function renderAgentAnswer(answer){
  $("agent-answer").textContent=answer||"尚未收到完整回答。";
  $("agent-cards").replaceChildren();
  if(!answer){$("agent-display-note").textContent="等待Agent返回完整回答。";return;}
  let visible=answer;
  if(!visible.includes("\n")&&visible.includes("\\n"))visible=visible.replace(/\\r\\n|\\n/g,"\n");
  const end=visible.lastIndexOf("</think>");
  if(end>=0)visible=visible.slice(end+8);
  else if(visible.includes("<think>")){
    $("agent-display-note").textContent="回答中包含未闭合的草稿标记，暂不分区。可展开原始回答核查。";return;
  }
  // Hide the repeated condition table and process preamble in the display only.
  // The exact original remains in agent-answer and in the exported snapshot.
  const teamHeaders=["本次用到的条件","能不能与文献值并排比较","为什么","下一步该做什么","下一轮实验","实验评价","实验建议","依据与限制","效果评估","缺失与追问","证据与来源","实验信息","推断边界","本次文献检索","下一步方案","补充问题"];
  const teamMatches=Array.from(visible.matchAll(/^\s*#{2,4}\s*(?:[一二三四五]、)?([^\n]+)\n/gm)).filter(m=>teamHeaders.some(t=>m[1].includes(t)));
  if(teamMatches.length){
    const groups={evaluation:[],advice:[],missing:[],evidence:[],experiment:[],boundaries:[]};
    teamMatches.forEach((m,i)=>{
      const content=visible.slice(m.index+m[0].length,i+1<teamMatches.length?teamMatches[i+1].index:visible.length).trim();
      const kind=/实验建议|下一步该做什么|下一轮实验|下一步方案/.test(m[1])?"advice":/缺失与追问|补充问题/.test(m[1])?"missing":/依据与限制|证据与来源|本次文献检索/.test(m[1])?"evidence":/本次用到的条件|实验信息/.test(m[1])?"experiment":/推断边界/.test(m[1])?"boundaries":"evaluation";
      groups[kind].push((m[1].includes("为什么")?"#### 条件差异与待核查事项\n":"")+content);
    });
    const empty={missing:"本次报告未单独列出追问，可查看实验建议中的待核查事项。",evidence:"本次报告未单独提供来源，请在原始回答中核对。",experiment:"本次原始实验输入保留在导出文件中。",boundaries:"本次报告未单独提供推断边界；页面展示不代表结论已独立核验。"};
    for(const [kind,title] of [["evaluation","效果评估"],["advice","实验建议"],["missing","缺失与追问"],["evidence","证据与来源"],["experiment","实验信息"],["boundaries","推断边界"]]){
      const secondary=["evidence","experiment","boundaries"].includes(kind);
      if(!groups[kind].length&&!empty[kind])continue;
      const card=appendText($("agent-cards"),secondary?"details":"section","",kind==="evaluation"?"goal-card agent-assessment":"result-section agent-report-section"+(secondary?" agent-supporting":""));
      appendText(card,secondary?"summary":"h3",title);
      if(!groups[kind].length){appendText(card,"p",empty[kind],"hint");continue;}
      const body=chineseReportContent(groups[kind].join("\n\n"),kind);
      renderTeamBody(appendText(card,"div","","team-report-body"),kind==="advice"?adviceWithoutRatingTable(body):body);
    }
    $("agent-display-note").textContent="";
    return;
  }
  const definitions=[
    ["效果评估",/效果|评估|可比性|目标比较|现在能判断|当前能判断|结果分析/],
    ["优先核查行动与方案",/下一步|后续方案|行动方案|建议方案|优先核查|行动建议/],
    ["证据与来源",/文献|检索|参考来源|证据与来源/],
    ["推断边界",/推断边界|局限|限制说明|不确定性/],
    ["实验信息",/已知|事实|实验信息|实验概况|待确认信息/],
    ["缺失与追问",/补充问题|待补|追问|必要.*问题|需要.*补充|补查.*记录/]
  ];
  const sections=definitions.map(([title])=>({title,lines:[]}));
  // When Markdown sections exist, only that section level can change cards.
  // Bold subheadings and numbered questions remain in their parent section.
  const markdownLevels=visible.split(/\r?\n/).flatMap(line=>{
    const m=line.match(/^\s*(#{1,6})\s+(.+)$/);
    if(!m)return [];
    const title=m[2].replace(/\*\*|__/g,"");
    if(/ChemCritic|评估报告|复盘报告/.test(title))return [];
    return definitions.some(([,pattern])=>pattern.test(title))?[m[1].length]:[];
  });
  const sectionLevel=markdownLevels.length?Math.min(...markdownLevels):null;
  const other={title:"其他说明",lines:[]};let current=other;
  for(const line of visible.split(/\r?\n/)){
    if(/^\s*(?:回复|输入|发送)[“"「']?展开[”"」']?/.test(line.trim()))continue;
    const normalized=line.trim().replace(/^#{1,6}\s*/,"").replace(/\*\*|__/g,"");
    const title=normalized.replace(/^(?:[（(]?[一二三四五六七八九十\d]+[）).、．:]\s*|[①②③④⑤]\s*)/,"");
    const explicit=/^\s*(?:#{1,6}|\*\*|__|[（(]?[一二三四五六七八九十\d]+[）).、．:]|[①②③④⑤])/.test(line);
    const md=line.match(/^\s*(#{1,6})\s+/);
    if(md&&/ChemCritic|评估报告|复盘报告/.test(title))continue;
    const heading=!/^\s*[-*•]\s+/.test(line)&&title.length<=100&&(sectionLevel!==null?!!md&&md[1].length===sectionLevel:(explicit||definitions.some(([,pattern])=>pattern.test(title)&&title.length<=25)));
    if(heading){
      if(/ChemCritic|评估报告|复盘报告/.test(title))continue;
      const index=definitions.findIndex(([,pattern])=>pattern.test(title));
      if(index>=0){
        current=sections[index];
        const inline=title.match(/^(.{1,25}?)[：:]\s*(.+)$/);
        if(inline)current.lines.push(title);
        continue;
      }
    }
    current.lines.push(line);
  }
  const matched=sections.some(section=>section.lines.some(line=>line.trim()));
  $("agent-display-note").textContent=matched?"按Agent原回答标题分区，未改写内容；来源与建议仍需核查。":"本次回答未包含可识别的分区标题，已保留在“其他说明”中。";
  if(!matched&&/report has been delivered|task is complete|chemcritic_report\.md|报告已.*(?:交付|保存)/i.test(visible))$("agent-display-note").textContent="目前收到的是交付通知，尚未取得报告正文。请点击“读取原任务报告”，无需重新创建任务。";
  const priority=["效果评估","优先核查行动与方案","缺失与追问","证据与来源","实验信息","推断边界"];
  const ordered=priority.map(title=>sections.find(s=>s.title===title));
  for(const section of [...ordered,other]){
    const content=section.lines.join("\n").trim();
    if(!content)continue;
    const secondary=["证据与来源","实验信息","推断边界"].includes(section.title);
    const card=appendText($("agent-cards"),secondary?"details":"section","",section.title==="效果评估"?"goal-card agent-assessment":"result-section agent-report-section"+(secondary?" agent-supporting":""));
    appendText(card,secondary?"summary":"h3",section.title);
    if(!content){appendText(card,"p","本次回答未单独提供此部分。","hint");continue;}
    const readable=content.replace(/([^\n])(?=(?:实际查询词|检索词|来源|已核验全文|未核验全文|其余检索结果|检索限制说明)[：:])/g,"$1\n\n");
    let list=null;
    for(const line of readable.split("\n")){
      if(!line.trim()||/^\s*---+\s*$/.test(line))continue;
      const clean=line.replace(/^\s*#{1,6}\s+/,"").replace(/\*\*(.*?)\*\*/g,"$1");
      const isLabel=/^\s*\*\*.+?\*\*[:：]?\s*$/.test(line)||/^\s*#{1,6}\s+/.test(line);
      if(/^\s*[-*•]\s+/.test(clean)){
        if(!list)list=appendText(card,"ul","");
        appendText(list,"li",clean.replace(/^\s*[-*•]\s+/,""));
      }else{
        list=null;
        const node=appendText(card,isLabel?"h4":"p",clean);
        if(/^(?:实际查询词|检索词|来源|已核验全文|未核验全文|其余检索结果)[：:]/.test(clean))node.className="agent-source-fact";
      }
    }
  }
}
let agentPollTimer=null;
const agentStatusChecks=new Map();
function scheduleAgentStatus(job){
  if(agentPollTimer!==null){clearTimeout(agentPollTimer);agentPollTimer=null;}
  let remote=false,delay=2000;
  if(!job.working){
    if(job.state!=="running"||!job.run_id)return;
    const count=agentStatusChecks.get(job.id)||0;
    if(count>=8){message("自动状态查询已达上限。任务未被重跑，请稍后点击查看任务状态。");return;}
    remote=true;delay=10000;
  }
  const id=job.id;
  agentPollTimer=setTimeout(()=>{
    agentPollTimer=null;
    if(!agentJob||agentJob.id!==id)return;
    if(remote)agentStatusChecks.set(id,(agentStatusChecks.get(id)||0)+1);
    refreshAgent(remote).catch(error=>message(error.message));
  },delay);
}
function scopeNote(job){
  const scope=job.record_scope;
  if(!scope)return "";
  if(scope.in_scope)return `判定范围：本次属于 ${ENGINE_SCOPE_LABEL} 档案，固定库共 44 条记录。`;
  return `判定范围：${scope.reason||"本次反应不在固定判定引擎范围内。"}`;
}
const GOAL_REASON_LABELS={goal_not_set:"用户未设目标",outcome_missing:"实测数值缺失",assay_unknown:"实测或目标口径未知",assay_mismatch:"实测与目标口径不同"};
function goalNote(job){
  // report_contract already phrases the verified summary as "按用户所报数据，…",
  // so the prefix is not added twice.
  const summary=(job.report_review||{}).goal_summary;
  if(summary)return summary;
  const preview=job.input_goal_preview;
  if(preview?.goal_comparison){
    const state=preview.goal_comparison.state,reason=preview.goal_comparison.reason;
    if(state==="unavailable")return "按用户所报数据：暂不能比较用户目标"+(reason&&GOAL_REASON_LABELS[reason]?"（"+GOAL_REASON_LABELS[reason]+"）":"");
    return "按用户所报数据："+(goals[state]||"暂不能比较用户目标");
  }
  return "";
}
function evidenceNote(job){
  const evidence=(job.report_review||{}).product_evidence||(job.input_goal_preview||{}).product_evidence;
  if(!evidence)return "";
  const label=productLabels[evidence.state]||evidence.label||evidence.state;
  // Only the mechanical-check detail is appended; repeating "未附数据/需人工复核"
  // next to a label that already says it was the redundant part.
  const detail=/^structured_/.test(evidence.state)&&(evidence.reasons||[])[0]?"（"+evidence.reasons[0]+"）":"";
  return "产物证据："+label+detail;
}
const WARNING_LABELS={known_scale_reported_missing:"报告把已提供的投料规模列为缺失",original_values_change_advice:"报告建议改写原始数值来消除差异",unsupported_integral_cause:"报告对积分差异给出了无依据的具体原因",product_evidence_check_conflict:"报告与程序发现的表征数值差异矛盾",empty_class_claim:"把“全库某口径共 N 条”写成了“同口径下没有记录”",invented_derived_classification:"抽取时补写了用户未声明的受控分类（如催化体系档位）",missing_explicit_yield_basis:"抽取时漏了用户明确的计算基准",observed_value_changed_or_missing:"抽取的实测值与用户明确数值不一致",mapping_omission:"抽取输入与用户数值或基准存在冲突",goal_claim_conflict:"报告的目标结论与按你所报数据算出的结果相反",goal_claim_without_comparable_caliber:"实测与目标口径不同或未知，报告却对是否达标下了结论",goal_claim_without_goal:"用户未设目标，报告却声称达到目标",product_claim_overreach:"报告把用户自述的结构证据写成了“已确证 / 结构已确认”",product_data_conflict_ignored:"用户所报数据自相矛盾，报告却称数据一致"};
function formatFindingsNote(job){
  const review=job.report_review||{};
  const tokens=new Set();
  for(const item of review.format_findings||[])for(const token of item.tokens||[])tokens.add(token.token);
  const parts=[];
  if(tokens.size)parts.push(`本报告含未翻译的内部字段名或状态词（${[...tokens].slice(0,6).join("、")}），已按原文展示；这些是程序字段，不是化学结论。`);
  const codes=[...new Set((review.consistency_warnings||[]).map(item=>item.code))];
  if(codes.length)parts.push("有待核查项："+codes.map(code=>WARNING_LABELS[code]||code).join("；")+"。");
  return parts.join(" ");
}
function analysisDetail(status){
  if(!status||status.state!=="incomplete")return "";
  if(status.reason==="agent_reported_failure")return "（Agent 报告本次分析未完成）";
  const parts=[];
  if(status.script)parts.push(status.script);
  if(status.exit_code!==null&&status.exit_code!==undefined)parts.push("退出码 "+status.exit_code);
  else parts.push("命令未正常结束");
  return `（失败环节：${parts.join(" · ")}）`;
}
function showAgent(job){
  agentJob=job;
  const labels={queued:"等待连接",running:"运行中",completed:"报告已返回",stopped:"已停止",failed:"失败",asked:"等待补充",rejected:"请求被拒绝",needs_check:"需核查原任务",initiation_uncertain:"正在创建任务；中断时请先核查平台"};
  const analysis=job.analysis_status||{};
  const working=Boolean(job.working);
  const detail=analysisDetail(analysis);
  let status;
  if(working&&analysis.state==="incomplete")status="运行中（有一次准备或执行失败，等待重试结果）";
  else if(working)status="运行中";
  else if(analysis.state==="incomplete")status="本次分析未完成";
  else status=labels[job.state]||job.state;
  let tail="";
  if(!working&&analysis.state==="incomplete"&&!job.answer)tail=" 可点“查看任务状态”或“读取原任务报告”；不要重复创建任务。";
  const line=[`${status}${detail?" "+detail:""}`,job.message||"",tail.trim(),
    agentVersion!==revision?"输入已修改，这是上次提交的结果。":""].filter(Boolean).join(" ");
  $("agent-status").textContent=line;
  $("agent-task-meta").textContent=job.run_id?"Run ID: "+job.run_id:"尚未创建远端任务。";
  $("agent-scope").textContent=scopeNote(job);
  $("agent-evidence").textContent=evidenceNote(job);
  $("agent-goal").textContent=goalNote(job);
  renderAgentAnswer(job.answer);
  const formatNote=formatFindingsNote(job);
  if(formatNote)$("agent-display-note").textContent=$("agent-display-note").textContent?$("agent-display-note").textContent+" "+formatNote:formatNote;
  const preview=job.input_goal_preview;
  if(!job.answer&&preview?.kind==="local_input_rules_not_agent_report"){
    const card=appendText($("agent-cards"),"section","","goal-card agent-assessment");
    appendText(card,"h3","本地目标预览（非Agent报告）");
    const comparison=preview.goal_comparison||{};
    appendText(card,"p",goals[comparison.state]||"暂不能比较用户目标");
    appendText(card,"p",`实测：${preview.observed_value??"未知"}%；目标：${preview.target_value??"未设定"}%。`);
    appendText(card,"p","仅根据本次表单计算；不代表文献已检索、执行证书已核验或产物已确认。Agent报告仍需等待。","hint");
  }
  $("agent-refresh").disabled=false;$("agent-download").disabled=false;
  $("agent-recover").disabled=!job.run_id||!job.thread_id||job.working;
  $("agent-start").disabled=job.working||["running","needs_check","initiation_uncertain"].includes(job.state);
  scheduleAgentStatus(job);
}
async function refreshAgent(check=false){
  if(!agentJob)return;
  const id=agentJob.id;
  const result=await api("/api/agent/reviews/"+id+(check?"?check=1":""));
  if(agentJob?.id===id)showAgent(result);
}
$("agent-refresh").addEventListener("click",()=>refreshAgent(true).catch(error=>message(error.message)));
$("agent-recover").addEventListener("click",async()=>{
  if(!agentJob)return;$("agent-recover").disabled=true;
  try{showAgent(await api("/api/agent/recover",{id:agentJob.id,run_id:agentJob.run_id,thread_id:agentJob.thread_id}));}
  catch(error){message(error.message);$("agent-recover").disabled=false;}
});
$("agent-start").addEventListener("click",async()=>{
  if(!agentRequest&&$("agent-input-mode").value==="form"&&!form.reportValidity())return;
  $("agent-start").disabled=true;
  try{
    if(!agentRequest){const input=readAgentInput();agentRequest=crypto.randomUUID();agentInput=input;agentVersion=revision;}
    $("agent-status").textContent="正在提交，请勿重复创建任务…";
    showAgent(await api("/api/agent/reviews",{...agentInput,request_id:agentRequest}));
    agentRequest=null;
  }catch(error){$("agent-status").textContent="提交未确认："+error.message+"。再次点击会核查同一请求，不重复启动。";$("agent-start").disabled=false;}
});
function readAgentInput(){
  if($("agent-input-mode").value==="form")return {experiment:readExperiment()};
  const text=$("agent-description").value.trim();
  if(!text)throw new Error("请先填写实验描述与研究需求。");
  return {request_text:text};
}
$("agent-input-mode").value="form";
$("agent-input-mode").addEventListener("change",()=>{
  const structured=$("agent-input-mode").value==="form";
  $("agent-form-input").hidden=!structured;$("agent-text-input").hidden=structured;
  markDirty();
});
$("agent-download").addEventListener("click",()=>{
  if(!agentJob)return;
  const blob=new Blob([JSON.stringify({input:agentInput,agent:agentJob},null,2)],{type:"application/json;charset=utf-8"});
  const url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download="chemcritic-agent-review.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$("agent-import").addEventListener("change",async()=>{
  const file=$("agent-import").files[0];if(!file)return;
  try{
    if(file.size>2*1024*1024)throw new Error("结果文件不能超过2MB。");
    const data=JSON.parse((await file.text()).replace(/^\uFEFF/,""));
    if(typeof data.agent?.answer!=="string")throw new Error("请选择之前导出的Agent结果JSON。");
    if(agentJob?.working||["queued","running","needs_check","initiation_uncertain"].includes(agentJob?.state))throw new Error("当前任务仍在运行或状态未确认，请先核查原任务，再打开文件。");
    const restored=data.input||(data.experiment?{experiment:data.experiment}:null);
    // Validate the shape before touching the current form or selected report.
    if(restored?.experiment){
      const e=restored.experiment;
      const reactants=e?.reaction?.reactants;
      if(!e||!e.conditions||!e.results||!Array.isArray(reactants)||!reactants.length||!reactants.every(v=>v&&typeof v.name==="string")||typeof (e.reaction.product||{}).name!=="string"||
        (e.results.characterization!=null&&(!Array.isArray(e.results.characterization)||!e.results.characterization.every(v=>v&&typeof v==="object"))))throw new Error("结果文件中的实验输入结构不完整，未更改当前记录。");
      fill(e,"");
      $("agent-input-mode").value="form";$("agent-form-input").hidden=false;$("agent-text-input").hidden=true;
    }else if(typeof restored?.request_text==="string"){
      $("agent-description").value=restored.request_text;
      $("agent-input-mode").value="text";$("agent-form-input").hidden=true;$("agent-text-input").hidden=false;
      markDirty();
    }else if(restored)throw new Error("结果文件中的原始输入无效，未更改当前记录。");
    agentJob=data.agent;agentInput=restored;agentRequest=null;agentVersion=revision;
    $("agent-scope").textContent=scopeNote(agentJob);
    renderAgentAnswer(agentJob.answer);
    $("agent-evidence").textContent=evidenceNote(agentJob);
    $("agent-goal").textContent=goalNote(agentJob);
    const formatNote=formatFindingsNote(agentJob);
    if(formatNote)$("agent-display-note").textContent=$("agent-display-note").textContent?$("agent-display-note").textContent+" "+formatNote:formatNote;
    $("agent-status").textContent=(agentJob.analysis_status?.state==="incomplete"?"本次分析未完成 · ":"")+(restored?"已打开本地导出结果，未重新调用Agent。":"已打开报告，但文件没有原始输入，左侧表单未恢复；未调用Agent。");
    $("agent-refresh").disabled=true;$("agent-download").disabled=false;
    $("agent-recover").disabled=!agentJob.run_id||!agentJob.thread_id;
  }catch(error){message(error.message);}
});
$("agent-description").addEventListener("input",()=>{revision++;if(agentJob)$("agent-status").textContent="描述已修改，下方仍为上次提交的结果。";});
$("agent-example").addEventListener("click",()=>{$("agent-description").value="模拟案例，非真实湿实验：4-溴苯甲醚与苯硼酸反应，目标产物4-甲氧基联苯。催化剂Pd(PPh3)4，THF，60°C，12小时，分离收率42%，目标至少60%分离收率。用户自述1H NMR匹配，未上传谱图。碱、催化剂载量、规模、气氛和重复次数未知。请按团队规则判定并提出下一轮方案。";revision++;if(agentJob)$("agent-status").textContent="已载入新描述，下方仍为上次提交结果。";});
async function initAgentConfig(){
  try{const config=await api("/api/agent/config");$("agent-config").textContent=config.enabled?`${config.name} · ${config.agent_id} · 固定库 ${config.record_count} 条 · 判定范围 ${ENGINE_SCOPE_LABEL}`:"尚未启用。请在终端使用 --sciencepal 启动服务。";$("agent-start").disabled=!config.enabled;}catch(error){$("agent-config").textContent="连接配置读取失败："+error.message;}
}
(async()=>{
  try{bootstrap=await api("/api/bootstrap");fill(bootstrap.experiment,bootstrap.sciencepal_text);}
  catch(error){message("初始化失败："+error.message);addReactantRow({role:"aryl_halide"});syncGoal();syncScope();}
  await loadHistory().catch(()=>{});
  await initAgentConfig();
})();
