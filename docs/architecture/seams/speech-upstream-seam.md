# Seam: speech (SenseVoice) upstream provider vs our speech compat

Status: **keep-compat** (no worker-launch injection point as of 0.2.2-rc.5).

## Upstream structure

- `@deepseek-ai/dsh-experimental-speech-to-text-sensevoice` is a managed local provider:
  - `Config` covers `dataRoot`, model directories/origins, VAD, timeouts, buffers, retention
    — **no worker/spawn factory option**;
  - `RuntimePaths.worker` is resolved beside the module (`lib/worker.js`);
  - it launches the worker through `ctx.subprocess.spawn(...)` when a transcription starts,
    speaks a readiness/token protocol over pipes, then calls the worker's transcript transport.
- Sherpa-ONNX native runtime (`sherpa-onnx-node`) needs to run in a Host Node context, not in
  a proot guest process.

## Our current adaptation

`packages/dsh-host/dsh-native-web.cjs` rewrites the upstream module at load time:

1. allows `"openharmony-arm64"` platform in the worker asset table;
2. replaces the `ctx.subprocess.spawn` block with `globalThis.__harmonySpeechLaunch(worker, config, maxLogBytes)`
   — a Host **Worker thread** launcher (`runtime/harmonyos/compat/dsh-harmony-speech.cjs`);
3. removes the pipe-token handshake and routes transcription through the worker handle
   (`handle.transcribe(...)`) instead of the local HTTP transport.

`emulator-voice-input` exercises the real device path.

## Why keep compat

- Upstream's only seam is the generic `ctx.subprocess` service, which would require making the
  **Host subprocess service** behave differently for exactly this worker (program/args sniffing),
  i.e. a hidden contract rather than a real seam.
- The transport swap is a genuine platform adaptation (Worker thread + direct handle), not a bug
  workaround; duplicating it in a package patch would be larger and more fragile than the current
  compat module.

## Future seam

If upstream exposes `workerFactory`/`processServer` in `Config` (or a `SpeechWorker` provider
contract), migrate this module directly. Until then keep-compat and guard with
`emulator-voice-input`.

## Risks

- Worker readiness/error protocol changes upstream will silently break transcription.
- Model download/verify paths stay upstream; only launch/transport is ours.
