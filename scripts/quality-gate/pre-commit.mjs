#!/usr/bin/env node
import { hasPathPrefix, getRepoRoot, getPkgCmd, getStagedFiles, run } from './common.mjs';
import { runDisableGuard } from './check-disable.mjs';
import { runStyleGuard } from './frontend/style-guard.mjs';

const repoRoot = getRepoRoot();
const pnpm = getPkgCmd();
const staged = getStagedFiles(repoRoot);

console.log('[quality-gate] pre-commit: disable guard + lint-staged');
runDisableGuard(repoRoot);

if (hasPathPrefix(staged, 'frontend/')) {
  const feStaged = staged.filter((file) => file.startsWith('frontend/'));
  console.log('[quality-gate] pre-commit: frontend style guard (staged touched)');
  runStyleGuard(feStaged);
}

run('pnpm --dir frontend exec lint-staged', repoRoot);

if (hasPathPrefix(staged, 'frontend/')) {
  console.log('[quality-gate] pre-commit: frontend typecheck (staged touched)');
  run(`${pnpm} --dir frontend run -s typecheck`, repoRoot);
}
