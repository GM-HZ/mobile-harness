declare const poc: {
  run(stage: string, filesDir: string): Promise<string>;
  startNative(root: string, safe: boolean): number;
  nativeStatus(): number;
  usesHostProcess(): boolean;
  stopNative(): boolean;
  localInferenceAvailable(): boolean;
  localInferenceStart(modelPath: string, modelId: string, apiKey: string): number;
  localInferenceStop(): number;
  localInferenceState(): number;
};
export default poc;
