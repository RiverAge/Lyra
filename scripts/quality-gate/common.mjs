#!/usr/bin/env node
import { execSync } from 'node:child_process';
import process from 'node:process';

export function run(command, cwd) {
  execSync(command, { cwd, stdio: 'inherit' });
}

export function runCapture(command, cwd) {
  return execSync(command, { cwd, encoding: 'utf8' }).trim();
}

export function getRepoRoot() {
  return runCapture('git rev-parse --show-toplevel', process.cwd());
}

export function getPkgCmd() {
  return process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm';
}

export function getStagedFiles(repoRoot) {
  const out = runCapture('git diff --cached --name-only --diff-filter=ACMR', repoRoot);
  return out ? out.split(/\r?\n/).filter(Boolean) : [];
}

export function getAddedLines(repoRoot, file) {
  const diff = runCapture(`git diff --cached -U0 -- "${file}"`, repoRoot);
  return diff
    .split(/\r?\n/)
    .filter((line) => line.startsWith('+') && !line.startsWith('+++ '))
    .map((line) => line.slice(1));
}

export function hasPathPrefix(files, prefix) {
  return files.some((f) => f.startsWith(prefix));
}
