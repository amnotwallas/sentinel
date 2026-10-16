import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import process from 'node:process';

const [input, output] = process.argv.slice(2);
if (!input || !output) {
  throw new Error('Usage: node generate-api.mjs <openapi.json> <schema.ts>');
}

const require = createRequire(import.meta.url);
const { default: openapiTS, astToString } = require('openapi-typescript');
const { createConfig } = require('@redocly/openapi-core');
const ts = require('typescript');
const spec = JSON.parse(readFileSync(input, 'utf8'));
const redocly = await createConfig(
  { rules: { 'operation-operationId-unique': { severity: 'error' } } },
  { extends: ['minimal'] },
);

const recursive = new Map();
for (const [name, schema] of Object.entries(spec.components?.schemas ?? {})) {
  function containsSelfReference(value) {
    if (value === null || typeof value !== 'object') return false;
    return (
      value.$ref === `#/components/schemas/${name}` ||
      Object.values(value).some(containsSelfReference)
    );
  }
  if (containsSelfReference(schema)) recursive.set(name, `Generated${name}`);
}

function componentReference(node) {
  if (
    !ts.isIndexedAccessTypeNode(node) ||
    !ts.isLiteralTypeNode(node.indexType) ||
    !ts.isStringLiteral(node.indexType.literal)
  )
    return undefined;
  const schemas = node.objectType;
  if (
    !ts.isIndexedAccessTypeNode(schemas) ||
    !ts.isLiteralTypeNode(schemas.indexType) ||
    !ts.isStringLiteral(schemas.indexType.literal) ||
    schemas.indexType.literal.text !== 'schemas' ||
    !ts.isTypeReferenceNode(schemas.objectType) ||
    !ts.isIdentifier(schemas.objectType.typeName) ||
    schemas.objectType.typeName.text !== 'components'
  )
    return undefined;
  return node.indexType.literal.text;
}

const aliases = [];
const seen = new Set();
const generated = await openapiTS(spec, {
  redocly,
  defaultNonNullable: false,
  postTransform(type, options) {
    const entry = Array.from(recursive).find(
      ([name]) => options.path === `#/components/schemas/${name}`,
    );
    if (!entry) return undefined;
    const [name, alias] = entry;
    assert.ok(!seen.has(name), 'Repeated recursive component transform');
    seen.add(name);
    const transformed = ts.transform(type, [
      (context) => {
        function visit(node) {
          const replacement = recursive.get(componentReference(node));
          if (replacement)
            return ts.factory.createTypeReferenceNode(replacement);
          return ts.visitEachChild(node, visit, context);
        }
        return (node) => ts.visitNode(node, visit);
      },
    ]);
    aliases.push(
      ts.factory.createTypeAliasDeclaration(
        [ts.factory.createModifier(ts.SyntaxKind.ExportKeyword)],
        alias,
        undefined,
        transformed.transformed[0],
      ),
    );
    transformed.dispose();
    return ts.factory.createTypeReferenceNode(alias);
  },
});
assert.equal(seen.size, recursive.size, 'Missing recursive component alias');
const nodes = [...generated, ...aliases];
function rejectAny(node) {
  assert.notEqual(node.kind, ts.SyntaxKind.AnyKeyword, 'Generated any type');
  ts.forEachChild(node, rejectAny);
}
nodes.forEach(rejectAny);
writeFileSync(output, astToString(nodes));
