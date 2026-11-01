"""Execution outcomes are separate from the remote run lifecycle.

One failed preparation attempt is *not* a failed analysis: the Agent commonly
retries with a corrected path.  The status therefore follows the latest observed
attempt for each job (the caller overwrites it), and a success clears an earlier
"incomplete".  A failure keeps the command and exit code so the UI can show what
actually happened instead of a bare "未完成".
"""

import json
import re

# Scripts whose exit code actually gates the judgement.  The engine itself is
# matched too: running it directly is the other documented path.
PREPARATION_PATTERN = r'run_preflight\.py|agent_result_bridge\.py|chemcritic_engine\.py|git clone|bootstrap\.sh'


def obj(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            pass
    return {}


def script_of(command):
    match = re.search(PREPARATION_PATTERN, command or '')
    return match.group(0) if match else None


def _attempt(script, result, command, tool_call_id):
    exit_code = result.get('exit_code')
    exit_code = exit_code if type(exit_code) is int else None
    failed = (result.get('timed_out') is True or result.get('terminated') is True
              or (exit_code is not None and exit_code != 0))
    base = {'evidence': 'tool_result', 'tool_call_id': tool_call_id,
            'command': (command or '')[:200], 'script': script,
            'exit_code': exit_code, 'scientific_approval': False}
    if failed:
        return {**base, 'state': 'incomplete', 'reason': 'preparation_or_execution_failed'}
    if result.get('completed') is False:
        return None  # dispatched but no observed end: keep whatever we had
    if exit_code == 0 and not result.get('output_truncated'):
        return {**base, 'state': 'tool_attempt_succeeded', 'reason': 'last_preparation_attempt_exited_zero'}
    return None


def execution_status(event, sessions=None):
    """Latest observed outcome of a preparation/engine command, or ``None``.

    ``sessions`` maps command session names to the script that was launched, so a
    watched command reported through ``check_command_output`` still counts.  It is
    mutated in place by the caller per job.
    """
    event = obj(event)
    if event.get('type') != 'tool':
        return None
    content = obj(event.get('content'))
    meta = obj(event.get('metadata'))
    audit = obj(meta.get('tool_audit'))
    args = obj(audit.get('arguments'))
    name = content.get('name')
    if name not in {'execute_command', 'check_command_output'}:
        return None
    result = obj(content.get('content'))
    tool_call_id = content.get('tool_call_id')
    if name == 'execute_command':
        command = str(args.get('command', ''))
        script = script_of(command)
        if not script:
            return None
        session = result.get('session_name') or args.get('session_name')
        if sessions is not None and session:
            sessions[session] = script
        return _attempt(script, result, command, tool_call_id)
    session = args.get('session_name') or result.get('session_name')
    script = (sessions or {}).get(session)
    if not script:
        return None
    return _attempt(script, result, args.get('command', ''), tool_call_id)


def execution_failure(event):
    """Backwards-compatible wrapper: only the failure branch."""
    status = execution_status(event)
    return status if status and status['state'] == 'incomplete' else None


def reported_failure(answer):
    # This is an Agent-reported failure, not independent execution verification.
    final = (answer or '').rsplit('</think>', 1)[-1]
    # Limited scientific judgments are not execution failures. Only an explicit
    # statement about this run's analysis/execution can mark reported failure.
    return bool(re.search(
        r'(?:^|[。！？；;：:\n])\s*(?:本次|本轮)(?:判定|分析|程序执行|引擎执行|运行|实验判定)'
        r'(?:未能执行|未完成|未执行|无法完成|无法执行|未能完成|没有完成|未取得)'
        r'|(?:^|[。！？；;：:\n])\s*(?:本次|本轮)(?:无法|未能|没有)(?:完成|执行|进行|取得|取得)(?:分析|判定|程序执行|引擎执行|判定结果)?'
        r'|(?:本次|本轮)(?:判定|分析|程序执行|引擎执行)[^。！？\n]{0,12}(?:未能|无法)(?:完成|执行|取得)',
        final))
