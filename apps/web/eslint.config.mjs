import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

const config = [
  ...nextVitals,
  ...nextTs,
  {
    ignores: ['.next/**', 'node_modules/**', 'public/**', 'next-env.d.ts', 'coverage/**'],
  },
  {
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.property.name='toLocaleString']",
          message: 'Format numbers and dates through lib/format.ts (design.md 7.5).',
        },
      ],
      'no-restricted-imports': [
        'error',
        { paths: [{ name: 'lucide-react', message: 'Import icons from components/Icon (design.md 22.1).' }] },
      ],
    },
  },
  {
    files: ['components/Icon/**', '**/*.test.ts', '**/*.test.tsx', 'lib/format.ts'],
    rules: { 'no-restricted-imports': 'off', 'no-restricted-syntax': 'off' },
  },
];

export default config;
