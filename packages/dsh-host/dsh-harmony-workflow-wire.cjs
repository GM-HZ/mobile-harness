'use strict';

const maxFrame = 4 * 1024 * 1024;
const bindingNames = ['begin', 'progress', 'startChild', 'childResult', 'disposeChild'];

function parseFrames(onMessage) {
  let fragments = [];
  let length = 0;
  return function read(chunk) {
    for (let start = 0; start < chunk.length;) {
      const delimiter = chunk.indexOf(10, start);
      const end = delimiter < 0 ? chunk.length : delimiter;
      length += end - start;
      if (length > maxFrame) throw new Error('Workflow control frame exceeds 4 MiB');
      fragments.push(chunk.subarray(start, end));
      if (delimiter >= 0) {
        const message = JSON.parse(Buffer.concat(fragments, length).toString('utf8'));
        fragments = [];
        length = 0;
        if (message === null || typeof message !== 'object' || Array.isArray(message)) {
          throw new Error('Invalid Workflow control frame');
        }
        onMessage(message);
      }
      start = end + 1;
    }
  };
}

function listen(socket, onMessage, onError) {
  const receive = parseFrames(onMessage);
  socket.on('data', chunk => {
    try { receive(chunk); } catch (error) { onError(error); }
  });
  socket.on('error', onError);
}

function encode(message) {
  const frame = Buffer.from(JSON.stringify(message) + '\n');
  if (frame.length > maxFrame) throw new Error('Workflow control message exceeds 4 MiB');
  return frame;
}

function send(socket, message) {
  const frame = encode(message);
  if (socket.writableLength + frame.length > maxFrame) throw new Error('Workflow control write queue exceeds 4 MiB');
  socket.write(frame);
}

module.exports = { bindingNames, encode, listen, parseFrames, send };
