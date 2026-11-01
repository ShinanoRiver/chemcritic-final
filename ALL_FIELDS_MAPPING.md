# 表单全字段映射检查（2026-10-31）

对象：工作区中的同伴v0.2修正版，桌面原版与云端均未修改。无新增Agent调用。

## 覆盖范围

实际执行网页中的readRows/readExperiment/fill函数，覆盖34个静态具名控件、8个动态行字段，检查JSON生成与回填往返。此项使用表单控件测试桩，不等于真实浏览器视觉或文件选择器验收。
后端测试覆盖规范化、原始提交数据、提示词尾部数据保留、SQLite保存读取、全部反应类型/角色/添加剂类型/结果口径，以及映射冲突拒绝。字段进入Agent请求不等于Agent必然准确解释，远端仍待复测。

|界面部分|提交字段|固定引擎处理|
|---|---|---|
|编号、模拟属性|experiment_id、simulated|保留编号及声明，不升级真实性|
|反应类型、自定义名称|reaction.type、type_label|Suzuki且角色唯一时判定；其他类型保留事实、禁用固定判定|
|每条原料名称、角色|reaction.reactants[].name/role|按明确角色映射底物，不依名称推断；同角色多条停止固定判定|
|每条原料当量、限量标记|reactants[].equivalents/limiting、equivalents_basis|保留明确数值；多个限量标记拒绝；非芳基卤化物基准不自动换算|
|目标产物|reaction.product.name|映射substrate.product；不独立确认结构|
|催化剂、载量、基准|catalyst.name/loading_mol_pct/loading_basis|映射催化剂字段，计算基准保留|
|另加配体、载量|catalyst.ligand.name/loading_mol_pct|名称映射；载量保留在原记录/Agent上下文，不编造引擎门槛|
|添加剂名称、类型|additives[].name/type|唯一碱/配体映射；其他类型保留上下文；多碱/多配体或冲突停判|
|添加剂当量、mol%|additives[].equivalents/loading_mol_pct|碱当量有直接字段；mol%不直接改写成当量；原始值均保留|
|添加剂完整声明|additives_listed_complete|勾选才可将未列出的类别标为未加入；不勾选保持未知|
|主/共溶剂、比例|conditions.solvent_system|保留组合与比例；只填共溶剂也不丢失名称|
|体积、含水声明|solvent_system.volume_ml/water_content|保留给Agent；不自动推导浓度或实测水量|
|温度、时间、气氛、规模|conditions.temperature_C/time_h/atmosphere/scale_mmol|映射对应引擎字段；零值与空值分开|
|压力、光照、加料|conditions.pressure_bar/irradiation/addition_mode|保留给Agent；当前引擎无直接门槛，不能虚构判定|
|结果数值、口径|results.value_pct/metric|保持0与未知区别；LC不伪装成GC，当前停用固定判定|
|计算基准、定量方法、内标|results.basis/method/internal_standard|映射assay.quantification_basis/method/internal_standard；不补造校准|
|结构证据、表征方法|results.characterization[].method/supports_target/provenance/observation_text/proton_integral/mz/mz_adduct/formula/spectrum_reference|按行登记；本地只用分子式核对积分与单同位素质量，不是独立谱图核验；分级见 product_evidence.py|
|重复次数|results.repeat_attempts|保留原始正整数；空值不表示未重复；不自动证明稳定性|
|目标开关、数值、口径|user_goal|未勾选为null；目标与结果不同口径不换算|

## 本次修复

1. 已有GC-FID与内标字段保留；原始当量来源路径错误时仅做无冲突别名规范化，原文件保留。
2. 多个限量试剂声明不再静默取第一项。
3. 同角色多原料、多碱、多配体及冲突配体不会被静默压缩成单字段。
4. 配体若登记在添加剂栏，唯一且无冲突时接入引擎名称字段。
5. 仅填共溶剂时保留已知名称。6. 非芳基卤化物当量基准、LC口径保持原记录，不自动改写成引擎支持的数据。
7. 旧v0.1记录中的明确方法/内标也保留。
8. 提示词明确所有已填字段要从原始记录读取，不能因引擎摘要无字段就反问或声称未提供。
9. 结构证据改为按行登记（动态行字段由 8 个增加到 22 个）：每行可填方法、结论、观测值原话、积分总数、实测 m/z、分子式与附件编号；
   人工复核来源、复核记录号与加合物仍随记录保留，但不再要求用户重复填写。
10. 新增本地算术核对与分级（`product_evidence.py`）：只判断用户所报数值是否自洽，不做谱图解析，也不签发结构确证。

## 限制

未执行真实Agent调用；未修改化学引擎、固定文献或数值发布权限；未合并到Render。不能承诺任意填写都会得到科学结论，支持范围外应如实返回限制。
