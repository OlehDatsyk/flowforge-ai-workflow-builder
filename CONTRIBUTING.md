# Contributing

1. Read [INSTRUCTION.md](INSTRUCTION.md), especially the rules at the top, and [SECURITY.md](SECURITY.md).
2. Work on a branch and keep changes focused.
3. Add tests for behaviour changes. Backend logic gets Pytest, graph helpers get Vitest, and user journeys get Playwright.
4. Make sure the backend tests, frontend build and tests, and browser tests pass.
5. Run `pip-audit -r backend/requirements.txt` and `npm audit --omit=dev` when you change dependencies.
6. Update the docs and `CHANGELOG.md`.

Do not commit `.env`, real API keys or database files. Security issues should be reported privately, as described in `SECURITY.md`.

**Style:** Python is type-hinted, with thin routers and logic in `services.py` and `engine/`. TypeScript is strict. Prefer the existing UI components in `components/ui.tsx` over new ones.
