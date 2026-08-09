module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:vue/vue3-recommended',
  ],
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  rules: {
    'no-unused-vars': 'warn',
    'vue/no-unused-vars': 'warn',
    'vue/no-v-html': 'warn',
    'no-constant-condition': 'warn',
  },
}