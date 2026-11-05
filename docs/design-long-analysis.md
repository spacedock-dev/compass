# Long analysis

Ordinary Analyze makes one model call. Long analysis is a separate explicit press for a native Claude Code session whose admitted evidence needs several prompts. It uses the saved intent and the route shown for that press. It does not extend the unasked lane or grant permission to resume after a restart.

The [reading design](design-reading-a-session.md) owns what may count as evidence, what a reading may say, and how later directions affect intent. The [runtime architecture](design-runtime-architecture.md) owns the module map. The [security contract](../SECURITY.md) owns outgoing content, permissions, storage and numerical limits.

## A plan is a bound, not a coverage claim

The preview names the route, saved per-prompt ceiling and maximum calls before Start. It reads metadata rather than session bodies and reserves nothing. Start refreshes that authority. Saving a drafted goal changes the intent binding, so it finishes separately and requires a fresh preview before analysis starts. The native source collector then freezes the admitted streams and reads them under one cumulative allowance. Revalidation consumes that same allowance; wrapping a snapshot again cannot restore spent preparation time or I/O.

The plan's `prepare_ms` measurement is `source-and-analysis-preparation`: source collection,
CI acquisition, packet construction and response processing, with model waits excluded. It is
separate from whole-job elapsed time and from the retained object graph, which is not process RSS.

Actual packet planning happens once. Its exact evidence-call count is published before the first model factory runs. A separate final slot remains reserved even when fewer evidence calls are needed. Its ordinal is not a charge count. Known uncovered ranges or required final evidence that cannot fit refuse before paying for maps that cannot produce a reading.

## Original words remain the evidence

Complete admitted messages are joined to their canonical source identity, masked and normalized before any cut. Ranges index the resulting Unicode characters; byte fitting measures the fully serialized UTF-8 prompt, including frozen intent and protocol text. Each evidence packet repeats up to 4,096 masked characters immediately before and after its primary span, including continuations of a split message. Adjacent atomic facts and strict final replies remain whole. Required context that cannot fit refuses the plan. This bounded context does not guarantee that the model understands every correction. Context does not advance primary range assignment; repeated text counts once toward unique text coverage and every time toward transmitted input.

The source's physical order survives clock rollback. Original fact identities and timestamps remain unchanged, because request floors and the existing resolver still need them. Copied Compass corrections retain their derived authorship and cannot become independent person intent or support.

Evidence replies use a closed schema and local menu numbers. Parsing immediately binds each citation to the original identity and actual rendered range. Unknown fields, foreign numbers, overflow or malformed replies make the pass unusable. An empty candidate list says only that no usable candidates were proposed. Candidate text is unstored navigation sent to the final call, never a ledger fact, final citation or proof that the goal was met.

## Reconciliation restores originals

The final prompt has a fresh numbered menu. It restores mandatory person and atomic evidence, candidate originals and relevant later counterevidence. Adjacent or overlapping ranges can merge. Disjoint slices do not become a fictional whole message. A named final reply needs the existing complete-source proof and must fit as one actual row; an unfit final cannot be smuggled through the ordinary fragment path. Adopted goals likewise require their complete verified original words in every prompt.

The final reply goes through the existing parser, resolver and full frozen-corpus guards. A failed source or map, missing required context, or overflow withholds a new assessment. When maps succeeded but all ordinary agent prose cannot fit the final packet, only original-supported structural departures on outcome lines may survive. Other clauses become Can't tell. That partial result cannot establish absence, global consistency or the agent's account of completion.

## Each call and publication have their own boundary

Every actual reservation checks current permission, route, target and remaining job allowance. Failed calls and failures discovered after reservation retain their charge. Calls are sequential, with no automatic retry, shortening or provider fallback. Before a call there must be room for its full timeout. The supervisor checks that allowance again after waiting for launch admission, immediately before spawn, using only owned monotonic state under its launch lock. After the final response, publication checks the elapsed whole-job deadline without allocating another call.

The annotation publication owner checks the captured target again. A qualified partial reading may replace the old assessment. A withheld, cancelled or failed attempt leaves the old assessment available and records the latest outcome separately.

Restart markers and SQLite receipts retain word-free bindings and accounting, not prompts, candidate prose or authority to run again. Inspection distinguishes exact totals, known minimums and unknown counts. Recovery does not infer death from a missing marker or resume a model call. A terminal label is accounting metadata, not authority to discard an obsolete record.

History is an explicit read, not a recovery trigger. Discard re-proves session attribution, a
dead terminal owner, exact accounting and positive target supersession under the server's locks.
An empty record, bare Clear or lost response supplies none of those proofs. Retiring a marker
does not refund calls, stop a process or authorize another model run. Unconfirmed child cleanup
holds the live job's slot; the page exposes that blocked state rather than announcing completion.

## Shortcuts deliberately rejected

- Reusing the legacy prompt builder for arbitrary evidence packets could reorder or drop originals after allocation and detach local citations from the prompt.
- Taking model summaries or votes as proof would lose counterevidence and let candidate prose invent citable facts.
- Filling gaps with an ordinary Analyze call would change the declared scope and charge a call the plan did not authorize.
- Treating final ordinal 17 as 17 spent calls, or a missing receipt as zero, would misstate the reader's allowance.
- Reconstructing execution from durable markers would turn accounting metadata into permission to send session content again.

Synthetic fixtures and fake transports check these application boundaries. They do not establish the model's accuracy on real long sessions.

The guarded pipeline fixture uses a native source of about 3 MiB with the actual 512 KiB prompt
ceiling: seven evidence calls and the reserved final slot produce eight SQLite charges for one
job. Its middle failed check remains an original citation in a partial result. That proves the
application can carry the evidence through multiple prompts; it is not a paid-model accuracy
measurement or a promise that every source of that size fits.
