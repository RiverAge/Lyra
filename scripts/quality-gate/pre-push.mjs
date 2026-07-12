#!/usr/bin/env node
import { getPkgCmd, getRepoRoot, run } from './common.mjs';

const repoRoot = getRepoRoot();
const pnpm = getPkgCmd();

console.log('[quality-gate] pre-push: frontend lint/typecheck/build');
run(`${pnpm} --dir frontend run -s lint`, repoRoot);
run(`${pnpm} --dir frontend run -s typecheck`, repoRoot);
run(`${pnpm} --dir frontend run -s build`, repoRoot);
