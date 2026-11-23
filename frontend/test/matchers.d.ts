import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers';
import 'vitest';

declare module 'vitest' {
  interface Assertion<T> {
    toBeInTheDocument: TestingLibraryMatchers<void, T>['toBeInTheDocument'];
    toBeVisible: TestingLibraryMatchers<void, T>['toBeVisible'];
    toHaveAccessibleDescription: TestingLibraryMatchers<void, T>['toHaveAccessibleDescription'];
  }
}
