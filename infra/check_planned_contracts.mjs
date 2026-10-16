// Validate design contracts without replacing the implemented API/client artifacts.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const frontend = join(root, 'frontend');
const require = createRequire(join(frontend, 'package.json'));
const { default: Ajv } = require('@redocly/ajv/dist/2020');
const { default: openapiTS, astToString } = require('openapi-typescript');
const { createConfig } = require('@redocly/openapi-core');
const ts = require('typescript');
const contractPath = join(root, 'docs/contracts/milestone-2.openapi.json');
const spec = JSON.parse(readFileSync(contractPath, 'utf8'));
const activeTestCaseSchemas = JSON.parse(
  readFileSync(
    join(root, 'backend/src/sentinel/api/catalog/test_case_schemas.json'),
    'utf8',
  ),
);
const fixtures = JSON.parse(
  readFileSync(join(root, 'docs/contracts/milestone-2.fixtures.json'), 'utf8'),
);
const artifactPaths = [
  join(frontend, 'openapi.json'),
  join(frontend, 'src/shared/api/generated/schema.ts'),
];
const digest = (path) =>
  createHash('sha256').update(readFileSync(path)).digest('hex');
const before = artifactPaths.map(digest);
assert.equal(spec.openapi, '3.1.0');
assert.match(spec['x-sentinel-status'], /planned/i);

const activeRoots = [
  'TestCaseWrite',
  'TestCaseRevision',
  'TestCaseDetail',
  'TestCaseSummary',
  'TestCasePage',
  'TestCaseRevisionPage',
];
const expectedActiveNames = new Set();
const pendingActiveNames = [...activeRoots];
while (pendingActiveNames.length > 0) {
  const name = pendingActiveNames.pop();
  if (expectedActiveNames.has(name)) continue;
  const schema = spec.components.schemas[name];
  assert.ok(schema, `Missing accepted active schema: ${name}`);
  expectedActiveNames.add(name);
  for (const match of JSON.stringify(schema).matchAll(
    /#\/components\/schemas\/([^"\\]+)/g,
  )) {
    pendingActiveNames.push(match[1]);
  }
}
assert.deepEqual(
  Object.keys(activeTestCaseSchemas).sort(),
  Array.from(expectedActiveNames).sort(),
  'Active test-case schema closure drifted from the accepted contract',
);
for (const name of expectedActiveNames) {
  assert.deepEqual(
    activeTestCaseSchemas[name],
    spec.components.schemas[name],
    `Active test-case schema drifted: ${name}`,
  );
}

function checkReferences(value) {
  if (value === null || typeof value !== 'object') return;
  if (typeof value.$ref === 'string') {
    assert.ok(
      value.$ref.startsWith('#/'),
      'Only local planned schema references are permitted',
    );
    const target = value.$ref
      .slice(2)
      .split('/')
      .reduce(
        (node, segment) =>
          node?.[segment.replaceAll('~1', '/').replaceAll('~0', '~')],
        spec,
      );
    assert.notEqual(target, undefined, 'Unresolved planned schema reference');
  }
  for (const child of Object.values(value)) checkReferences(child);
}
checkReferences(spec);

const expectedOperations = [
  'get /api/v1/projects',
  'post /api/v1/projects',
  'get /api/v1/projects/{project_id}',
  'get /api/v1/projects/{project_id}/environments',
  'post /api/v1/projects/{project_id}/environments',
  'get /api/v1/environments/{environment_id}',
  'patch /api/v1/environments/{environment_id}',
  'get /api/v1/projects/{project_id}/test-cases',
  'post /api/v1/projects/{project_id}/test-cases',
  'get /api/v1/test-cases/{test_case_id}',
  'put /api/v1/test-cases/{test_case_id}',
  'get /api/v1/test-cases/{test_case_id}/revisions',
  'get /api/v1/projects/{project_id}/suites',
  'post /api/v1/projects/{project_id}/suites',
  'get /api/v1/suites/{suite_id}',
  'put /api/v1/suites/{suite_id}',
];
const methods = new Set([
  'get',
  'post',
  'put',
  'patch',
  'delete',
  'head',
  'options',
  'trace',
]);
const operations = Object.entries(spec.paths).flatMap(([path, item]) =>
  Object.keys(item)
    .filter((method) => methods.has(method))
    .map((method) => `${method} ${path}`),
);
assert.deepEqual(operations.sort(), expectedOperations.sort());

// OpenAPI annotations are allowed; all structural JSON Schema checks remain active.
const ajv = new Ajv({ strict: false, allErrors: true, validateFormats: false });
const schemaId = 'urn:sentinel:planned-contract';
ajv.addSchema(spec, schemaId);
for (const [name, schema] of Object.entries(spec.components.schemas)) {
  assert.ok(ajv.validateSchema(schema), `Invalid component schema: ${name}`);
  ajv.compile({ $ref: `${schemaId}#/components/schemas/${name}` });
}
assert.ok(
  fixtures.cases.some((item) => item.valid),
  'Missing positive contract examples',
);
assert.ok(
  fixtures.cases.some((item) => !item.valid),
  'Missing negative contract examples',
);
for (const fixture of fixtures.cases) {
  assert.ok(
    /^[A-Za-z][A-Za-z0-9_]*$/.test(fixture.schema),
    'Invalid fixture schema name',
  );
  const validate = ajv.compile({
    $ref: `${schemaId}#/components/schemas/${fixture.schema}`,
  });
  assert.equal(
    validate(fixture.value),
    fixture.valid,
    `Fixture failed: ${fixture.name}`,
  );
  // Never print rejected values or raw AJV error parameters.
}

const directory = mkdtempSync(join(tmpdir(), 'sentinel-planned-contract-'));
try {
  // Explicit configuration prevents discovery of an unrelated multi-API config.
  const redocly = await createConfig(
    { rules: { 'operation-operationId-unique': { severity: 'error' } } },
    { extends: ['minimal'] },
  );
  const environment = Object.fromEntries(
    Object.entries(process.env).filter(
      ([name]) => !name.startsWith('SENTINEL_'),
    ),
  );
  // Indexed recursive array types trigger TS2502 in the installed generator.
  // Derive named aliases from its AST; never maintain separate handwritten shapes.
  const recursive = new Map();
  for (const [name, schema] of Object.entries(spec.components.schemas)) {
    function containsSelfReference(value) {
      if (value === null || typeof value !== 'object') return false;
      return (
        value.$ref === `#/components/schemas/${name}` ||
        Object.values(value).some(containsSelfReference)
      );
    }
    if (containsSelfReference(schema)) recursive.set(name, `Planned${name}`);
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
    cwd: directory,
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
  writeFileSync(join(directory, 'schema.ts'), astToString(nodes));
  const examples = fixtures.cases
    .filter((item) => item.valid)
    .map(
      (item, index) =>
        `const example${index} = ${JSON.stringify(item.value)} satisfies components["schemas"]["${item.schema}"];`,
    );
  writeFileSync(
    join(directory, 'examples.ts'),
    'import type { components } from "./schema";\n' +
      examples.join('\n') +
      '\n',
  );
  execFileSync(
    process.execPath,
    [
      join(frontend, 'node_modules/.bin/tsc'),
      '--noEmit',
      '--strict',
      '--target',
      'ES2022',
      '--module',
      'ESNext',
      '--moduleResolution',
      'bundler',
      join(directory, 'examples.ts'),
    ],
    { cwd: directory, env: environment, stdio: 'pipe' },
  );
} finally {
  rmSync(directory, { recursive: true, force: true });
  assert.deepEqual(
    artifactPaths.map(digest),
    before,
    'Runtime contract artifacts changed',
  );
}
console.log(
  `${operations.length} planned catalog operations; ${Object.keys(spec.components.schemas).length} schemas; ${fixtures.cases.length} fixture cases validated; generated TypeScript examples compile. Runtime artifacts unchanged.`,
);
