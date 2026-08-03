import type { TestingLibraryMatchers } from "@testing-library/jest-dom/matchers";

// Teach Vitest's `expect` about the jest-dom matchers (toBeInTheDocument, etc.)
// for the test typecheck. Mirrors @testing-library/jest-dom/types/vitest.d.ts.
declare module "vitest" {
  interface Assertion<T = unknown> extends TestingLibraryMatchers<unknown, T> {}
  interface AsymmetricMatchersContaining extends TestingLibraryMatchers<unknown, unknown> {}
}
