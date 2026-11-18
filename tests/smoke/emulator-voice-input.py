"""Verify the official voice provider, WAV validation, and ArkWeb draft input."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import runpy
import shutil
import threading
import time
import urllib.request
from urllib.parse import urlsplit
import uuid
import wave

flow = runpy.run_path(str(Path(__file__).with_name('emulator-personalized-recommendations.py')))
browser = flow['flow']
support, agent, lsp = (flow[name] for name in ('support','agent','lsp'))
PROFILE, INSPECTOR = flow['PROFILE'], flow['INSPECTOR']
VOICE = '@deepseek-ai/dsh-experimental-voice-input-bundle'
PROVIDER = 'sensevoice-local'
EXPECTED = '今天我们测试语音输入。'
MODEL_ROOT = 'alpine/native-benchmark-home/speech-to-text/sensevoice'


def canonical_wave(source):
    with wave.open(str(source),'rb') as sample:
        assert (sample.getnchannels(),sample.getsampwidth(),sample.getframerate())==(1,2,16000)
        audio=sample.readframes(sample.getnframes())
    output=io.BytesIO()
    with wave.open(output,'wb') as sample:
        sample.setparams((1,2,16000,0,'NONE','not compressed'))
        sample.writeframes(audio)
    return output.getvalue()


def cache_models(emulator, model_root, remote):
    targets = [
        ('model.int8.onnx','models/sensevoice-onnx/'),
        ('tokens.txt','models/sensevoice-onnx/'),
        ('silero_vad.onnx','models/silero/'),
    ]
    emulator.app(f'mkdir -p {MODEL_ROOT}/models/sensevoice-onnx {MODEL_ROOT}/models/silero')
    for index,(name,relative) in enumerate(targets):
        path=model_root/name
        scratch=remote+'-asset'+str(index)
        assert 'FileTransfer finish' in emulator.hdc('file','send',str(path),scratch)
        copied=emulator.app(f'cp {scratch} {MODEL_ROOT}/{relative}{name} && rm -f {scratch} && printf COPIED')
        assert copied=='COPIED',copied


class ModelMirror(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        path=self.server.assets.get(urlsplit(self.path).path)
        if path is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type','application/octet-stream')
        self.send_header('Content-Length',str(path.stat().st_size))
        self.end_headers()
        with path.open('rb') as model:
            shutil.copyfileobj(model,self.wfile)
        self.server.completed.append(path.name)


def model_mirror(root):
    lock=Path('vendor/repos/dsh/packages/experimental/speech-to-text-sensevoice/runtime/assets.json')
    assets=json.loads(lock.read_text())
    selected=[assets['models']['int8'],assets['tokens'],assets['vad']]
    files={urlsplit(asset['url']).path:root/asset['name'] for asset in selected}
    assert all(files[urlsplit(asset['url']).path].stat().st_size==asset['bytes'] for asset in selected)
    server=ThreadingHTTPServer(('127.0.0.1',0),ModelMirror)
    server.assets=files
    server.completed=[]
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


def readiness(emulator, timeout=40):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        rows=emulator.rpc('speech/catalog',{})['providers']
        row=next((row for row in rows if row['id']==PROVIDER),None)
        if row:
            state=row['preparation']
            if state['phase']=='failed':
                raise AssertionError(state)
            if state['phase'] in ['ready','standby']:
                assert row['location']=='host-local'
                return state
        time.sleep(.25)
    raise AssertionError('SenseVoice never became ready')


def transcribe(emulator,payload):
    body=json.dumps({
        'type':'client-request','rpcId':str(uuid.uuid4()),'method':'speech/transcribe',
        'payload':{'args':{'request':payload}},
    }).encode()
    request=urllib.request.Request(emulator.url+'/api/speech/transcribe',body,headers={
        'Content-Type':'application/json','Host':'127.0.0.1:19592','Cookie':emulator.cookie(),
    })
    with emulator.opener.open(request,timeout=55) as response:
        result=json.load(response)['result']
    if not result['ok']:
        raise RuntimeError(f"{result['error']['code']}: {result['error']['message']}")
    return result['value']


def verify_arkweb(emulator,audio,evidence):
    with browser['browser'](emulator) as run:
        sidebar = browser['ui']
        sidebar['open_sidebar'](emulator)
        sidebar['tap'](emulator,sidebar['wait_control'](emulator,{'新建会话','New session','新建聊天','New chat'},'button'))
        start_hit = '''(() => {
          const button=Array.from(document.querySelectorAll('button')).find(node =>
            ['开始录音','Start recording'].includes(node.getAttribute('aria-label')) &&
            !node.disabled && node.getClientRects().length);
          if(!button)return null;
          const rect=button.getBoundingClientRect();
          const hit=document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2);
          return {hit:hit?.closest('button')===button, hitLabel:hit?.closest('button')?.getAttribute('aria-label'),
            x:rect.x,y:rect.y,width:rect.width,height:rect.height,dpr:devicePixelRatio,viewport:[innerWidth,innerHeight]};
        })()'''
        browser['wait'](run,start_hit,'official recording button')
        position=run(start_hit)
        if not position['hit']:
            closers={'关闭侧边栏','Close sidebar'}
            close=sidebar['find'](sidebar['controls'](emulator),closers,'button')
            if close:
                sidebar['tap'](emulator,close)
        browser['wait'](run,'('+start_hit+')?.hit','unobstructed recording button')
        # Route a synthetic MediaStream into the real ArkWeb recorder, retaining media
        # capture, audio conversion, the Remote request and the composer update.
        script='''(() => {
          const samples=atob(AUDIO);
          const trace={clicks:[], errors:[]};
          const onClick=e=>trace.clicks.push({label:e.target.closest('button')?.getAttribute('aria-label'),
            type:e.target.tagName, trusted:e.isTrusted});
          const onError=e=>trace.errors.push(String(e.reason || e.error || e.message));
          document.addEventListener('click',onClick,true);
          window.addEventListener('unhandledrejection',onError);
          window.addEventListener('error',onError);
          globalThis.__mhVoiceTest={phase:'waiting', trace, recorder:typeof MediaRecorder,
            cleanup:()=>{document.removeEventListener('click',onClick,true);
              window.removeEventListener('unhandledrejection',onError); window.removeEventListener('error',onError);},
            audioContext:typeof AudioContext, destination:typeof AudioContext==='function'?
              typeof AudioContext.prototype.createMediaStreamDestination:'unavailable'};
          Object.defineProperty(navigator.mediaDevices,'getUserMedia',{ configurable:true,value:async () => {
            const context=new AudioContext();
            Object.assign(globalThis.__mhVoiceTest,{phase:'resume',context});
            await context.resume();
            globalThis.__mhVoiceTest.phase='decode';
            const bytes=Uint8Array.from(samples,char=>char.charCodeAt(0));
            const clip=await context.decodeAudioData(bytes.buffer);
            const destination=context.createMediaStreamDestination();
            const input=context.createBufferSource();
            input.buffer=clip; input.connect(destination); input.start(context.currentTime+.25);
            Object.assign(globalThis.__mhVoiceTest,{phase:'playing',duration:clip.duration});
            return destination.stream;
          } });
          return true;
        })()'''.replace('AUDIO',json.dumps(base64.b64encode(audio).decode()))
        assert run(script)
        try:
            evidence['arkWebStartControl']=run('''[...document.querySelectorAll('button')].filter(
              btn=>['开始录音','Start recording'].includes(btn.getAttribute('aria-label'))).map(btn=>({
                disabled:btn.disabled, visible:btn.getClientRects().length>0, ariaDisabled:btn.getAttribute('aria-disabled')
              }))''')
            control=sidebar['wait_control'](emulator,{'开始录音','Start recording'},'button')
            evidence['arkWebStartHit']={'dom':run(start_hit),'nativeBounds':control['bounds']}
            sidebar['tap'](emulator,control)
            browser['wait'](run,"Boolean(document.querySelector('[data-voice-activity=recording]'))",'official recorder running')
            duration=run('globalThis.__mhVoiceTest.duration')
            time.sleep(duration+.5)
            flow['button'](run,'button',['停止并识别','Stop and transcribe'])
            browser['wait'](run,f'''[...document.querySelectorAll('textarea,[contenteditable=true]')].some(
              node=>(node.value||node.textContent||'').includes({json.dumps(EXPECTED)}))''','transcript inserted into composer draft')
            evidence['arkWebSyntheticDraft']=True
            sidebar['tap'](emulator,sidebar['wait_control'](emulator,{'开始录音','Start recording'},'button'))
            browser['wait'](run,"Boolean(document.querySelector('[data-voice-activity=recording]'))",'second recording running')
            flow['button'](run,'[data-voice-activity] button',['取消','Cancel'])
            browser['wait'](run, '''!document.querySelector('[data-voice-activity]')''','recorder releases cancelled recording')
            evidence['arkWebRecordingCancelled']=True
        except AssertionError:
            evidence['arkWebRecorderDiagnostic']=run('''(() => {
              const {phase,recorder,audioContext,destination,context,trace}=globalThis.__mhVoiceTest||{};
              const row=document.querySelector('[data-voice-activity]');
              return {phase, recorder, audioContext, destination, state:context?.state, ui:row?.textContent, trace};
            })()''')
            raise
        finally:
            run('globalThis.__mhVoiceTest?.cleanup(); void globalThis.__mhVoiceTest?.context?.close(); delete navigator.mediaDevices.getUserMedia; delete globalThis.__mhVoiceTest; true')


def run(emulator,args):
    run_name='mh-voice-'+uuid.uuid4().hex[:10]
    remote='/data/local/tmp/'+run_name
    originals, evidence = {}, {}
    models_created=False
    mirror=None
    reverse=None
    flags=[PROFILE+'/'+f for f in ['package.json','pnpm-lock.yaml','cordis.patch.yml']]+['mobile-harness-boot.json']
    audio=canonical_wave(args.audio)
    try:
        emulator.ready('normal')
        originals={f:agent['read_bytes'](emulator,f) for f in flags}
        evidence['defaultCatalog']=flow['has_bundle'](emulator,VOICE,False)
        assert emulator.app(f'test ! -e {MODEL_ROOT} && printf ABSENT')=='ABSENT', 'Dedicated emulator already has voice cache'
        models_created=True
        if not args.download:
            cache_models(emulator,args.model_root,remote)
        browser['switch'](emulator,VOICE,True)
        browser['switch'](emulator,INSPECTOR,True)
        if args.download:
            mirror=model_mirror(args.model_root)
            candidate=('tcp:19758',f'tcp:{mirror.server_port}')
            assert 'Forwardport result:OK' in emulator.hdc('rport',*candidate)
            reverse=candidate
            patch=PROFILE+'/cordis.patch.yml'
            overlay=b'\n- id: speech-to-text-sensevoice\n  config:\n    modelOrigin: "http://127.0.0.1:19758"\n'
            lsp['restore_bytes'](emulator,patch,originals[patch].rstrip()+overlay,remote+'-mirror-overlay')
        browser['restart'](emulator)
        if args.download:
            rows=emulator.rpc('speech/catalog',{})['providers']
            row=next(item for item in rows if item['id']==PROVIDER)
            assert row['preparation']['phase']=='unprepared',row
            emulator.rpc('speech/prepare',{'providerId':PROVIDER})
            evidence['downloadPreparation']=readiness(emulator,timeout=100)
            evidence['downloadedAssets']=sorted(mirror.completed)
            assert evidence['downloadedAssets']==['model.int8.onnx','silero_vad.onnx','tokens.txt']
        else:
            evidence['cachePreparation']=readiness(emulator)
        payload={'audioBase64':base64.b64encode(audio).decode(),'language':'auto','providerId':PROVIDER}
        evidence['firstTranscript']=transcribe(emulator,payload)
        assert evidence['firstTranscript']['text']==EXPECTED, evidence['firstTranscript']
        payload['language']='zh'
        evidence['repeatTranscript']=transcribe(emulator,payload)
        assert evidence['repeatTranscript']['text']==EXPECTED,evidence['repeatTranscript']
        try:
            transcribe(emulator,{'audioBase64':'INVALID'})
        except RuntimeError as error:
            assert 'speech/transcription-failed' in str(error),error
            evidence['invalidAudioRejected']=True
        else:
            raise AssertionError('Invalid audio reached the provider')
        if args.arkweb:
            verify_arkweb(emulator,audio,evidence)
        browser['switch'](emulator,VOICE,False)
        rows=[json.loads(line) for line in emulator.app('cat alpine/tmp/dsh-native-timeline.log').splitlines()]
        assert sum(row['event']=='speech-worker-started' for row in rows)==1
        assert sum(row['event']=='speech-worker-stopped' for row in rows)==1
        evidence['workerReusedAndStopped']=True
    except Exception:
        rows=emulator.app("grep 'speech-worker' alpine/tmp/dsh-native-timeline.log || true")
        evidence['workerTimelineOnFailure']=[json.loads(line) for line in rows.splitlines()]
        raise
    finally:
        try:
            if originals:
                emulator.stop()
                if models_created:
                    emulator.app('rm -rf '+MODEL_ROOT)
                emulator.app('rm -f '+remote+'-asset0 '+remote+'-asset1 '+remote+'-asset2')
                for index,(path,data) in enumerate(originals.items()):
                    lsp['restore_bytes'](emulator,path,data,remote+str(index))
                emulator.start()
                evidence['restoreReadyMs']=emulator.ready('normal')
                assert all(agent['read_bytes'](emulator,path)==data for path,data in originals.items())
                evidence['originalConfigurationRestored']=True
        finally:
            try:
                if reverse:
                    emulator.hdc('rport','rm',*reverse)
            finally:
                if mirror:
                    mirror.shutdown()
                    mirror.server_close()
                args.output.write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    parser.add_argument('--model-root',type=Path,required=True)
    parser.add_argument('--audio',type=Path,required=True)
    parser.add_argument('--arkweb',action='store_true')
    parser.add_argument('--download',action='store_true',help='Prepare the pinned models via an isolated mirror')
    args=parser.parse_args()
    emulator=support['Emulator'](args.target,19643)
    forward=('tcp:19643','tcp:19592')
    assert 'Forwardport result:OK' in emulator.hdc('fport',*forward)
    try:
        run(emulator,args)
    finally:
        emulator.hdc('fport','rm',*forward)
