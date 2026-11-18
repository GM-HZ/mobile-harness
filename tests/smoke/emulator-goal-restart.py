"""Run three actual goal rounds with revision changes and Host restarts between them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import time
import uuid

flow=runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support=flow['support']


def goal_ref(view):
    return {key:view[key] for key in ('id','revision')}


def objective(workspace, stage):
    source='seed.txt' if stage==1 else f'checkpoint-{stage-1}.txt'
    dest=f'checkpoint-{stage}.txt'
    finish=(
        'After the copy succeeds, use get_goal to get the current id and revision, then update_goal with action complete. '
        'Do not invoke other tools. '
        if stage==3 else (
            'The overall goal remains incomplete until checkpoint-3.txt exists. '
            'Later checkpoints require new instructions from the acceptance driver. '
            'Creating this checkpoint does not complete the goal. Leave it active for the round driver to stop. '
            'Do not call get_goal or update_goal in this round. End the turn immediately after the write.'
        )
    )
    return (
        f'In this isolated acceptance workspace {workspace}, this automatic round is stage {stage} of 3. '
        f'Use read on {workspace}/{source}, then use write on {workspace}/{dest} with exactly the original text. '
        'Preserve all bytes, including the absence of a final newline. Work only with those two paths. '
        + finish
    )


def settled(device,session,index,phase,goal_id,evidence):
    until=time.monotonic()+110
    while time.monotonic()<until:
        status=device.rpc('goals/get',{'agentId':session})
        rows=support['events'](device,session)
        messages=[r for r in rows if r['type']=='user/message'
                  and r['data']['source'].get('goalId')==goal_id]
        evidence['lastObservedGoal']={key:status.get(key) for key in
                                      ('phase','activation','roundsStarted','blockedReason')}
        if status['phase'] in ('blocked','complete','paused') and len(messages)==index:
            start=[r for r in rows if r['seq']<messages[-1]['seq'] and r['type']=='turn/start'][-1]
            turn=start['data']['turn']
            ending=[r for r in rows if r['type']=='turn/end' and r['data']['turn']==turn]
            if ending:
                assert status['phase']==phase,evidence['lastObservedGoal']
                assert ending[0]['data']['reason']['kind']=='completed',ending
                return status,rows,turn
        time.sleep(.25)
    raise AssertionError(f'Stage {index} did not settle at {phase}')


def work_history(rows):
    kinds={'user/message','assistant/message','turn/start','turn/end','tool/call','tool/result'}
    return [row for row in rows if row['type'] in kinds]


def run(device,output):
    name='mh-goal-restart-'+uuid.uuid4().hex[:10]
    folder='alpine/workspace-native/'+name
    path=support['WORKSPACE']+'/'+name
    marker='OWNED_GOAL_'+uuid.uuid4().hex.upper()
    device.app(f'mkdir {folder} && printf %s {marker} > {folder}/seed.txt')
    bridge=('tcp:19643','tcp:19592')
    app_workspace=None
    session=None
    evidence={'stages':[]}
    assert 'Forwardport result:OK' in device.hdc('fport',*bridge)
    try:
        device.ready('normal')
        app_workspace=device.rpc('workspace/create',{'request':{'path':path}})['workspace']['workspaceId']
        with support['model_key'](device):
            try:
                session=device.rpc('session/create',{'request':{'workspaceId':app_workspace}})['sessionId']
                evidence['sessionId']=session
                device.rpc('session/selectModel',{'request':{'sessionId':session,'provider':'deepseek-official',
                           'model':'deepseek-flash','reasoningEffort':'off'}})
                args={'objective':objective(path,1),'max_goal_rounds':1}
                calls,_,_=flow['prompt'](device,session,
                    'I explicitly authorize this isolated acceptance goal. First call create_goal exactly once '
                    'with '+json.dumps(args)+'. Do no file work in this initial turn. Stop after creating the '
                    'goal so its automatic continuation takes the first stage.',timeout=55)
                assert [row['name'] for row in calls]==['create_goal'],calls
                assert json.loads(calls[0]['arguments'])==args
                goal_id=device.rpc('goals/get',{'agentId':session})['id']
                for index in range(1,4):
                    phase='complete' if index==3 else 'blocked'
                    status,rows,turn=settled(device,session,index,phase,goal_id,evidence)
                    assert status['roundsStarted']==index and status['activation']=='disarmed',status
                    used=[r['data'] for r in rows if r['type']=='tool/call' and r['data']['turn']==turn]
                    call_ids={row['callId'] for row in used}
                    results=[r['data']['message'] for r in rows if r['type']=='tool/result'
                             and r['data']['message'].get('toolCallId') in call_ids]
                    assert len(used)==len(results) and not any(row['isError'] for row in results),results
                    expected_tools=['read','write']
                    if index==3:
                        expected_tools+=['get_goal','update_goal']
                    required=[row for row in used if row['name']!='grep']
                    assert [row['name'] for row in required]==expected_tools,used
                    source='seed.txt' if index==1 else f'checkpoint-{index-1}.txt'
                    source_path=f'{path}/{source}'
                    dest_path=f'{path}/checkpoint-{index}.txt'
                    assert json.loads(required[0]['arguments'])=={'file_path':source_path}
                    assert json.loads(required[1]['arguments'])=={'file_path':dest_path,'content':marker}
                    for row in used:
                        if row['name']=='grep':
                            assert json.loads(row['arguments']).get('path') in (source_path,dest_path),row
                    if index==3:
                        args=json.loads(required[3]['arguments'])
                        assert args['goal_id']==goal_id and args['action']=='complete',args
                    else:
                        assert status['blockedReason']['code']=='round-limit',status
                    data=flow['read_bytes'](device,f'{folder}/checkpoint-{index}.txt')
                    assert data==marker.encode()
                    step={'round':index,'state':goal_ref(status),'phase':phase,'checkpointSha256':hashlib.sha256(data).hexdigest()}
                    step['tools']=[row['name'] for row in used]
                    evidence['stages'].append(step)
                    if index<3:
                        step['blockedReason']=status['blockedReason']['code']
                        device.stop()
                        device.start()
                        step['restartReadyMs']=device.ready('normal')
                        restored=device.rpc('goals/get',{'agentId':session})
                        assert restored==status,(restored,status)
                        restored_rows=support['events'](device,session)
                        before_work=work_history(rows)
                        after_work=work_history(restored_rows)
                        step['restoredWorkEvents']=len(after_work)
                        step['extraRestartEventTypes']=[
                            row['type'] for row in restored_rows if row['seq']>rows[-1]['seq']
                        ]
                        assert set(step['extraRestartEventTypes'])<={'session/end-seed'},step
                        assert after_work==before_work,(
                            [(row['seq'],row['type']) for row in before_work],
                            [(row['seq'],row['type']) for row in after_work],
                        )
                        assert device.app(f'test ! -e {folder}/checkpoint-{index+1}.txt && printf ABSENT')=='ABSENT'
                        try:
                            device.rpc('goals/resume',{'agentId':session,'ref':goal_ref(restored)})
                        except RuntimeError as error:
                            assert str(error) in ('goals/resume: GOAL_INVALID_TRANSITION','goals/resume: gateway/internal'),error
                            step['exhaustedResumeError']=str(error)
                            assert device.rpc('goals/get',{'agentId':session})==restored
                        else:
                            raise AssertionError('An exhausted Goal started another round')
                        edited=device.rpc('goals/edit',{'agentId':session,'ref':goal_ref(restored),
                                         'request':{'objective':objective(path,index+1),'maxGoalRounds':index+1}})
                        assert edited['phase']=='blocked' and edited['revision']==restored['revision']+1,edited
                        try:
                            device.rpc('goals/resume',{'agentId':session,'ref':goal_ref(restored)})
                        except RuntimeError as error:
                            assert str(error) in ('goals/resume: GOAL_STALE_REVISION','goals/resume: gateway/internal'),error
                            step['staleResumeError']=str(error)
                            assert device.rpc('goals/get',{'agentId':session})==edited
                        else:
                            raise AssertionError('The prior Goal revision armed a new round')
                        resumed=device.rpc('goals/resume',{'agentId':session,'ref':goal_ref(edited)})
                        assert resumed['phase']=='active' and resumed['id']==goal_id,resumed
                        step['explicitResumeRevision']=resumed['revision']
                evidence['eachCheckpointMatched']=True
                evidence['sameGoalId']=goal_id
                evidence.pop('lastObservedGoal',None)
            finally:
                if session:
                    current=device.rpc('goals/get',{'agentId':session})
                    if current:
                        device.rpc('goals/clear',{'agentId':session,'ref':goal_ref(current)})
                    device.rpc('workspace/archiveSession',{'request':{'sessionId':session}})
        evidence['testKeyRemoved']=True
    finally:
        try:
            if app_workspace:
                assert device.rpc('workspace/delete',{'request':{'workspaceId':app_workspace}})=={'deleted':True}
            device.app('rm -rf '+folder)
        finally:
            device.hdc('fport','rm',*bridge)
            output.write_text(json.dumps(evidence,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    run(support['Emulator'](args.target,19643),args.output)
