import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers';
import 'vitest';

declare module 'vitest' {
  interface Assertion<T> {
    toBeInTheDocument: TestingLibraryMatchers<T, void>['toBeInTheDocument'];
    toBeVisible: TestingLibraryMatchers<T, void>['toBeVisible'];
    toHaveAccessibleDescription: TestingLibraryMatchers<T, void>['toHaveAccessibleDescription'];
  }
}
