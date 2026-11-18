"""Exercise current-session Auto review and the LiveShare owner surface on Phone."""
import argparse
import json
import queue
from pathlib import Path
import runpy
import time
import uuid

flow = runpy.run_path(str(Path(__file__).with_name('emulator-personalized-recommendations.py')))
support, agent, lsp = (flow[name] for name in ('support', 'agent', 'lsp'))
PROFILE = flow['PROFILE']
AUTO = '@deepseek-ai/dsh-experimental-auto-review'
SHARE = '@deepseek-ai/dsh-experimental-liveshare'


def permission_catalog(emulator, enabled):
    catalog = emulator.rpc('permissionPresets/catalog', {})
    assert ('auto' in {option['value'] for option in catalog['options']}) == enabled, catalog
    assert 'auto' not in {option['value'] for option in catalog['defaultOptions']}, catalog
    assert catalog['defaultPreset'] == 'workspace-write', catalog
    return catalog


def permission(emulator, sid, name):
    return emulator.rpc('commands/execute', {
        'agentId': sid, 'line': '/permission '+name, 'submittedAttachments': [],
    })


def denied_write(emulator, sid, relative, outcome):
    filename = 'cancelled.txt' if outcome == 'cancel' else 'rejected.txt'
    arguments = {'file_path':filename,'content':'FORBIDDEN_FIXTURE_WRITE'}
    previous = support['events'](emulator,sid)
    start = max((event['seq'] for event in previous),default=0)
    with flow['flow']['approval']['approval_events'](emulator) as (client, frames):
        emulator.rpc('session/prompt',{'request':{
            'sessionId':sid,'requestId':str(uuid.uuid4()),'mode':'queue',
            'content':[{'type':'text','text':'Call write exactly once with '+json.dumps(arguments)
                        +'. Do not retry or use any other tool.'}],
        }})
        deadline = time.monotonic()+80
        reviewed = None
        while time.monotonic()<deadline:
            try:
                frame = frames.get(timeout=.15)
            except queue.Empty:
                frame = None
            if isinstance(frame,BaseException):
                raise frame
            if frame and frame['type']=='waterfall':
                answer = {'kind':'next'}
                if frame['event']=='approval/request' and frame['agentId']==sid:
                    assert reviewed is None and frame['request']['toolName']=='write',frame
                    assert emulator.app(f'test ! -e {relative}/{filename} && printf ABSENT')=='ABSENT'
                    reviewed = frame['request']['callId']
                    if outcome=='cancel':
                        assert emulator.rpc('session/cancel',{'request':{'sessionId':sid}})['accepted']
                        answer = None
                    else:
                        answer = {'kind':'result','value':outcome}
                if answer is not None:
                    emulator.rpc('$events/result',{'clientId':client,'eventId':frame['eventId'],'outcome':answer})
            events = [event for event in support['events'](emulator,sid) if event['seq']>start]
            if any(event['type']=='turn/end' for event in events):
                asked = [event['data'] for event in events if event['type']=='approval/asked']
                assert reviewed and any(row['callId']==reviewed and 'Owned fixture requires confirmation.' in row['reason']
                                        for row in asked),asked
                assert emulator.app(f'test ! -e {relative}/{filename} && printf ABSENT')=='ABSENT'
                return True
    raise AssertionError('Auto review approval did not settle: '+outcome)


def run(emulator, output, scripted_review):
    name = 'mh-auto-review-'+uuid.uuid4().hex[:10]
    relative = 'alpine/workspace-native/'+name
    remote = '/data/local/tmp/'+name
    paths = [PROFILE+'/'+file for file in ['package.json','pnpm-lock.yaml','cordis.patch.yml']]
    paths.append('mobile-harness-boot.json')
    originals, evidence, sessions = {}, {}, []
    workspace = None
    patch = 'alpine/native-benchmark-home/cordis.patch.yml'
    fixture_patch = False
    try:
        emulator.ready('normal')
        originals = {file:agent['read_bytes'](emulator,file) for file in paths}
        evidence['defaultCatalog'] = [flow['has_bundle'](emulator,bundle,False) for bundle in [AUTO,SHARE]]
        permission_catalog(emulator,False)
        emulator.app('mkdir '+relative+' && printf MOBILE_HARNESS_AUTO_REVIEW > '+relative+'/fixture.txt')
        if scripted_review:
            assert emulator.app('test ! -e '+patch+' && printf EMPTY')=='EMPTY'
            module = Path(__file__).with_name('fixtures')/'auto-review-response.mjs'
            lsp['restore_bytes'](emulator,relative+'/auto-review-response.mjs',module.read_bytes(),remote+'-module')
            url = 'file://'+support['WORKSPACE']+'/'+name+'/auto-review-response.mjs'
            fixture_patch = True
            lsp['restore_bytes'](emulator,patch,f'- insert:\n    - id: {name}\n      name: "{url}"\n'.encode(),remote+'-patch')
        for bundle in [AUTO,SHARE]:
            flow['flow']['switch'](emulator,bundle,True)
        flow['flow']['restart'](emulator)
        evidence['enabledCatalog'] = [flow['has_bundle'](emulator,bundle,True) for bundle in [AUTO,SHARE]]
        evidence['defaultPolicyUnchanged'] = permission_catalog(emulator,True)['defaultPreset']
        # Only check the authenticated owner surface. No share or Relay address is created.
        relay = emulator.rpc('liveshareShares/relay',{})
        assert not relay.get('effective'), 'Dedicated emulator must have no configured Relay'
        assert emulator.rpc('liveshareShares/list',{}) == {'shares':[]}
        assert emulator.web_status(False) == 401
        evidence['shareOwnerHasNoRelayOrShares'] = True
        registered = emulator.rpc('workspace/create',{'request':{'path':support['WORKSPACE']+'/'+name}})
        assert registered['created'],registered
        workspace = registered['workspace']['workspaceId']
        with support['model_key'](emulator):
            sid = flow['session'](emulator,workspace,'Auto review fixture '+name,sessions)
            evidence['selectedAuto'] = permission(emulator,sid,'auto')
            result,_ = agent['tool'](emulator,sid,'read',{'file_path':'fixture.txt'})
            assert 'MOBILE_HARNESS_AUTO_REVIEW' in str(result),result
            evidence['autoAllowedRead'] = True
            if scripted_review:
                result,_ = agent['tool'](emulator,sid,'write',
                    {'file_path':'malformed.txt','content':'FORBIDDEN_FIXTURE_WRITE'},expect_error=True)
                assert 'AUTO_REVIEW_FAILED' in str(result),result
                assert emulator.app('test ! -e '+relative+'/malformed.txt && printf ABSENT')=='ABSENT'
                evidence['invalidReviewDeniedBeforeWrite'] = True
                evidence['rejectedAfterReviewerDenial'] = denied_write(emulator,sid,relative,'rejected')
                evidence['cancelledAfterReviewerDenial'] = denied_write(emulator,sid,relative,'cancel')
            flow['flow']['restart'](emulator)
            evidence['selectionAfterRestart'] = permission(emulator,sid,'')
            assert 'current preset auto ' in str(evidence['selectionAfterRestart']),evidence['selectionAfterRestart']
            permission(emulator,sid,'workspace-write')
        for bundle in [AUTO,SHARE]:
            flow['flow']['switch'](emulator,bundle,False)
        flow['flow']['restart'](emulator)
        permission_catalog(emulator,False)
        evidence['disabledCatalog'] = [flow['has_bundle'](emulator,bundle,False) for bundle in [AUTO,SHARE]]
    finally:
        try:
            try:
                for sid in sessions:
                    emulator.rpc('workspace/archiveSession',{'request':{'sessionId':sid}})
                if workspace:
                    emulator.rpc('workspace/delete',{'request':{'workspaceId':workspace}})
            finally:
                if originals:
                    emulator.stop()
                    if fixture_patch:
                        emulator.app('rm -f '+patch)
                    emulator.app('rm -rf '+relative)
                    for index,(file,data) in enumerate(originals.items()):
                        lsp['restore_bytes'](emulator,file,data,remote+str(index))
                    emulator.start()
                    evidence['restoredReadyMs'] = emulator.ready('normal')
                    assert all(agent['read_bytes'](emulator,file)==data for file,data in originals.items())
                    evidence['originalConfigurationRestored'] = True
        finally:
            output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    parser.add_argument('--scripted-review', action='store_true', help='Control reviewer decisions for denial and cancellation')
    args = parser.parse_args()
    emulator = support['Emulator'](args.target,19643)
    forward = ('tcp:19643','tcp:19592')
    assert 'Forwardport result:OK' in emulator.hdc('fport',*forward)
    try:
        run(emulator,args.output,args.scripted_review)
    finally:
        emulator.hdc('fport','rm',*forward)
