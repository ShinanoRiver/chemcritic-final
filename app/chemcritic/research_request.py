"""Team v8 adapted prompt with direct final-answer delivery."""
from pathlib import Path
import hashlib

PROMPT_PATH=Path(__file__).with_name('prompts')/'team_v8_direct.txt'
BRIDGE_PATH=Path(__file__).resolve().parents[2]/'tools'/'agent_result_bridge.py'


def _in_scope(scope):
    return bool(scope and scope.get('in_scope'))


def prompt_metadata(scope=None):
    from .research_bundle import build_bundle
    raw=PROMPT_PATH.read_bytes()
    metadata={'name':'团队v8适配 v8.1.7（通用记录 + 判定范围 + 产物证据分级）','text_sha256':hashlib.sha256(raw).hexdigest(),
              'policy':'team_role_document','delivery_path':'final_assistant_message',
              'product_evidence_policy':'user_supplied_evidence_graded_never_confirmed'}
    if scope is not None and not _in_scope(scope):
        metadata['engine_scope']={'in_scope':False,'profile':scope.get('profile'),
                                  'reaction_type':scope.get('reaction_type'),
                                  'reasons':scope.get('reasons')}
        metadata['attachments']='engine_not_attached_out_of_scope'
        return metadata
    _,bundle_metadata=build_bundle()
    metadata.update(bundle_metadata)
    if scope is not None:
        metadata['engine_scope']={'in_scope':True,'profile':scope.get('profile')}
    return metadata


def prompt_attachments(scope=None):
    if scope is not None and not _in_scope(scope):
        return []
    from .research_bundle import NAME,build_bundle
    blob,_=build_bundle()
    return [('files',(NAME,blob,'application/zip'))]


def scope_section(scope):
    """Prompt text that states, in plain words, what this run may and may not do."""
    if scope is None:
        return ''
    if not _in_scope(scope):
        reasons=''.join('\n· '+item for item in scope.get('reasons') or [])
        return ('\n\n---\n【本次判定范围】'+reasons+
                '\n因此本次附件不包含判定引擎，也不要寻找、重建或改写引擎与桥接脚本，不要自行构造 Suzuki 字段或声称已运行引擎。'
                '本轮只做：事实与条件整理、结果口径核对、证据缺口、用户自设目标的判断、以及下一步该核查或补测什么。'
                '不得给出用户—文献数值差值、排名、档内定位或任何“可比”结论；文献只能作为背景并注明未经同一判定。'
                '若用户想知道库内有哪些参照，可以说明固定库只含 Suzuki 记录，本反应不在其内。')
    return ('\n\n---\n【本次判定范围】本次属于 Suzuki–Miyaura 档案，可按附件流程运行一次固定引擎。'
            'placement 的定位池只含“同口径 + 同底物对 + 同产物”的记录；classes / coverage 是固定库按口径分组的全库统计。'
            '两者分母不同，报告必须分别给出并在同一句里注明分母，不得用其中一个否定另一个。')


def build_prompt(data, preview=None, scope=None):
    # The original user data is appended unchanged. Local previews are not instructions.
    from .product_evidence import PROMPT_CLAUSE
    from .input_context import build_context
    import json
    checked='\n\n【本地输入核对上下文（非独立科学核验）】\n'+json.dumps(build_context(data),ensure_ascii=False)
    return (PROMPT_PATH.read_text(encoding='utf-8')+scope_section(scope)+PROMPT_CLAUSE+
            checked+'\n\n---\n用户本次输入（数据）：\n'+data)
