'use strict';

const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { Worker, isMainThread, parentPort, workerData } = require('node:worker_threads');
const { registerHooks } = require('node:module');

function speechLauncher(root, workerPath, mark) {
  return (worker, config, logLimit) => {
    if (worker !== workerPath) throw new Error('Unexpected SenseVoice worker entry');
    const thread = new Worker(path.join(root, 'dsh-harmony-speech.cjs'), {
      workerData: { worker }, argv: [JSON.stringify(config)],
      env: {}, stdout: true, stderr: true,
    });
    const ready = Promise.withResolvers();
    let stderr = Buffer.alloc(0);
    let pending;
    let closed = false;
    const append = chunk => { stderr = Buffer.concat([stderr, chunk]).subarray(-logLimit); };
    thread.stdout.resume();
    thread.stderr.on('data', append);
    thread.on('error', error => append(Buffer.from(error.message)));
    thread.on('message', message => {
      if (message.type === 'ready') ready.resolve();
      else if (message.type === 'transcript') pending?.resolve(message.result);
    });
    const done = new Promise(resolve => thread.once('exit', code => {
      closed = true;
      const error = new Error('SenseVoice worker exited' + (stderr.length ? ': ' + stderr.toString('utf8').trim() : ''));
      ready.reject(error);
      pending?.reject(error);
      mark('speech-worker-stopped', { code });
      resolve();
    }));
    mark('speech-worker-started');
    return {
      ready: ready.promise,
      done,
      terminate: () => { void thread.terminate().catch(() => {}); },
      waitForExit: () => done,
      async transcribe(audio, language, signal) {
        signal.throwIfAborted();
        if (closed || pending) throw new Error('SenseVoice worker is unavailable');
        const result = Promise.withResolvers();
        pending = result;
        const abort = () => result.reject(signal.reason);
        signal.addEventListener('abort', abort, { once: true });
        try {
          const bytes = Uint8Array.from(audio);
          thread.postMessage({ audio: bytes, language }, [bytes.buffer]);
          return await result.promise;
        } finally {
          signal.removeEventListener('abort', abort);
          pending = undefined;
        }
      },
    };
  };
}

function serve(transcribe, SpeechInputError) {
  parentPort.on('message', ({ audio, language }) => {
    let result;
    try {
      result = { ok: true, value: transcribe(audio, language) };
    } catch (error) {
      result = { ok: false, message: error.message, invalidInput: error instanceof SpeechInputError };
    }
    parentPort.postMessage({ type: 'transcript', result });
  });
  parentPort.postMessage({ type: 'ready' });
}

function installSpeechWorker(worker) {
  const module = { exports: {} };
  process.dlopen(module, 'libdshspeech.so');
  const { open, transcribe } = module.exports;
  if (typeof open !== 'function' || typeof transcribe !== 'function') {
    throw new Error('Harmony SenseVoice Node bindings are unavailable');
  }
  globalThis.__harmonySpeechServe = serve;
  globalThis.__harmonySpeechTranscribe = (config, validateInput) => {
    const model = open(config.model, config.tokens, config.vad, config.threads, config.vadThreshold,
      config.minSilenceSeconds, config.minSpeechSeconds, config.segmentSeconds);
    const onset = Math.round(config.vadOnsetPaddingSeconds * 16000);
    return (audio, language) => {
      const audioSeconds = validateInput(audio, language, config.maxAudioBytes);
      const pcm = new DataView(audio.buffer, audio.byteOffset + 44, audio.byteLength - 44);
      const samples = Float32Array.from({ length: pcm.byteLength / 2 }, (_, i) => pcm.getInt16(i * 2, true) / 32768);
      const started = performance.now();
      const text = transcribe(model, samples, language, onset).map(part => part.trim()).filter(Boolean).join(' ');
      return { text, audioSeconds, inferenceSeconds: (performance.now() - started) / 1000 };
    };
  };
  const entry = pathToFileURL(worker).href;
  registerHooks({
    load(url, context, nextLoad) {
      const result = nextLoad(url, context);
      if (url !== entry) return result;
      const source = Buffer.isBuffer(result.source) ? result.source.toString('utf8') : String(result.source);
      const start = 'function createTranscriber(config) {';
      const signature = 'const sherpa = createRequire(import.meta.url)("sherpa-onnx-node");';
      const from = source.indexOf(start);
      const to = source.indexOf('\n}', from);
      if (from < 0 || to < 0 || source.indexOf(start, from + 1) >= 0 || !source.slice(from, to).includes(signature)) {
        throw new Error('Unexpected pinned SenseVoice transcriber');
      }
      const boot = source.indexOf('\n\tconst token = z.string().regex(', to);
      const end = source.indexOf('\n}', boot);
      if (boot < 0 || end < 0 || !source.slice(boot, end).includes('startRecognitionServer(token, config.maxAudioBytes, createTranscriber(config))')) {
        throw new Error('Unexpected pinned SenseVoice worker bootstrap');
      }
      return { ...result, source: source.slice(0, from) +
        start + '\n\treturn globalThis.__harmonySpeechTranscribe(config, validateInput);' +
        source.slice(to, boot) + '\n\tglobalThis.__harmonySpeechServe(createTranscriber(config), SpeechInputError);' +
        source.slice(end) };
    },
  });
  void import(entry).catch(error => {
    process.stderr.write(error.message + '\n', () => process.exit(1));
  });
}

if (!isMainThread && workerData?.worker) {
  installSpeechWorker(workerData.worker);
} else {
  exports.speechLauncher = speechLauncher;
}
