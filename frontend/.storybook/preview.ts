import type { Preview } from '@storybook/react-vite';
import '../src/styles/tailwind.css';
import '../src/styles/shell.css';
import '../src/styles/controls.css';

const preview: Preview = {
  parameters: { layout: 'padded', backgrounds: { disable: true } },
  beforeEach: async () => {
    await document.fonts.load('15px Inter');
    await document.fonts.ready;
  },
};
export default preview;
