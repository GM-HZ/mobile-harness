'use strict';

const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { Worker, isMainThread, workerData } = require('node:worker_threads');
const { registerHooks } = require('node:module');

function speechLauncher(root, workerPath, mark) {
  return (worker, config, token, logLimit) => {
    if (worker !== workerPath) throw new Error('Unexpected SenseVoice worker entry');
    const thread = new Worker(path.join(root, 'dsh-harmony-speech.cjs'), {
      workerData: { worker }, argv: [JSON.stringify(config)],
      env: { DSH_SPEECH_TOKEN: token }, stdout: true, stderr: true,
    });
    let stderr = Buffer.alloc(0);
    thread.stderr.on('data', chunk => {
      stderr = Buffer.concat([stderr, chunk]).subarray(-logLimit);
    });
    thread.on('error', error => {
      stderr = Buffer.concat([stderr, Buffer.from(error.message)]).subarray(-logLimit);
    });
    const done = new Promise(resolve => thread.once('exit', code => {
      mark('speech-worker-stopped', { code });
      resolve();
    }));
    mark('speech-worker-started');
    return {
      stdout: thread.stdout,
      collected: { stderr: { readFrom: () => ({ text: stderr.toString('utf8') }) } },
      done,
      terminate: () => { void thread.terminate().catch(() => {}); },
      waitForExit: () => done,
    };
  };
}

function installSpeechWorker(worker) {
  const module = { exports: {} };
  process.dlopen(module, 'libdshspeech.so');
  const { open, transcribe } = module.exports;
  if (typeof open !== 'function' || typeof transcribe !== 'function') {
    throw new Error('Harmony SenseVoice Node bindings are unavailable');
  }
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
      return { ...result, source: source.slice(0, from) +
        start + '\n\treturn globalThis.__harmonySpeechTranscribe(config, validateInput);' + source.slice(to) };
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
