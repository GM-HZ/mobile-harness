'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { transform } = require('./verify.cjs');

const fixtures = path.resolve(__dirname, '../../../vendor/repos/node/test/fixtures/typescript');
const cases = [
  ['ptc-async-body', 'async function __dsh_program__() {\nconst x: number = await Promise.resolve(42); return x;\n}'],
  ['ptc-repl', 'interface Result { value: bigint }; const answer: Result = { value: 42n }; await Promise.resolve(answer.value)'],
  ['unicode-crlf', 'type 数 = number;\r\nconst 値: 数 = 42;\r\nconsole.log(値);'],
  ['typescript-generics', 'const unwrap = <T,>(value: T): T => value; unwrap<number>(42);'],
  ['large-source', Array.from({ length: 1024 }, (_, i) => `const item${i}: number = ${i};`).join('\n')],
  ['runtime-enum', 'enum Colour { Red }; console.log(Colour.Red);'],
  ['invalid-syntax', 'const a: number = ;'],
];
for (const name of fs.readdirSync(fixtures, { recursive: true }).sort()) {
  const file = path.join(fixtures, name);
  if (/\.(ts|mts|cts)$/.test(name) && fs.statSync(file).isFile()) {
    cases.push([name, fs.readFileSync(file, 'utf8')]);
  }
}

const [candidatePath, outputPath] = process.argv.slice(2);
const { transformSync } = require(path.resolve(candidatePath));
const baseline = cases.map(([name, input]) => [name, input, transform(transformSync, input)]);
fs.writeFileSync(outputPath, JSON.stringify(baseline) + '\n');
