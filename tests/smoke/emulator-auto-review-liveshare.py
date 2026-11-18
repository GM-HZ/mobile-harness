"""Exercise current-session Auto review and the LiveShare owner surface on Phone."""
import argparse
import json
from pathlib import Path
import runpy
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


def run(emulator, output):
    name = 'mh-auto-review-'+uuid.uuid4().hex[:10]
    relative = 'alpine/workspace-native/'+name
    remote = '/data/local/tmp/'+name
    paths = [PROFILE+'/'+file for file in ['package.json','pnpm-lock.yaml','cordis.patch.yml']]
    paths.append('mobile-harness-boot.json')
    originals, evidence, sessions = {}, {}, []
    workspace = None
    try:
        emulator.ready('normal')
        originals = {file:agent['read_bytes'](emulator,file) for file in paths}
        evidence['defaultCatalog'] = [flow['has_bundle'](emulator,bundle,False) for bundle in [AUTO,SHARE]]
        permission_catalog(emulator,False)
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
        emulator.app('mkdir '+relative+' && printf MOBILE_HARNESS_AUTO_REVIEW > '+relative+'/fixture.txt')
        registered = emulator.rpc('workspace/create',{'request':{'path':support['WORKSPACE']+'/'+name}})
        assert registered['created'],registered
        workspace = registered['workspace']['workspaceId']
        with support['model_key'](emulator):
            sid = flow['session'](emulator,workspace,'Auto review fixture '+name,sessions)
            evidence['selectedAuto'] = permission(emulator,sid,'auto')
            result,_ = agent['tool'](emulator,sid,'read',{'file_path':'fixture.txt'})
            assert 'MOBILE_HARNESS_AUTO_REVIEW' in str(result),result
            evidence['autoAllowedRead'] = True
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
    args = parser.parse_args()
    emulator = support['Emulator'](args.target,19643)
    forward = ('tcp:19643','tcp:19592')
    assert 'Forwardport result:OK' in emulator.hdc('fport',*forward)
    try:
        run(emulator,args.output)
    finally:
        emulator.hdc('fport','rm',*forward)
