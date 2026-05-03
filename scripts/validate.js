#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const Ajv = require('ajv');
const addFormats = require('ajv-formats');

const ROOT = path.join(__dirname, '..');
const MARKETPLACE = path.join(ROOT, '.claude-plugin', 'marketplace.json');
const SCHEMA = path.join(ROOT, 'schema', 'marketplace.schema.json');

const ajv = new Ajv({ allErrors: true });
addFormats(ajv);
const validate = ajv.compile(JSON.parse(fs.readFileSync(SCHEMA, 'utf8')));

let errors = 0;
const fail = (msg) => { console.error(`error: ${msg}`); errors++; };

const marketplace = JSON.parse(fs.readFileSync(MARKETPLACE, 'utf8'));

if (!validate(marketplace)) {
  for (const e of validate.errors) {
    fail(`schema ${e.instancePath || '/'}: ${e.message}${e.params ? ' ' + JSON.stringify(e.params) : ''}`);
  }
}

const pluginNames = new Set();
for (const p of marketplace.plugins || []) {
  if (pluginNames.has(p.name)) fail(`duplicate plugin name: ${p.name}`);
  pluginNames.add(p.name);

  const isLocal = typeof p.source === 'string' && p.source.startsWith('./');
  if (!isLocal) continue;

  const dir = path.join(ROOT, p.source);
  if (!fs.existsSync(dir)) {
    fail(`${p.name}: source path missing: ${p.source}`);
    continue;
  }

  const strict = p.strict !== false;
  const manifest = path.join(dir, '.claude-plugin', 'plugin.json');
  if (strict && !fs.existsSync(manifest)) {
    fail(`${p.name}: strict:true requires ${p.source}/.claude-plugin/plugin.json`);
    continue;
  }
  if (!fs.existsSync(manifest)) continue;

  let meta;
  try { meta = JSON.parse(fs.readFileSync(manifest, 'utf8')); }
  catch (e) { fail(`${p.name}: invalid JSON in plugin.json: ${e.message}`); continue; }

  if (!meta.name) fail(`${p.name}: plugin.json missing name`);
  if (meta.name && meta.name !== p.name) {
    fail(`${p.name}: plugin.json name "${meta.name}" must match marketplace name "${p.name}"`);
  }
  if (!meta.description) fail(`${p.name}: plugin.json missing description`);
}

if (errors) {
  console.error(`\n${errors} error(s)`);
  process.exit(1);
}
console.log(`ok: ${marketplace.plugins.length} plugin(s) valid`);
