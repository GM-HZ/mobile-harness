declare const poc: {
  run(stage: string, filesDir: string): Promise<string>;
  startNative(root: string, safe: boolean): number;
  nativeStatus(): number;
  usesHostProcess(): boolean;
  stopNative(): boolean;
};
export default poc;
