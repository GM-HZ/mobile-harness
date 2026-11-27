"""Verify the official voice provider, WAV validation, and ArkWeb draft input."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import runpy
import threading
import subprocess
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
LOCK = Path(__file__).resolve().parents[2]/'vendor/repos/dsh/packages/experimental/speech-to-text-sensevoice/runtime/assets.json'
APP_ID = 'org.sayact.nodepoc'
START = {'开始录音', 'Start recording'}


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
        request_path=urlsplit(self.path).path
        self.server.requests.append(request_path)
        path=self.server.assets.get(request_path)
        if path is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type','application/octet-stream')
        self.send_header('Content-Length',str(path.stat().st_size))
        self.end_headers()
        sent=0
        try:
            with path.open('rb') as model:
                for chunk in iter(lambda:model.read(256*1024),b''):
                    self.wfile.write(chunk)
                    sent+=len(chunk)
                    # Limit emulator reverse-port backpressure while DSH hashes and writes the model.
                    time.sleep(len(chunk)/(12*1024*1024))
            self.server.completed.append(path.name)
        finally:
            self.server.transferred[path.name]=sent


def model_mirror(root):
    assets=json.loads(LOCK.read_text())
    selected=[assets['models']['int8'],assets['tokens'],assets['vad']]
    files={urlsplit(asset['url']).path:root/asset['name'] for asset in selected}
    assert all(files[urlsplit(asset['url']).path].stat().st_size==asset['bytes'] for asset in selected)
    server=ThreadingHTTPServer(('127.0.0.1',0),ModelMirror)
    server.assets=files
    server.completed=[]
    server.requests=[]
    server.transferred={}
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


def readiness(emulator, timeout=40, phases=('ready','standby')):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        rows=emulator.rpc('speech/catalog',{})['providers']
        row=next((row for row in rows if row['id']==PROVIDER),None)
        if row:
            state=row['preparation']
            if state['phase']=='failed':
                raise AssertionError(state)
            if state['phase'] in phases:
                assert row['location']=='host-local'
                return state
        time.sleep(.25)
    raise AssertionError(f'SenseVoice never entered {phases}')


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


def open_voice_composer(emulator, run):
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
    if not run(start_hit)['hit']:
        closers={'关闭侧边栏','Close sidebar'}
        close=sidebar['find'](sidebar['controls'](emulator),closers,'button')
        if close:
            sidebar['tap'](emulator,close)
    return browser['wait'](run,'('+start_hit+')?.hit && ('+start_hit+')','unobstructed recording button')


def verify_arkweb(emulator,audio,evidence):
    with browser['browser'](emulator) as run:
        sidebar = browser['ui']
        position = open_voice_composer(emulator, run)
        # Route a synthetic MediaStream into the real ArkWeb recorder, retaining media
        # capture, audio conversion, the Remote request and the composer update.
        script='''(() => {
          const samples=atob(AUDIO);
          const trace={clicks:[], errors:[]};
          const contexts=[];
          const devices=navigator.mediaDevices;
          const descriptor=Object.getOwnPropertyDescriptor(devices,'getUserMedia');
          const onClick=e=>trace.clicks.push({label:e.target.closest('button')?.getAttribute('aria-label'),
            type:e.target.tagName, trusted:e.isTrusted});
          const onError=e=>trace.errors.push(String(e.reason || e.error || e.message));
          document.addEventListener('click',onClick,true);
          window.addEventListener('unhandledrejection',onError);
          window.addEventListener('error',onError);
          globalThis.__mhVoiceTest={phase:'waiting', trace, recorder:typeof MediaRecorder,
            cleanup:async()=>{document.removeEventListener('click',onClick,true);
              window.removeEventListener('unhandledrejection',onError); window.removeEventListener('error',onError);
              if(descriptor) Object.defineProperty(devices,'getUserMedia',descriptor);
              else delete devices.getUserMedia;
              await Promise.allSettled(contexts.map(async context => {
                if(context.state!=='closed') await context.close();
              }));
              return contexts.every(context=>context.state==='closed');},
            audioContext:typeof AudioContext, destination:typeof AudioContext==='function'?
              typeof AudioContext.prototype.createMediaStreamDestination:'unavailable'};
          Object.defineProperty(devices,'getUserMedia',{ configurable:true,value:async () => {
            const context=new AudioContext();
            contexts.push(context);
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
            control=sidebar['wait_control'](emulator,START,'button')
            evidence['arkWebStartHit']={'dom':position,'nativeBounds':control['bounds']}
            sidebar['tap'](emulator,control)
            browser['wait'](run,"Boolean(document.querySelector('[data-voice-activity=recording]'))",'official recorder running')
            duration=run('globalThis.__mhVoiceTest.duration')
            time.sleep(duration+.5)
            flow['button'](run,'button',['停止并识别','Stop and transcribe'])
            browser['wait'](run,f'''[...document.querySelectorAll('textarea,[contenteditable=true]')].some(
              node=>(node.value||node.textContent||'').includes({json.dumps(EXPECTED)}))''','transcript inserted into composer draft')
            evidence['arkWebSyntheticDraft']=True
            sidebar['tap'](emulator,sidebar['wait_control'](emulator,START,'button'))
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
            assert run('''(async () => {
              try { return await globalThis.__mhVoiceTest.cleanup(); }
              finally { delete globalThis.__mhVoiceTest; }
            })()'''), 'Synthetic recorder contexts did not close'


def microphone_permission(emulator):
    info = json.loads(emulator.hdc('shell', 'atm', 'dump', '-t', '-b', APP_ID))
    entries = [section for section in info.values() if isinstance(section, list)]
    row, = (item for section in entries for item in section if item.get('permissionName') == 'ohos.permission.MICROPHONE')
    return {'status': row['grantStatus'], 'flag': row['grantFlag']}


def grant_native_microphone(emulator, ui, result):
    ui['tap'](emulator, ui['wait_control'](emulator, START, 'button'))
    deadline = time.monotonic() + 15
    previous = None
    while time.monotonic() < deadline:
        rows = ui['controls'](emulator, bundle=None)
        dialog = any(('麦克风' in row['text'] and '访问' in row['text'])
                     or 'access your microphone' in row['text'].lower() for row in rows)
        allow = ui['find'](rows, {'允许', 'Allow', 'While using the app', 'Allow while using the app'}) if dialog else None
        if allow and allow == previous:
            break
        previous = allow
        time.sleep(.2)
    else:
        raise AssertionError('HarmonyOS did not present a stable native microphone permission dialog')
    ui['tap'](emulator, allow)
    result['nativePermissionDialog'] = True
    deadline = time.monotonic() + 5
    while True:
        permission = microphone_permission(emulator)
        result['nativePermissionAfterTap'] = permission
        if permission['status'] == 0:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f'HarmonyOS did not grant the microphone after the Allow tap: {permission}')
        time.sleep(.2)


NATIVE_MICROPHONE_HOOK = '''(() => {
  const devices = navigator.mediaDevices;
  const descriptor = Object.getOwnPropertyDescriptor(devices, 'getUserMedia');
  const original = devices.getUserMedia.bind(devices);
  const trace = { phase: 'not-called', errorName: null, visibility: [] };
  const recordVisibility = ({type}) => {
    if (trace.visibility.length < 12) trace.visibility.push({type, state: document.visibilityState});
  };
  recordVisibility({type: 'initial'});
  document.addEventListener('visibilitychange', recordVisibility);
  window.addEventListener('blur', recordVisibility);
  window.addEventListener('focus', recordVisibility);
  let released = false;
  trace.cleanup = () => {
    released = true;
    document.removeEventListener('visibilitychange', recordVisibility);
    window.removeEventListener('blur', recordVisibility);
    window.removeEventListener('focus', recordVisibility);
    globalThis.__mhNativeTracks?.forEach(track => track.stop());
    delete globalThis.__mhNativeTracks;
    if (descriptor) Object.defineProperty(devices, 'getUserMedia', descriptor);
    else delete devices.getUserMedia;
    delete globalThis.__mhNativeMicTrace;
  };
  globalThis.__mhNativeMicTrace = trace;
  Object.defineProperty(devices, 'getUserMedia', { configurable: true, value: async (constraints) => {
    trace.phase = 'pending';
    try {
      const stream = await original(constraints);
      if (released) {
        stream.getTracks().forEach(track => track.stop());
        throw new DOMException('Fixture ended', 'AbortError');
      }
      globalThis.__mhNativeTracks = stream.getAudioTracks();
      trace.phase = 'resolved';
      return stream;
    } catch (error) {
      trace.phase = 'rejected';
      trace.errorName = /^[A-Za-z]{1,48}Error$/.test(error?.name) ? error.name : 'UnknownError';
      throw error;
    }
  } });
  return true;
})()'''


def record_native_microphone_failure(emulator, run, result):
    diagnostic = result['nativeRecorderDiagnostic'] = {}
    try:
        diagnostic['permission'] = microphone_permission(emulator)
    except Exception as error:
        diagnostic['permissionProbeError'] = type(error).__name__
    try:
        diagnostic['arkWeb'] = run('''(() => {
          const trace = globalThis.__mhNativeMicTrace;
          const voiceState = document.querySelector('[data-voice-activity]')?.dataset.voiceActivity;
          return { visibilityState: document.visibilityState, visibility: trace?.visibility,
            phase: trace?.phase, errorName: trace?.errorName, voiceState,
            audioTrackCount: globalThis.__mhNativeTracks?.length ?? 0 };
        })()''', timeout=5)
    except Exception as error:
        diagnostic['arkWebProbeError'] = type(error).__name__


def verify_native_arkweb(emulator, evidence):
    assert microphone_permission(emulator) == {'status': -1, 'flag': 0}, 'Expected an unused test permission state'
    ui = browser['ui']
    result = evidence['nativeMicrophone'] = {}
    try:
        with browser['browser'](emulator) as run:
            open_voice_composer(emulator, run)
            assert run(NATIVE_MICROPHONE_HOOK)
            try:
                grant_native_microphone(emulator, ui, result)
                browser['wait'](run, "Boolean(document.querySelector('[data-voice-activity=recording]'))",
                                'official recorder using the native microphone')
                active = run('globalThis.__mhNativeTracks.map(t => ({kind:t.kind, state:t.readyState, muted:t.muted}))')
                assert active == [{'kind': 'audio', 'state': 'live', 'muted': False}], active
                assert microphone_permission(emulator)['status'] == 0
                result['liveAudioTrack'] = active[0]
                flow['button'](run,'[data-voice-activity] button',['取消','Cancel'])
                browser['wait'](run, '''!document.querySelector('[data-voice-activity]') &&
                  globalThis.__mhNativeTracks.every(t => t.readyState === 'ended')''', 'native tracks ended on cancellation')
                result['trackEndedOnCancel'] = True
            except Exception:
                record_native_microphone_failure(emulator, run, result)
                raise
            finally:
                run('globalThis.__mhNativeMicTrace?.cleanup(); true')
    finally:
        emulator.hdc('shell', 'atm', 'perm', '-r', '-b', APP_ID)
        assert microphone_permission(emulator) == {'status': -1, 'flag': 0}
        result['permissionRestored'] = True



CAPTURE_HOOK = """(() => {
  const devices = navigator.mediaDevices;
  const original = devices.getUserMedia.bind(devices);
  Object.defineProperty(devices, 'getUserMedia', { configurable: true, value: async (constraints) => {
    const stream = await original(constraints);
    const context = new AudioContext();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
    const buffer = new Float32Array(analyser.fftSize);
    const state = { samples: 0, sumSquares: 0, peak: 0, context, analyser };
    state.timer = setInterval(() => {
      analyser.getFloatTimeDomainData(buffer);
      let sum = 0, peak = 0;
      for (const value of buffer) { sum += value * value; peak = Math.max(peak, Math.abs(value)); }
      state.samples += buffer.length;
      state.sumSquares += sum;
      state.peak = Math.max(state.peak, peak);
    }, 40);
    globalThis.__mhNativeCapture = state;
    return stream;
  } });
  return true;
})()"""

CAPTURE_STATS = """(() => {
  const state = globalThis.__mhNativeCapture;
  if (!state) return null;
  clearInterval(state.timer);
  const rms = state.samples ? Math.sqrt(state.sumSquares / state.samples) : 0;
  return { samples: state.samples, durationSeconds: state.samples / state.context.sampleRate,
           rms, peak: state.peak, sampleRate: state.context.sampleRate };
})()"""


def verify_native_capture(emulator, audio_path, evidence):
    """Record through the native microphone while the host plays a known clip."""
    assert microphone_permission(emulator) == {'status': -1, 'flag': 0}, 'Expected an unused test permission state'
    ui = browser['ui']
    result = evidence['nativeMicCapture'] = {}
    playback = None
    try:
        with browser['browser'](emulator) as run:
            open_voice_composer(emulator, run)
            assert run(NATIVE_MICROPHONE_HOOK)
            try:
                assert run(CAPTURE_HOOK)
                grant_native_microphone(emulator, ui, result)
                browser['wait'](run, "Boolean(document.querySelector('[data-voice-activity=recording]'))",
                                'official recorder using the native microphone')
                playback = subprocess.Popen(['afplay', str(audio_path)])
                time.sleep(4.5)
                playback.terminate()
                playback.wait(timeout=5)
                playback = None
                flow['button'](run, 'button', ['停止并识别', 'Stop and transcribe'])
                try:
                    browser['wait'](run, f'''[...document.querySelectorAll('textarea,[contenteditable=true]')].some(
                      node=>(node.value||node.textContent||'').includes({json.dumps(EXPECTED)}))''',
                                    'native capture transcribed')
                    result['draftMatched'] = True
                except AssertionError:
                    result['draftMatched'] = False
                result['draft'] = run("(() => { const node=document.querySelector('textarea,[contenteditable=true]');"
                                      " return (node?.value||node?.textContent||'').trim(); })()")
                result['capture'] = run(CAPTURE_STATS)
                result['audioPlayoutSeconds'] = 4.5
                capture = result['capture'] or {}
                assert capture.get('samples', 0) > capture.get('sampleRate', 48000), capture
                assert capture.get('rms', 0) > 0.005, ['silent native capture', capture]
                assert result['draftMatched'] is True, result
            except Exception:
                record_native_microphone_failure(emulator, run, result)
                raise
            finally:
                if playback:
                    playback.terminate()
                    playback.wait(timeout=5)
                run('''(async () => {
                  const capture = globalThis.__mhNativeCapture;
                  delete globalThis.__mhNativeCapture;
                  globalThis.__mhNativeMicTrace?.cleanup();
                  if(capture) {
                    clearInterval(capture.timer);
                    if(capture.context.state !== 'closed') await capture.context.close();
                  }
                  return true;
                })()''')
    finally:
        emulator.hdc('shell', 'atm', 'perm', '-r', '-b', APP_ID)
        result['permissionRestored'] = microphone_permission(emulator) == {'status': -1, 'flag': 0}
        assert result['permissionRestored']


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
        originals={f:browser['profile_bytes'](emulator,f) for f in flags}
        evidence['defaultCatalog']=flow['has_bundle'](emulator,VOICE,False)
        assert emulator.app(f'test ! -e {MODEL_ROOT} && printf ABSENT')=='ABSENT', 'Dedicated emulator already has voice cache'
        models_created=True
        if not (args.download or args.public_download):
            cache_models(emulator,args.model_root,remote)
        browser['switch'](emulator,VOICE,True)
        browser['switch'](emulator,INSPECTOR,True)
        if args.download:
            mirror=model_mirror(args.model_root)
            patch=PROFILE+'/cordis.patch.yml'
            overlay=(b'\n- id: speech-to-text-sensevoice\n  config:\n'
                     b"    dataRoot: !!js dshHomePath('speech-to-text', 'sensevoice')\n"
                     b'    modelOrigin: "http://127.0.0.1:19758"\n')
            lsp['restore_bytes'](emulator,patch,originals[patch].rstrip()+overlay,remote+'-mirror-overlay')
        browser['restart'](emulator)
        if args.download:
            evidence['downloadInitialState']=readiness(emulator,phases=('unprepared',))
            candidate=('tcp:19758',f'tcp:{mirror.server_port}')
            reply=emulator.hdc('rport',*candidate)
            assert 'Forwardport result:OK' in reply,reply
            reverse=candidate
            emulator.rpc('speech/prepare',{'providerId':PROVIDER})
            evidence['downloadPreparation']=readiness(emulator,timeout=100)
            evidence['downloadedAssets']=sorted(mirror.completed)
            assert evidence['downloadedAssets']==['model.int8.onnx','silero_vad.onnx','tokens.txt']
        elif args.public_download:
            evidence['downloadInitialState']=readiness(emulator,phases=('unprepared',))
            evidence['publicOrigin']=args.public_download
            request={'providerId':PROVIDER}
            if args.public_download!='auto':
                request['options']={'downloadSource':args.public_download}
            emulator.rpc('speech/prepare',request)
            try:
                evidence['downloadPreparation']=readiness(emulator,timeout=240)
            except AssertionError as error:
                evidence['publicPreparationFailure']=error.args[0]
                raise
            lock=json.loads(LOCK.read_text())
            verified={}
            for folder,asset in [('sensevoice-onnx',lock['models']['int8']),('sensevoice-onnx',lock['tokens']),('silero',lock['vad'])]:
                target=f"{MODEL_ROOT}/models/{folder}/{asset['name']}"
                checksum=emulator.app('sha256sum '+target).split()[0]
                assert checksum==asset['sha256'], (asset['name'],checksum)
                verified[asset['name']]=checksum
            evidence['publicAssetSha256']=verified
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
        if args.arkweb or args.native_mic or args.native_mic_transcribe:
            emulator.hdc('shell','power-shell','wakeup')
            emulator.start()
        if args.arkweb:
            verify_arkweb(emulator,audio,evidence)
        if args.native_mic:
            verify_native_arkweb(emulator,evidence)
        if args.native_mic_transcribe:
            verify_native_capture(emulator,args.audio,evidence)
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
                    if data is None:
                        emulator.app('rm -f '+path)
                    else:
                        lsp['restore_bytes'](emulator,path,data,remote+str(index))
                emulator.start()
                evidence['restoreReadyMs']=emulator.ready('normal')
                assert all(browser['profile_bytes'](emulator,path)==data for path,data in originals.items())
                evidence['originalConfigurationRestored']=True
        finally:
            try:
                if reverse:
                    emulator.hdc('fport','rm',*reverse)
                    assert ' '.join(reverse) not in emulator.hdc('fport','ls')
            finally:
                if mirror:
                    mirror.shutdown()
                    mirror.server_close()
                    evidence['mirrorRequests']=mirror.requests
                    evidence['mirrorBytesSent']=mirror.transferred
                args.output.write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    parser.add_argument('--model-root',type=Path)
    parser.add_argument('--audio',type=Path,required=True)
    parser.add_argument('--arkweb',action='store_true')
    parser.add_argument('--native-mic',action='store_true',help='Grant the real emulator microphone through the system dialog, then verify cancellation')
    parser.add_argument('--native-mic-transcribe',action='store_true',help='Record through the native microphone while the host plays a clip, then transcribe it')
    parser.add_argument('--port',type=int,default=19643)
    source=parser.add_mutually_exclusive_group()
    source.add_argument('--download',action='store_true',help='Prepare the pinned models via an isolated mirror')
    source.add_argument('--public-download',choices=['auto','https://huggingface.co','https://hf-mirror.com'],
                        help='Prepare an empty cache through one shipped public source')
    args=parser.parse_args()
    if not args.public_download and args.model_root is None:
        parser.error('--model-root is required for local fixtures')
    emulator=support['Emulator'](args.target,args.port)
    forward=(f'tcp:{args.port}','tcp:19592')
    assert 'Forwardport result:OK' in emulator.hdc('fport',*forward)
    try:
        run(emulator,args)
    finally:
        emulator.hdc('fport','rm',*forward)
