"""Exercise the real LiveShare gateway and owner RPCs with a loopback Relay stand-in."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import runpy
import select
import subprocess
import time
import uuid

flow = runpy.run_path(str(Path(__file__).with_name('emulator-personalized-recommendations.py')))
support, agent, lsp = (flow[name] for name in ['support', 'agent', 'lsp'])
ws_module = runpy.run_path(str(Path(__file__).with_name('emulator-ptc-approval.py')))['ws_module']
NAME = '@deepseek-ai/dsh-experimental-liveshare'


def owner(device, method, request, timeout=25):
    return device.rpc('liveshareShares/'+method, {'request': request}, timeout=timeout)


def run(device, output):
    node = Path(os.environ.get('DEVECO_HOME', '/Applications/DevEco-Studio.app/Contents'))/'tools/node/bin/node'
    fixture = Path(__file__).with_name('fixtures')/'liveshare-relay.cjs'
    name = 'mh-share-relay-'+uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/'+name
    workspace_path = support['WORKSPACE']+'/'+name
    base = 'http://127.0.0.1:19769'
    bridge = ('tcp:19643', 'tcp:19592')
    temp = '/data/local/tmp/'+name
    paths = [flow['PROFILE']+'/'+part for part in ('package.json', 'pnpm-lock.yaml', 'cordis.patch.yml')]
    paths.append('mobile-harness-boot.json')
    proc = None
    reverse = None
    workspace = None
    share = None
    sessions = []
    saved, evidence = {}, {}
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.ready('normal')
        saved = {path: agent['read_bytes'](device, path) for path in paths}
        assert not flow['market']['catalog'](device, NAME)['enabled']
        flow['flow']['switch'](device, NAME, True)
        proc = subprocess.Popen([str(node), str(fixture), str(ws_module())], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        assert select.select([proc.stdout], [], [], 5)[0], 'Relay did not report a bound port'
        candidate = ('tcp:19769', f'tcp:{int(proc.stdout.readline())}')
        assert 'Forwardport result:OK' in device.hdc('rport', *candidate)
        reverse = candidate
        device.app('mkdir '+folder)
        state = workspace_path+'/owner-shares.json'
        patch = saved[paths[2]].rstrip() + ('\n- id: liveshare-share-host\n  config: '+
                                          json.dumps({'ownerStateFile': state})+'\n').encode()
        expiry = (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        credential = {'relay': base, 'credential': 'fixture-payload.fixture-signature',
                      'expiresAt': expiry, 'subjectId': 'owner'}
        lsp['restore_bytes'](device, folder+'/owner-credential.json', json.dumps(credential).encode(), temp+'-credential')
        device.stop()
        lsp['restore_bytes'](device, paths[2], patch, temp+'-patch')
        device.start()
        device.ready('normal')
        assert owner(device, 'setRelay', {'relayUrl': base})['effective'] == base
        evidence['reachable'] = device.rpc('liveshareShares/testRelay', {})
        assert evidence['reachable'] == {'ok': True, 'httpReachable': True, 'blocking': False}
        registered = device.rpc('workspace/create', {'request': {'path': workspace_path}})
        assert registered['created']
        workspace = registered['workspace']['workspaceId']
        for _ in range(2):
            sessions.append(device.rpc('session/create', {'request': {'workspaceId': workspace}})['sessionId'])
        evidence['authorized'] = owner(device, 'testPublish', {'sessionId': sessions[0]})
        assert evidence['authorized'] == {'ok': True, 'blocking': False}, evidence['authorized']
        created = owner(device, 'create', {'sessionId': sessions[0], 'sessionTitle': 'Loopback DSH fixture',
                                           'sessionMode': 'view', 'allowsFork': False})
        share = created['shareId']
        evidence['created'] = created
        assert created['link'] == base+'/?shareId='+share and created['sessionMode'] == 'view'
        expanded = owner(device, 'addSessions', {'shareId': share, 'sessionIds': [sessions[1]]})
        assert expanded['sessionIds'] == sessions, expanded
        evidence['addedSecondSource'] = True
        flow['flow']['restart'](device)
        until = time.monotonic()+18
        while time.monotonic() < until:
            rows = device.rpc('liveshareShares/list', {})['shares']
            if len(rows) == 1 and rows[0]['online']:
                assert rows[0]['shareId'] == share and rows[0]['sessionIds'] == sessions, rows
                break
            time.sleep(.25)
        else:
            raise AssertionError('LiveShare did not reconnect after restarting the Host')
        evidence['restoredOnlineSources'] = rows[0]['sessionIds']
        evidence['stop'] = owner(device, 'stop', {'shareId': share})
        assert evidence['stop'] == {'ok': True} and device.rpc('liveshareShares/list', {}) == {'shares': []}
        share = None
        disabled = device.rpc('pluginManager/setBundleEnabled', {'name': NAME, 'enabled': False})
        assert disabled['application'] == 'applied', disabled
        until = time.monotonic()+8
        while time.monotonic() < until:
            events = device.app('cat alpine/tmp/dsh-native-timeline.log')
            if 'liveshare-worker-stopped' in events:
                evidence['gatewayThreadStopped'] = True
                break
            time.sleep(.1)
        else:
            raise AssertionError('Disabling LiveShare did not stop the gateway worker')
    finally:
        try:
            try:
                if share:
                    owner(device, 'stop', {'shareId': share})
                for session in sessions:
                    device.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
                if workspace:
                    assert device.rpc('workspace/delete', {'request': {'workspaceId': workspace}}) == {'deleted': True}
            finally:
                if saved:
                    device.stop()
                    device.app('rm -rf '+folder)
                    for i, (path, body) in enumerate(saved.items()):
                        lsp['restore_bytes'](device, path, body, temp+str(i))
                    device.start()
                    evidence['restoredReadyMs'] = device.ready('normal')
                    assert all(agent['read_bytes'](device, path) == body for path, body in saved.items())
                    evidence['configRestored'] = True
        finally:
            if reverse:
                device.hdc('fport', 'rm', *reverse)
            device.hdc('fport', 'rm', *bridge)
            if proc:
                proc.terminate()
                messages, stderr = proc.communicate(timeout=5)
                evidence['relayMessages'] = [json.loads(row) for row in messages.splitlines()]
                if stderr:
                    evidence['relayError'] = stderr
            output.write_text(json.dumps(evidence, indent=2)+'\n')
    created_id = evidence['created']['shareId']
    messages = evidence['relayMessages']
    assert sum(row.get('registered') == created_id for row in messages) >= 2, messages
    assert any(row.get('deleted') == created_id for row in messages), messages
    assert any(row.get('closed') == created_id and row.get('code') == 1000 for row in messages), messages


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(support['Emulator'](args.target, 19643), args.output)
