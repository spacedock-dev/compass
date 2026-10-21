/* Claude Code wraps a paste in `<pasted_content id="N">` and `</pasted_content>`, and `records.strip_paste_wrapper`
   takes the two tags off before the server publishes a direction. This is the same rule on the page, for a
   direction an older server or a republished history still sends with them, so the reader never reads the
   harness's tags, or the paste's number, as their own words. The text between them stays; only the two tags go.
   It lives here, below every view, so the project and timeline pages draw a direction the way the session
   page does. */
const PASTE_TAG = /<\/?pasted_content(?:\s[^<>]*)?>/g;

export function stripPasteWrapper(text: string): string {
  return text.replace(PASTE_TAG, '').trim();
}
