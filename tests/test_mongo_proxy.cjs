const {test} = require('node:test');
const assert = require('node:assert/strict');
const tls = require('node:tls');
const {EventEmitter} = require('node:events');
const {createSocketPolicy, createHandler} = require('../app/mongo-proxy.cjs');

test('DocumentDB forces certificate and hostname verification for browser sockets', () => {
  const options = createSocketPolicy({documentdb: true, tls: {
    allowInvalidCertificates: true, allowInvalidHostnames: true,
  }})({host: 'cluster.example', port: 27017, tls: false, rejectUnauthorized: false,
       tlsInsecure: true, tlsAllowInvalidCertificates: true, tlsAllowInvalidHostnames: true,
       servername: 'wrong.example', ca: 'untrusted CA', checkServerIdentity: () => undefined,
       minVersion: 'TLSv1', path: '/run/private.sock'});
  assert.equal(options.tls, true);
  assert.equal(options.rejectUnauthorized, true);
  assert.equal(options.checkServerIdentity, tls.checkServerIdentity);
  assert.equal(options.servername, 'cluster.example');
  assert.equal(options.minVersion, 'TLSv1.2');
  assert.equal(options.ca, undefined);
  assert.equal(options.path, undefined);
  assert(options.checkServerIdentity('cluster.example', {subjectaltname: 'DNS:wrong.example'}) instanceof Error);
});

test('generic MongoDB supports plain TCP and server-controlled TLS settings', () => {
  const policy = createSocketPolicy({tls: {allowInvalidHostnames: true}});
  assert.deepEqual(policy({host: 'localhost', port: 27017, tls: false}), {host: 'localhost', port: 27017, tls: false});
  assert.equal(policy({host: 'localhost', tls: true}).rejectUnauthorized, true);
});

test('invalid database targets are rejected', () => {
  const policy = createSocketPolicy({});
  for (const input of [null, {}, {host: '/tmp/socket'}, {host: 'db', port: -1},
                       {host: 'db', port: 65536}, {host: 'db', port: 'invalid'}]) {
    assert.throws(() => policy(input));
  }
});

test('cross-origin WebSockets are closed before database access', () => {
  const socket = new EventEmitter();
  let closeCode;
  socket.close = code => { closeCode = code; };
  createHandler({})(null, socket, {headers: {host: 'localhost:6080', origin: 'https://elsewhere.example'}});
  assert.equal(closeCode, 1008);
});

test('invalid protocol messages close only that socket', () => {
  const socket = new EventEmitter();
  let closeCode;
  socket.close = code => { closeCode = code; };
  createHandler({})(null, socket, {headers: {host: 'localhost:6080'}});
  socket.emit('message', Buffer.from('bad frame'));
  assert.equal(closeCode, 1008);
});
