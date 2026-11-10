// Exercise the same MongoDB-over-WebSocket framing used by the browser client.
const net = require('node:net');
const {MongoClient} = require('mongodb');
const WebSocket = require('ws');
const clients = new Set();
const auth = 'Basic ' + Buffer.from('smoke-operator:' + process.env.SMOKE_UI_PASSWORD).toString('base64');
const server = net.createServer(client => {
  clients.add(client);
  const ws = new WebSocket('ws://127.0.0.1:6080/mongo', {headers: {Authorization: auth, Origin: 'http://127.0.0.1:6080'}});
  let ready = false;
  const pending = [];
  const send = data => ws.send(Buffer.concat([Buffer.from([2]), data]));
  client.on('error', () => {});
  client.on('data', data => ready ? send(data) : pending.push(data));
  client.on('close', () => { clients.delete(client); ws.close(); });
  ws.on('open', () => ws.send(Buffer.concat([Buffer.from([1]), Buffer.from(JSON.stringify({host: 'mongo-smoke', port: 27017, tls: false}))])));
  ws.on('message', frame => {
    if (frame[0] === 1) { ready = true; pending.splice(0).forEach(send); }
    else if (frame[0] === 2) client.write(frame.subarray(1));
  });
  ws.on('error', () => client.destroy());
  ws.on('close', () => client.destroy());
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const password = encodeURIComponent(process.env.SMOKE_DB_PASSWORD);
  const client = new MongoClient(`mongodb://smoke-user:${password}@127.0.0.1:${server.address().port}/?authSource=admin&directConnection=true&tls=false`, {serverSelectionTimeoutMS: 10000});
  try {
    await client.connect();
    await client.db('admin').command({ping: 1});
    const status = await client.db('admin').command({serverStatus: 1});
    if (status.tcmalloc?.usingPerCPUCaches !== false) {
      throw new Error('MongoDB fixture must disable TCMalloc per-CPU caches for kernel compatibility');
    }
    const collection = client.db('smoke').collection('browser_transport');
    await collection.insertOne({_id: 'websocket', verified: true});
    const document = await collection.findOne({_id: 'websocket'});
    if (!document?.verified) throw new Error('Database round trip failed');
    console.log('MongoDB fixture per-CPU caches disabled; authenticated insert/read passed through the browser WebSocket transport.');
  } finally {
    await client.close();
    for (const connection of clients) connection.destroy();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error.name + ': ' + error.message); process.exitCode = 1; });
