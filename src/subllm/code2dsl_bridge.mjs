// Public code2dsl API from an independently pinned runtime. No .env or LLM.
import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const [runtime, root, output, configurationPathsFile] = process.argv.slice(2);
try {
  const { code2dsl, docs2dsl, config2dsl, getConfig, assertIntentRecords } = await import(
    pathToFileURL(path.join(runtime, 'dist/src/index.js')).href
  );
  const config = getConfig(root);
  Object.assign(config, {
    root, cacheEnabled: false, outputDir: path.join(root, '.intent'),
    maxFileBytes: 8 * 1024 * 1024,
    enablePythonAst: true, enableGoAst: false, enableJavaAst: false,
    enablePhpAst: false, enableRustAst: false,
  });
  const results = await Promise.all([code2dsl({ root }, config), docs2dsl({ root }, config), config2dsl({ root, paths: JSON.parse(await readFile(configurationPathsFile, 'utf8')) }, config)]);
  const result = { records: results.flatMap(r => r.records), warnings: results.flatMap(r => r.warnings) };
  assertIntentRecords(result.records);
  await writeFile(output, JSON.stringify({ records: result.records, warnings: result.warnings }), { mode: 0o600 });
} catch {
  // Extractor exceptions may contain source excerpts.
  process.stderr.write('code2dsl extraction failed\n');
  process.exitCode = 1;
}
