/* The Attention screen: what the board asks of the reader, in four ordered queues, and what it could not
   see. The model and the sentences are pure readings of one payload, held to the legacy page by the
   differential tests; the view draws them and acts on nothing but a press. */
export { AttentionAnnouncer } from './AttentionAnnouncer';
export { AttentionView, INITIAL_SECTION_SIZE } from './AttentionView';
export { EXPANDABLE, expansionFor, type Expansion } from './expansion';
export {
  attentionAnnouncement,
  attentionModel,
  publishedTask,
  type AttentionModel,
  type Section,
  type Signal,
  type Subject,
} from './model';
export {
  attentionFor,
  attentionSelectionFor,
  selectAttention,
  selectAttentionSelection,
  type AttentionSelection,
} from './select';
export { WorthALookFlag } from './WorthALookFlag';
