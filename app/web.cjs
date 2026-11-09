"use strict";
const fs = require('node:fs');
const config = JSON.parse(fs.readFileSync(process.env.COMPASS_RUNTIME_CONFIG, 'utf8'));
globalThis.compassHandleMongoConnection = require('./mongo-proxy.cjs').createHandler(config);
Object.assign(process.env, {
  CW_HOST: '127.0.0.1', CW_PORT: '6081',
  CW_APP_NAME: config.name || 'MongoDB Compass',
  CW_ENABLE_EDIT_CONNECTIONS: config.editable ? 'true' : 'false',
  CW_ENABLE_SHELL: 'false', CW_ENABLE_GEN_AI: 'false',
});
if (config.connectionString) process.env.CW_MONGO_URI = config.connectionString;
if (config.storagePassword) process.env.CW_MASTER_PASSWORD = config.storagePassword;
require('/opt/compass-web/node_modules/compass-web/dist/server.js');
