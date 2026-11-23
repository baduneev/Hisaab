import fs from 'node:fs/promises';
import openapiTS, { astToString } from 'openapi-typescript';
const response = await fetch('http://127.0.0.1:8008/openapi.json');
if (!response.ok) throw new Error('Start the API before generating types');
const schema = await response.json();
await fs.mkdir('web/generated', { recursive: true });
await fs.writeFile('web/generated/api.ts', astToString(await openapiTS(schema)));
await fs.writeFile('openapi.json', JSON.stringify(schema, null, 2) + '\n');
