import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

const config = [
  { ignores: [".next/**", "node_modules/**", "lib/api/schema.d.ts", "playwright-report/**"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default config;
