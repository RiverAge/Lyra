#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { getRepoRoot } from '../common.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const defaultTargetDir = path.resolve(__dirname, '../../../frontend/src');
const defaultExtensions = new Set(['.vue', '.ts', '.css']);
const ignoreMarker = 'style-guard-ignore';

function walkFiles(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkFiles(fullPath));
      continue;
    }
    if (defaultExtensions.has(path.extname(entry.name))) {
      files.push(fullPath);
    }
  }
  return files;
}

function getLineStarts(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === '\n') {
      starts.push(i + 1);
    }
  }
  return starts;
}

function indexToLine(lineStarts, index) {
  let low = 0;
  let high = lineStarts.length - 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    if (lineStarts[mid] <= index) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return high + 1;
}

function shouldIgnore(lines, lineNumber) {
  const current = lines[lineNumber - 1] ?? '';
  const previous = lines[lineNumber - 2] ?? '';
  return current.includes(ignoreMarker) || previous.includes(ignoreMarker);
}

function pushViolation(violations, seenKeys, relPath, lineNumber, message) {
  const key = `${relPath}:${lineNumber}:${message}`;
  if (seenKeys.has(key)) return;
  seenKeys.add(key);
  violations.push({ relPath, lineNumber, message });
}

function scanFile(absPath, repoRoot) {
  const text = fs.readFileSync(absPath, 'utf8');
  const lines = text.split(/\r?\n/);
  const lineStarts = getLineStarts(text);
  const relPath = path.relative(repoRoot, absPath).replace(/\\/g, '/');
  const violations = [];
  const seenKeys = new Set();

  const plainRules = [
    {
      regex: /!important/g,
      message: '禁止使用 `!important`。请通过主题配置、组件 props、结构调整或选择器层级解决样式优先级。',
    },
    {
      regex: /:deep\(/g,
      message: '默认禁止使用 `:deep(...)`。请优先改为主题配置、局部结构调整或带前缀的非 scoped 选择器。',
    },
    {
      regex: /::v-deep/g,
      message: '默认禁止使用 `::v-deep`。请优先改为主题配置、局部结构调整或带前缀的非 scoped 选择器。',
    },
  ];

  for (const rule of plainRules) {
    for (const match of text.matchAll(rule.regex)) {
      const lineNumber = indexToLine(lineStarts, match.index ?? 0);
      if (shouldIgnore(lines, lineNumber)) continue;
      pushViolation(violations, seenKeys, relPath, lineNumber, rule.message);
    }
  }

  const classAttrRegex = /(?:^|[\s<(])(class|icon-class)\s*=\s*("([^"]*)"|'([^']*)')/gms;
  for (const match of text.matchAll(classAttrRegex)) {
    const rawValue = match[3] ?? match[4] ?? '';
    const tokens = rawValue.split(/\s+/).filter(Boolean);
    const badToken = tokens.find((token) => token.startsWith('!'));
    if (!badToken) continue;
    const lineNumber = indexToLine(lineStarts, match.index ?? 0);
    if (shouldIgnore(lines, lineNumber)) continue;
    pushViolation(
      violations,
      seenKeys,
      relPath,
      lineNumber,
      `禁止使用 Tailwind 重要性修饰符 \`${badToken}\`。这会生成 \`!important\`，请改用显式宽度/样式属性、主题配置或组件结构调整。`
    );
  }

  return violations;
}

function resolveTargets(repoRoot, rawArgs) {
  if (rawArgs.length === 0) {
    return walkFiles(defaultTargetDir);
  }

  const normalized = rawArgs
    .map((arg) => path.resolve(repoRoot, arg))
    .filter((absPath) => fs.existsSync(absPath));

  const files = [];
  for (const absPath of normalized) {
    const stat = fs.statSync(absPath);
    if (stat.isDirectory()) {
      files.push(...walkFiles(absPath));
      continue;
    }
    if (defaultExtensions.has(path.extname(absPath))) {
      files.push(absPath);
    }
  }
  return Array.from(new Set(files));
}

export function runStyleGuard(rawArgs = []) {
  const repoRoot = getRepoRoot();
  const targets = resolveTargets(repoRoot, rawArgs);
  const violations = targets.flatMap((file) => scanFile(file, repoRoot));

  if (violations.length === 0) {
    console.log('[quality-gate] style-guard: OK');
    return;
  }

  console.error('=== Style Guard FAILED ===');
  for (const violation of violations) {
    console.error(`${violation.relPath}:${violation.lineNumber} ${violation.message}`);
  }
  console.error(`Found ${violations.length} style guard violation(s).`);
  process.exit(1);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runStyleGuard(process.argv.slice(2));
}
