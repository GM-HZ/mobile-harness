declare const poc: {
  run(stage: string, filesDir: string): Promise<string>;
  startNative(root: string): number;
  nativeStatus(): number;
};
export default poc;
