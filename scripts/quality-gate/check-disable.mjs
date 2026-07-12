#!/usr/bin/env node
import { getAddedLines, getStagedFiles } from './common.mjs';

export function runDisableGuard(repoRoot) {
  const allowDisableFiles = new Set([
    'frontend/src/auto-imports.d.ts',
  ]);
  const failures = [];
  const bypassSourceExt = /\.(js|mjs|cjs|ts|tsx|jsx|vue|svelte)$/;
  const staged = getStagedFiles(repoRoot);
  for (const file of staged) {
    if (file === 'scripts/quality-gate/check-disable.mjs') continue;
    if (!bypassSourceExt.test(file)) continue;
    const addedLines = getAddedLines(repoRoot, file);
    for (const line of addedLines) {
      const hasBypass = /eslint-disable|@ts-ignore|@ts-nocheck/i.test(line);
      if (!hasBypass || allowDisableFiles.has(file)) continue;
      const hasReason = /eslint-disable-next-line\s+.+--\s*原因：.+/.test(line);
      if (!hasReason) failures.push(`[disable] ${file}: ${line.trim()}`);
    }
  }
  if (failures.length > 0) {
    console.error('\n[quality-gate] failed: lint/type bypass without reason:\n');
    for (const f of failures) console.error(`- ${f}`);
    process.exit(1);
  }
}
