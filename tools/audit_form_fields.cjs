// Execute the real serializer/fill functions with a bounded form-control harness.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('app/chemcritic/static/app.js','utf8');
const html=fs.readFileSync('app/chemcritic/static/index.html','utf8');
const staticNames=[...html.matchAll(/name="([^"]+)"/g)].map(m=>m[1]);
const fields=Object.fromEntries(staticNames.map(m=>[m,{value:'',checked:false}]));
// Controls the page builds at runtime (the classification selects) are stubbed in
// for readExperiment/fill, but they are not part of the static-coverage check.
const classificationFields={catalyst_form:{label:'催化剂物理形态'},ligand_family:{label:'配体族'},support:{label:'载体'},medium:{label:'反应介质'},activation_mode:{label:'活化方式'}};
for(const key of Object.keys(classificationFields))fields['classification_'+key]={value:'',checked:false};
const rows={'reactant-rows':[],'additive-rows':[],'evidence-rows':[]};
const nodes=new Proxy({}, {get:(o,id)=>o[id]??=( {value:'',replaceChildren(){if(rows[id])rows[id]=[];}} )});
const mappings={
 reactant:item=>({'reactant-name':item.name,'reactant-role':item.role,'reactant-eq':item.equivalents,'reactant-limiting':item.limiting}),
 additive:item=>({'additive-name':item.name,'additive-type':item.type,'additive-eq':item.equivalents,'additive-molpct':item.loading_mol_pct}),
 evidence:item=>({'evidence-method':item.method,'evidence-supports':String(item.supports_target),'evidence-text':item.observation_text,'evidence-integral':item.proton_integral,'evidence-mz':item.mz,'evidence-formula':item.formula,'evidence-spectrum':item.spectrum_reference}),
};
function addRow(id,item){
 const mapping=id==='reactant-rows'?mappings.reactant(item):id==='additive-rows'?mappings.additive(item):mappings.evidence(item);
 const controls=Object.fromEntries(Object.entries(mapping).map(([k,v])=>[k,{value:v==null?'':String(v),checked:typeof v==='boolean'?v:false}]));
 const row={querySelector:s=>controls[s.slice(1)]};
 if(id==='evidence-rows')row.dataset={provenance:item.provenance||'user_report',reviewReference:item.review_reference||'',adduct:item.mz_adduct||'',rawSpectrum:item.raw_spectrum_provided?'1':''};
 rows[id].push(row);
}
const ctx=vm.createContext({field:n=>fields[n],$:id=>nodes[id],form:{reset(){for(const f of Object.values(fields)){f.value='';f.checked=false;}}},document:{querySelectorAll:s=>rows[s.slice(1,-3)]||[]},reactionTypes:{suzuki_miyaura:'Suzuki',other:'其他'},classificationFields,addReactantRow:r=>addRow('reactant-rows',r),addAdditiveRow:r=>addRow('additive-rows',r),addEvidenceRow:r=>addRow('evidence-rows',r),syncGoal(){},syncScope(){},markDirty(){}});
vm.runInContext(source.slice(source.indexOf('function readEvidenceRows('),source.indexOf('function payload()')),ctx);
vm.runInContext(source.slice(source.indexOf('function fill(data,sourceText)'),source.indexOf('form.addEventListener("input"')),ctx);
const values={experiment_id:'ALL-FIELDS',simulated:'true',reaction_type:'suzuki_miyaura',reaction_type_label:'自定义备注',product_name:'biphenyl',catalyst:'Pd(PPh3)4',catalyst_loading_mol_pct:'1',catalyst_loading_basis:'相对溴苯',ligand:'TEST-LIGAND',ligand_loading_mol_pct:'2',solvent_primary:'乙醇',solvent_cosolvent:'水',solvent_ratio:'4:1',solvent_volume_ml:'5',water_content:'aqueous',atmosphere:'N2',temperature_C:'-10',time_h:'4',scale_mmol:'1',pressure_bar:'2',irradiation:'TEST-LIGHT',addition_mode:'TEST-ADDITION',value_pct:'37',metric:'gc',basis:'溴苯投料量',results_method:'GC-FID',internal_standard:'TEST-STANDARD',repeat_attempts:'2',minimum_yield_pct:'60',goal_metric:'isolated'};
for(const [n,v] of Object.entries(values))fields[n].value=v;
fields.additives_complete.checked=true;fields.has_goal.checked=true;
addRow('reactant-rows',{name:'bromobenzene',role:'aryl_halide',equivalents:1,limiting:true});
addRow('reactant-rows',{name:'phenylboronic acid',role:'boronic_acid_or_ester',equivalents:1.2,limiting:false});
addRow('additive-rows',{name:'K2CO3',type:'base',equivalents:2,loading_mol_pct:null});
addRow('additive-rows',{name:'TEST-SALT',type:'salt',equivalents:0.1,loading_mol_pct:10});
addRow('evidence-rows',{method:'1H NMR',supports_target:true,observation_text:'δ 7.58 (d, J=8.8 Hz, 2H), 7.47 (d, 2H)',proton_integral:12,mz:185.0961,formula:'C13H12O',spectrum_reference:'NMR-TEST-001'});
const full=JSON.parse(JSON.stringify(ctx.readExperiment()));
ctx.fill(full,'');assert.deepEqual(JSON.parse(JSON.stringify(ctx.readExperiment())),full);
fs.writeFileSync('tests/all_fields_fixture.json',JSON.stringify(full,null,2));
// Provenance and review reference are not re-asked in the form; they must survive fill/read.
const reviewed=JSON.parse(JSON.stringify(full));
reviewed.results.characterization=[{method:'1H NMR',supports_target:true,provenance:'human_review',review_reference:'QC-2026-001',raw_spectrum_provided:true,mz_adduct:'[M+Na]+'}];
ctx.fill(reviewed,'');
assert.deepEqual(JSON.parse(JSON.stringify(ctx.readExperiment())).results.characterization,reviewed.results.characterization);
fields.has_goal.checked=false;rows['evidence-rows']=[];fields.value_pct.value='0';fields.temperature_C.value='0';fields.pressure_bar.value='0';
const zero=ctx.readExperiment();assert.equal(zero.user_goal,null);assert.deepEqual(Array.from(zero.results.characterization),[]);assert.equal(zero.results.value_pct,0);assert.equal(zero.conditions.temperature_C,0);assert.equal(zero.conditions.pressure_bar,0);
fields.results_method.value='';fields.internal_standard.value='';assert.equal(ctx.readExperiment().results.method,null);assert.equal(ctx.readExperiment().results.internal_standard,null);
rows['reactant-rows'][1].querySelector('.reactant-limiting').checked=true;assert.throws(()=>ctx.readExperiment(),/一个限量试剂/);
const covered=new Set([...Object.keys(values),'additives_complete','has_goal']);
const visible=staticNames.filter(n=>n!=='viewport');assert.deepEqual(visible.filter(n=>!covered.has(n)),[]);
console.log(JSON.stringify({status:'passed',static_controls:visible.length,dynamic_row_fields:22,roundtrip:true,checks:10,agent_calls:0}));
