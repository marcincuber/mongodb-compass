"use strict";
const fs = require('node:fs');
const net = require('node:net');
const tls = require('node:tls');

function createSocketPolicy(config) {
  const options = config.tls || {};
  const strict = config.documentdb === true;
  const material = {};
  try {
    if (options.caFile) material.ca = fs.readFileSync(options.caFile);
    if (options.certificateKeyFile) {
      material.cert = material.key = fs.readFileSync(options.certificateKeyFile);
      if (options.password) material.passphrase = options.password;
    }
  } catch {
    throw new Error('Cannot read configured TLS certificate material');
  }
  return (input) => {
    if (!input || typeof input.host !== 'string' ||
        (!net.isIP(input.host) && !/^[a-zA-Z0-9_.-]+$/.test(input.host))) {
      throw new Error('Invalid database host');
    }
    const port = Number(input.port || 27017);
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid database port');
    const secure = strict || input.tls === true || input.tls === 'true';
    const result = {host: input.host, port, tls: secure};
    if (secure) {
      Object.assign(result, material, {
        servername: input.host,
        minVersion: 'TLSv1.2',
        rejectUnauthorized: strict || !options.allowInvalidCertificates,
        checkServerIdentity: !strict && options.allowInvalidHostnames ? () => undefined : tls.checkServerIdentity,
      });
    }
    return result;
  };
}

function createHandler(config) {
  const socketOptions = createSocketPolicy(config);
  return (_app, socket, request) => {
    const origin = request.headers.origin;
    if (origin) {
      try {
        const parsed = new URL(origin);
        if (!['http:', 'https:'].includes(parsed.protocol) || parsed.host !== request.headers.host) throw new Error();
      } catch {
        socket.close(1008, 'Origin is not allowed');
        return;
      }
    }
    let upstream;
    socket.isAlive = true;
    socket.on('pong', () => { socket.isAlive = true; });
    socket.on('message', (message) => {
      try {
        const frame = Buffer.from(message);
        if (upstream) {
          if (frame[0] !== 2) throw new Error('Expected binary database data');
          upstream.write(frame.subarray(1));
          return;
        }
        if (frame[0] !== 1) throw new Error('Expected connection options');
        const {tls: secure, ...options} = socketOptions(JSON.parse(frame.subarray(1).toString()));
        upstream = secure ? tls.connect(options) : net.createConnection(options);
        upstream.setKeepAlive(true, 300000);
        upstream.setTimeout(30000);
        upstream.setNoDelay(true);
        upstream.on('error', () => socket.close(1011, 'Database connection failed'));
        upstream.on('timeout', () => { upstream.destroy(); socket.close(1011, 'Database connection timed out'); });
        upstream.on('close', () => socket.close(1001));
        upstream.on(secure ? 'secureConnect' : 'connect', () => {
          upstream.setTimeout(0);
          socket.send(Buffer.concat([Buffer.from([1]), Buffer.from(JSON.stringify({preMessageOk: 1}))]));
        });
        upstream.on('data', data => socket.send(Buffer.concat([Buffer.from([2]), data])));
      } catch {
        upstream?.destroy();
        socket.close(1008, 'Invalid database connection request');
      }
    });
    socket.on('close', () => upstream?.destroy());
    socket.on('error', () => upstream?.destroy());
  };
}
module.exports = {createSocketPolicy, createHandler};
