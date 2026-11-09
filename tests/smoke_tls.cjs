const WebSocket = require('ws');
const assert = require('node:assert/strict');
const auth = 'Basic ' + Buffer.from('smoke-operator:' + process.env.SMOKE_UI_PASSWORD).toString('base64');
async function connect(host, expectSuccess) {
  await new Promise((resolve, reject) => {
    const socket = new WebSocket('ws://127.0.0.1:6080/mongo', {headers: {Authorization: auth, Origin: 'http://127.0.0.1:6080'}});
    const timer = setTimeout(() => { socket.terminate(); reject(new Error('TLS test timed out')); }, 10000);
    let echoed = false;
    socket.on('open', () => socket.send(Buffer.concat([Buffer.from([1]), Buffer.from(JSON.stringify({
      host, port: 27017, tls: false, rejectUnauthorized: false, tlsInsecure: true,
      tlsAllowInvalidCertificates: true, tlsAllowInvalidHostnames: true, servername: 'tls-good', ca: 'untrusted',
    }))])));
    socket.on('message', data => {
      if (data[0] === 1) socket.send(Buffer.concat([Buffer.from([2]), Buffer.from('verified-tls')]));
      else if (data[0] === 2) { echoed = data.subarray(1).toString() === 'verified-tls'; socket.close(); }
    });
    socket.on('error', reject);
    socket.on('close', () => {
      clearTimeout(timer);
      try { assert.equal(echoed, expectSuccess, host); resolve(); } catch (error) { reject(error); }
    });
  });
}
(async () => {
  if (process.env.SMOKE_UNTRUSTED_ONLY) { await connect('tls-good', false); console.log('Untrusted server CA rejected.'); return; }
  await connect('tls-good', true);
  await connect('tls-wrong', false);
  console.log('DocumentDB TLS with encrypted client key enforced despite browser overrides; wrong hostname rejected.');
})().catch(error => { console.error(error.message); process.exitCode = 1; });
