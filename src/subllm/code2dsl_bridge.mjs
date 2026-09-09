// Public code2dsl API from an independently pinned runtime. No .env or LLM.
import { writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const [runtime, root, output] = process.argv.slice(2);
try {
  const { code2dsl, getConfig, assertIntentRecords } = await import(
    pathToFileURL(path.join(runtime, 'dist/src/index.js')).href
  );
  const config = getConfig(root);
  Object.assign(config, {
    root, cacheEnabled: false, outputDir: path.join(root, '.intent'),
    maxFileBytes: 8 * 1024 * 1024,
    enablePythonAst: true, enableGoAst: false, enableJavaAst: false,
    enablePhpAst: false, enableRustAst: false,
  });
  const result = await code2dsl({ root }, config);
  assertIntentRecords(result.records);
  await writeFile(output, JSON.stringify({ records: result.records, warnings: result.warnings }), { mode: 0o600 });
} catch {
  // Extractor exceptions may contain source excerpts.
  process.stderr.write('code2dsl extraction failed\n');
  process.exitCode = 1;
}
