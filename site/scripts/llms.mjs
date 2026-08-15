// Postbuild: rewrite dist/llms.txt with a per-page link list.
//
// starlight-llms-txt emits llms-full.txt and llms-small.txt with the page
// content, but its llms.txt names only those two sets. The llms.txt spec
// wants a link per page with a one-line description, so this walks the
// content collection frontmatter and writes that index. Deterministic:
// ordering follows the sidebar order encoded in the directory groups below.
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const docs = join(root, '..', 'src', 'content', 'docs');
const dist = join(root, '..', 'dist');
// Includes the /synthetic-foundry base: this is a project Pages site, and
// an llms.txt link without the base points at a page that does not exist.
const site = 'https://vamsiramakrishnan.github.io/synthetic-foundry';

const order = [
  'index.mdx',
  'getting-started/installation.mdx',
  'getting-started/quickstart.mdx',
  'concepts/architecture.mdx',
  'concepts/determinism.mdx',
  'concepts/validation.mdx',
  'concepts/evaluation.mdx',
  'guides/narration.mdx',
  'guides/rendering.mdx',
  'guides/twins.mdx',
  'guides/fleets.mdx',
  'guides/authoring.mdx',
  'guides/messiness.mdx',
  'reference/cli.mdx',
  'reference/corpus-anatomy.mdx',
  'reference/verticals.mdx',
];

function frontmatter(path) {
  const text = readFileSync(path, 'utf8');
  const match = text.match(/^---\n([\s\S]*?)\n---/);
  const out = {};
  if (!match) return out;
  for (const line of match[1].split('\n')) {
    const kv = line.match(/^(title|description):\s*(.*)$/);
    if (kv) out[kv[1]] = kv[2].trim();
  }
  return out;
}

const lines = [
  '# Worldloom',
  '',
  '> A deterministic compiler for coherent synthetic enterprise corpora.',
  '',
  '## Docs',
  '',
];

for (const rel of order) {
  const file = join(docs, rel);
  if (!existsSync(file)) continue;
  const { title, description } = frontmatter(file);
  const slug = rel === 'index.mdx' ? '' : rel.replace(/\.mdx$/, '') + '/';
  lines.push(`- [${title}](${site}/${slug}): ${description}`);
}

lines.push(
  '',
  '## Optional',
  '',
  `- [Complete documentation](${site}/llms-full.txt): every page, full text`,
  `- [Abridged documentation](${site}/llms-small.txt): the same pages, compacted`,
  '',
);

writeFileSync(join(dist, 'llms.txt'), lines.join('\n'));
console.log('llms.txt rewritten with', order.length, 'page links');
