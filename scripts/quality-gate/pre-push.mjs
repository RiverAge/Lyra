#!/usr/bin/env node
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { getPkgCmd, getRepoRoot, run } from './common.mjs';

const repoRoot = getRepoRoot();
const pnpm = getPkgCmd();

// 后端测试:有 backend/tests/ 目录才跑 pytest,早期无后端代码时跳过(不报错)
// 环境策略:优先 conda 环境 lyra(见 AGENTS.md §5),回退到当前 python
const backendDir = join(repoRoot, 'backend');
const testsDir = join(backendDir, 'tests');
if (existsSync(testsDir)) {
  console.log('[quality-gate] pre-push: backend pytest (tests/ exists)');
  let pytestCmd;
  try {
    // 探测 conda 是否可用 + lyra 环境是否存在
    runCapture('conda env list', repoRoot).includes('lyra')
      ? (pytestCmd = 'conda run -n lyra python -m pytest -q')
      : (pytestCmd = 'python -m pytest -q');
  } catch {
    pytestCmd = 'python -m pytest -q';
  }
  run(pytestCmd, backendDir);
} else {
  console.log('[quality-gate] pre-push: backend pytest skipped (no backend/tests/ dir)');
}

console.log('[quality-gate] pre-push: frontend lint/typecheck/build');
run(`${pnpm} --dir frontend run -s lint`, repoRoot);
run(`${pnpm} --dir frontend run -s typecheck`, repoRoot);
run(`${pnpm} --dir frontend run -s build`, repoRoot);
