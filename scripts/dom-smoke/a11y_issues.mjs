// Turns the JSON reports of a11y_axe.mjs / a11y_contrast.mjs (A11Y_JSON=...) into GitHub issues.
// One issue per axe rule, one per contrast combination; skips findings that already have an
// open issue with the same title (label `accessibility`). Usage:
//   node a11y_issues.mjs axe.json contrast.json
// Needs the gh CLI and GH_TOKEN. Set A11Y_DRY=1 to print instead of create.
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

const [axePath, contrastPath] = process.argv.slice(2);
const read = (p) => (p && fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : []);

const gh = (args) => execFileSync('gh', args, { encoding: 'utf8' });
const openIssues = new Set(
  JSON.parse(gh(['issue', 'list', '--state', 'open', '--label', 'accessibility', '--limit', '500', '--json', 'title']) || '[]').map((i) => i.title),
);

const create = (title, body) => {
  if (openIssues.has(title)) {
    console.log(`open issue already exists, skipping: ${title}`);
    return false;
  }
  if (process.env.A11Y_DRY) {
    console.log(`would create: ${title}`);
    return false;
  }
  gh(['issue', 'create', '--title', title, '--body', body, '--label', 'accessibility']);
  console.log(`created: ${title}`);
  return true;
};

let created = 0;

// -- axe findings: one issue per rule, listing every element and where it appears.
const byRule = new Map();
for (const e of read(axePath)) {
  if (!byRule.has(e.rule)) byRule.set(e.rule, []);
  byRule.get(e.rule).push(e);
}
for (const [rule, list] of byRule) {
  const title = `A11y (axe): ${rule} — ${list[0].help}`;
  const lines = list.map((e) => `- \`${e.target}\` — ${e.summary}\n  \`${e.html}\`\n  on: ${e.where.join(', ')}`);
  const body = [
    `Rule \`${rule}\` (impact: ${list[0].impact || 'n/a'}), ${list.length} element(s) with this problem.`,
    '',
    ...lines,
    '',
    '_Found by `a11y_axe.mjs` (WCAG 2.2 AA, light and dark, desktop and phone, every page)._',
  ].join('\n');
  if (create(title, body)) { openIssues.add(title); created++; }
}

// -- contrast findings: one issue per element/background combination, worst ratio in the title.
const byCombo = new Map();
for (const e of read(contrastPath)) {
  const k = `${e.sel}|${e.fg}|${e.bg}`;
  const g = byCombo.get(k) || { sel: e.sel, fg: e.fg, bg: e.bg, need: e.need, worst: e, themes: new Map() };
  g.themes.set(e.theme, e);
  if (e.ratio < g.worst.ratio) g.worst = e;
  byCombo.set(k, g);
}
for (const g of byCombo.values()) {
  const title = `A11y (contrast): ${g.sel} — ${g.worst.ratio}:1 (need ${g.worst.need})`;
  const themes = [...g.themes.values()].map((e) => `- ${e.theme}: ${e.ratio}:1 — fg rgb(${e.fg}) on bg rgb(${e.bg}) — "${e.text}" on ${e.where.join(', ')}`);
  const body = [
    `\`${g.sel}\` has text below the ${g.worst.need}:1 threshold.`,
    '',
    ...themes,
    '',
    '_Found by `a11y_contrast.mjs` (4.5:1, large text 3:1, composited over the real background)._',
  ].join('\n');
  if (create(title, body)) { openIssues.add(title); created++; }
}

console.log(`\n${created} issue(s) created, ${openIssues.size} open a11y issue(s) already known.`);
