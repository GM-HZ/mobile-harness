'use strict';
(async()=>{
 const started=Date.now();
 const result={platform:process.platform,node:process.version,execArgv:process.execArgv,wasm:typeof WebAssembly};
 console.log('START',JSON.stringify(result));
 const bytes=Buffer.from('0061736d010000000105016000017f0302010007070103666f6f00000a06010400412a0b','hex');
 result.value=new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports.foo();
 console.log('WASM',JSON.stringify(result));
 const js=require('node:module').stripTypeScriptTypes('const value: number = 42; value');
 result.typeScript=require('node:vm').runInNewContext(js);
 const http=require('node:http');
 const server=http.createServer((_q,r)=>{r.setHeader('Connection','close');r.end('42')});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const response=await fetch('http://127.0.0.1:'+server.address().port,{signal:AbortSignal.timeout(4000)});
 result.fetch={status:response.status,body:await response.text()};
 await new Promise(resolve=>server.close(resolve));
 result.elapsedMs=Date.now()-started;console.log('RESULT',JSON.stringify(result));process.exit(0);
})().catch(error=>{console.error('ERROR',error.stack);process.exit(1)});
