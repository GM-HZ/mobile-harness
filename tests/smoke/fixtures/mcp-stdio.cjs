const readline = require('node:readline');
const { writeFileSync } = require('node:fs');
const { cwd, argv, env } = process;
if (!cwd().endsWith('/workspace-native') || argv[2] !== "literal '$(); \" argument" ||
    env.MH_FIXTURE !== "space 'quote'\nnext" || env.DEEPSEEK_API_KEY !== undefined) {
  process.exit(3);
}
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on('line', line => {
  const request = JSON.parse(line);
  if (request.id === undefined) return;
  let result;
  switch (request.method) {
    case 'initialize':
      result = {protocolVersion: request.params.protocolVersion, serverInfo:{name:'node-stdio-fixture',version:'1'}, capabilities:{tools:{}}};
      break;
    case 'tools/list':
      result = {tools:[{name:'stdio_fixture_echo', description:'Returns a fixed marker', inputSchema:{type:'object',properties:{}}}]};
      if (env.MH_LIVE === '1') writeFileSync(argv[1] + '.ready', 'ok');
      break;
    case 'tools/call':
      if (request.params.name === 'stdio_fixture_echo') result = {content:[{type:'text',text:'MH_MCP_STDIO_OK'}]};
      break;
  }
  if (request.method === 'initialize') process.stderr.write('fixture diagnostic\n');
  const reply = result ? {result} : {error:{code:-32601,message:'Method not found'}};
  process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:request.id,...reply})+'\n');
});
