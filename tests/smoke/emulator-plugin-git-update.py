"""Use two local Git commits and the device's normal plugin management API."""
import argparse
import json
from pathlib import Path
import runpy
import socket
import subprocess
import tempfile
import time
import uuid

flow=runpy.run_path(str(Path(__file__).with_name('emulator-personalized-recommendations.py')))
support,agent=flow['support'],flow['agent']


def git(directory,*args):
    return subprocess.check_output(['git','-C',str(directory),*args],stderr=subprocess.STDOUT,text=True).strip()


def run(emulator,output):
    name='mh-git-'+uuid.uuid4().hex[:10]
    remote='/data/local/tmp/'+name
    paths=[flow['PROFILE']+'/'+path for path in ('package.json','pnpm-lock.yaml','cordis.patch.yml')]+['mobile-harness-boot.json']
    forward=('tcp:19643','tcp:19592')
    original, evidence, process, reverse={}, {}, None, None
    assert 'Forwardport result:OK' in emulator.hdc('fport',*forward)
    try:
        emulator.ready('normal')
        original={path:agent['read_bytes'](emulator,path) for path in paths}
        with tempfile.TemporaryDirectory(prefix=name) as temp:
            root=Path(temp)
            source=root/'source'
            source.mkdir()
            git(source,'init','-q')
            commits=[]
            for version in ('1.0.0','1.1.0'):
                (source/'package.json').write_text(json.dumps({'name':name,'version':version,'type':'module',
                        'main':'./index.js','exports':{'.':'./index.js','./package.json':'./package.json'},
                        'dsh':{'bundle':{'patch':'./cordis.patch.yml'}}})+'\n')
                (source/'cordis.patch.yml').write_text(f'- insert:\n    - id: {name}\n      name: {name}\n')
                (source/'index.js').write_text('export function apply() {}\n')
                git(source,'add','.')
                git(source,'-c','user.name=Mobile Harness Fixture','-c','user.email=fixture@example.invalid','commit','-qm',version)
                commits.append(git(source,'rev-parse','HEAD'))
            git(root,'clone','-q','--bare',str(source),str(root/'fixture.git'))
            with socket.socket() as check:
                check.bind(('127.0.0.1',0))
                port=check.getsockname()[1]
            process=subprocess.Popen(['git','daemon','--reuseaddr','--listen=127.0.0.1',f'--port={port}','--export-all',
                '--base-path='+str(root),str(root/'fixture.git')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            host=f'git://127.0.0.1:{port}/fixture.git'
            for _ in range(30):
                if subprocess.run(['git','ls-remote',host],capture_output=True).returncode==0: break
                if process.poll() is not None: raise RuntimeError('Local Git daemon exited')
                time.sleep(.1)
            else:
                raise RuntimeError('Local Git daemon did not become ready')
            candidate=('tcp:19759',f'tcp:{port}')
            assert 'Forwardport result:OK' in emulator.hdc('rport',*candidate)
            reverse=candidate
            base='git://127.0.0.1:19759/fixture.git'
            result=emulator.rpc('pluginManager/installBundle',{'spec':base+'#'+commits[0],'options':{'enabled':True}},timeout=125)
            evidence['install']=result
            assert result['version']=='1.0.0' and result['application'] in ['applied','restart-required'],result
            if result['application']=='restart-required': flow['flow']['restart'](emulator)
            denied=emulator.rpc('pluginManager/updateBundle',{'name':name,'version':'1.1.0','options':{'spec':base+'#main'}},timeout=50)
            evidence['unpinnedRejected']=denied
            assert denied['step']=='check' and denied['result']['error']['code']=='invalid-spec',denied
            update=emulator.rpc('pluginManager/updateBundle',{'name':name,'version':'1.1.0','options':{'spec':base+'#'+commits[1]}},timeout=125)
            evidence['update']=update
            assert update['step']=='install' and update['result']['version']=='1.1.0' and update['result']['application'] in ['applied','restart-required'],update
            flow['flow']['restart'](emulator)
            row=flow['market']['catalog'](emulator,name)
            assert row and row['enabled'] and row['installed'] and row['version']=='1.1.0',row
            evidence['retainedUpgrade']=True
    finally:
        try:
            try:
                row=flow['market']['catalog'](emulator,name)
                if row and row['installed']:
                    evidence['cleanupRemoval']=emulator.rpc('pluginManager/removeBundle',{'name':name},timeout=80)
            finally:
                if original:
                    emulator.stop()
                    for i,(path,body) in enumerate(original.items()):
                        flow['lsp']['restore_bytes'](emulator,path,body,remote+'-'+str(i))
                    emulator.start()
                    evidence['restoredReadyMs']=emulator.ready('normal')
                    assert all(agent['read_bytes'](emulator,path)==body for path,body in original.items())
                    evidence['configRestored']=True
        finally:
            try:
                if reverse:
                    emulator.hdc('fport','rm',*reverse)
                    assert ' '.join(reverse) not in emulator.hdc('fport','ls')
            finally:
                if process and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)
                emulator.hdc('fport','rm',*forward)
                output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    run(support['Emulator'](args.target,19643),args.output)
