"""Verify the official voice provider, WAV validation, and ArkWeb draft input."""
import argparse
import base64
import io
import json
from pathlib import Path
import runpy
import time
import urllib.request
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
        if not run('''[...document.querySelectorAll('button')].some(button=>
          button.getClientRects().length&&['新建会话','New session','新建聊天','New chat'].includes(
            (button.getAttribute('aria-label')||button.textContent).trim()))'''):
            sidebar['open_sidebar'](emulator)
        flow['button'](run,'button',['新建会话','New session','新建聊天','New chat'])
        browser['wait'](run, '''[...document.querySelectorAll('button')].some(button =>
          ['开始录音','Start recording'].includes(button.getAttribute('aria-label')))''','official recording button')
        # Route a synthetic MediaStream into the real ArkWeb recorder, retaining media
        # capture, audio conversion, the Remote request and the composer update.
        script='''(() => {
          const samples=atob(AUDIO);
          globalThis.__mhVoiceTest={phase:'waiting', recorder:typeof MediaRecorder,
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
            sidebar['tap'](emulator,sidebar['wait_control'](emulator,{'开始录音','Start recording'},'button'))
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
              const {phase,recorder,audioContext,destination,context}=globalThis.__mhVoiceTest||{};
              const row=document.querySelector('[data-voice-activity]');
              return {phase, recorder, audioContext, destination, state:context?.state, ui:row?.textContent};
            })()''')
            raise
        finally:
            run('void globalThis.__mhVoiceTest?.context?.close(); delete navigator.mediaDevices.getUserMedia; delete globalThis.__mhVoiceTest; true')


def run(emulator,args):
    run_name='mh-voice-'+uuid.uuid4().hex[:10]
    remote='/data/local/tmp/'+run_name
    originals, evidence = {}, {}
    models_created=False
    flags=[PROFILE+'/'+f for f in ['package.json','pnpm-lock.yaml','cordis.patch.yml']]+['mobile-harness-boot.json']
    audio=canonical_wave(args.audio)
    try:
        emulator.ready('normal')
        originals={f:agent['read_bytes'](emulator,f) for f in flags}
        evidence['defaultCatalog']=flow['has_bundle'](emulator,VOICE,False)
        assert emulator.app(f'test ! -e {MODEL_ROOT} && printf ABSENT')=='ABSENT', 'Dedicated emulator already has voice cache'
        models_created=True
        cache_models(emulator,args.model_root,remote)
        browser['switch'](emulator,VOICE,True)
        browser['switch'](emulator,INSPECTOR,True)
        browser['restart'](emulator)
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
            args.output.write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    parser.add_argument('--model-root',type=Path,required=True)
    parser.add_argument('--audio',type=Path,required=True)
    parser.add_argument('--arkweb',action='store_true')
    args=parser.parse_args()
    emulator=support['Emulator'](args.target,19643)
    forward=('tcp:19643','tcp:19592')
    assert 'Forwardport result:OK' in emulator.hdc('fport',*forward)
    try:
        run(emulator,args)
    finally:
        emulator.hdc('fport','rm',*forward)
