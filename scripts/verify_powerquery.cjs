// Optional verification dependency: @microsoft/powerquery-parser@4.0.1 (Node >=22).
const fs = require('node:fs');
const path = require('node:path');
const {DefaultSettings, TaskUtils} = require('@microsoft/powerquery-parser');
let root = path.resolve(__dirname, '../pipeline/powerbi/upgrade');
if (!fs.existsSync(root)) root = path.resolve(__dirname, '..');
const model = JSON.parse(fs.readFileSync(path.join(root, 'Banking_Analytics.SemanticModel/model.bim'), 'utf8')).model;
(async () => {
  const results = [];
  for (const table of model.tables) {
    const text = table.partitions[0].source.expression.join('\n');
    const result = await TaskUtils.tryLexParse(DefaultSettings, text);
    const ok = TaskUtils.isOk(result);
    results.push({table: table.name, ok});
    if (!ok) throw new Error(`Power Query parse failed: ${table.name}`);
  }
  const report = {parser: '@microsoft/powerquery-parser 4.0.1', runtimeEvaluated: false, results};
  fs.writeFileSync(path.join(root, 'verification/powerquery_parse.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({parsedQueries: results.length, nativeRuntimeEvaluated: false}));
})().catch(error => {console.error(error.message); process.exitCode = 1;});
