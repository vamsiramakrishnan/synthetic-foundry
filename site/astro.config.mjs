// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightLlmsTxt from 'starlight-llms-txt';
import starlightLinksValidator from 'starlight-links-validator';

// `site` is required by starlight-llms-txt: llms.txt links are absolute.
// It matches the GitHub Pages origin for vamsiramakrishnan/synthetic-foundry.
export default defineConfig({
  site: 'https://vamsiramakrishnan.github.io',
  integrations: [
    starlight({
      title: 'Worldloom',
      description:
        'A deterministic compiler for coherent synthetic enterprise corpora.',
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/vamsiramakrishnan/synthetic-foundry',
        },
      ],
      customCss: ['./src/styles/rams.css'],
      plugins: [starlightLlmsTxt(), starlightLinksValidator()],
      sidebar: [
        {
          label: 'Getting started',
          items: [
            { label: 'Installation', slug: 'getting-started/installation' },
            { label: 'Quickstart', slug: 'getting-started/quickstart' },
          ],
        },
        {
          label: 'Concepts',
          items: [
            { label: 'Architecture', slug: 'concepts/architecture' },
            { label: 'Determinism', slug: 'concepts/determinism' },
            { label: 'Validation', slug: 'concepts/validation' },
            { label: 'Evaluation', slug: 'concepts/evaluation' },
          ],
        },
        {
          label: 'Guides',
          items: [
            { label: 'Narration', slug: 'guides/narration' },
            { label: 'Rendering', slug: 'guides/rendering' },
            { label: 'Counterfactual twins', slug: 'guides/twins' },
            { label: 'Fleets', slug: 'guides/fleets' },
            { label: 'Authoring a company', slug: 'guides/authoring' },
            { label: 'Messiness and noise', slug: 'guides/messiness' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'CLI', slug: 'reference/cli' },
            { label: 'Corpus anatomy', slug: 'reference/corpus-anatomy' },
            { label: 'Verticals', slug: 'reference/verticals' },
          ],
        },
      ],
    }),
  ],
});
