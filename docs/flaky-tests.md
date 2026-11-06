# Flaky tests

This is the tally of tests that failed in CI and then passed on the same code. It exists so that a
flake gets fixed instead of re-run until it goes away. [AGENTS.md](../AGENTS.md#flaky-tests) says
when a row is added or raised.

`python3 scripts/flaky_tally.py` reads the last week of CI runs and prints what this table is
missing. It writes nothing; a person or an agent edits the table.

## How to read a row

- **Test** is `module.Class.method`, the last three parts of the unittest id. A failing subtest
  counts against its test.
- **Count** is the number of CI runs it failed in. A run that retried it and passed counts too.
- **Where** names the OS, the Python and the job, and every run the count includes, by run id. The
  tally treats a run named here as recorded.
- **Symptom** quotes the line the failure ended with.
- **Status** is `open` until a pull request removes the cause, then `fixed` with that pull
  request. A fixed test that fails again goes back to `open`.

## Ledger

| Test | First seen | Last seen | Count | Where | Symptom | Status | Fixing PR |
|---|---|---|---|---|---|---|---|
| `test_session_outline.SessionOutlineTest.test_all_parent_poll_reads_share_one_actual_byte_allowance` | 2026-11-06 | 2026-11-06 | 1 | macOS, Python 3.15, `Tests (macos-latest, Python 3.15, dashboard)`; run 42188478248 attempt 1, PR #811 | "AssertionError: 0 not greater than 0" | open | |
| `test_project_script_checks.ANameOrABodyThatIsNotACheckNeverCounts.test_a_variable_that_cannot_reach_the_runner_leaves_the_script_a_check` | 2026-11-06 | 2026-11-06 | 1 | Linux, Python 3.12, `Runtime floor (Python 3.12, dashboard 1)`; run 42164926705, push to main | "FileNotFoundError: [Errno 2] No such file or directory: '/tmp/tmpb5gbbbdb/work/billing/.git/objects'" (subtest `command='MAKEFLAGS=-j4 make lint'`) | open | |
| `test_long_intent_sources.LongIntentSourcesTest.test_a_reader_with_a_hundred_megabyte_record_can_open_recent_words_and_get_honest_menu_coverage` | 2026-11-06 | 2026-11-06 | 1 | macOS, Python 3.15, `Tests (macos-latest, Python 3.15, dashboard)`; run 42215659225, merge queue entry for PR #813 | "AssertionError: 'bytes' != 'time'" | fixed | #817 |
| `test_supervise.GroupQuiescenceTest.test_a_group_that_remains_live_exhausts_the_same_deadline` | 2026-11-06 | 2026-11-06 | 1 | Linux, Python 3.12, `Runtime floor (Python 3.12, dashboard 1)`; run 42225631356, merge queue entry for PR #818 | "AssertionError: False is not true" | open | |
| `test_react_frontend.InstalledFrontendTest.test_a_second_start_on_a_busy_port_says_to_use_the_running_dashboard` | 2026-11-06 | 2026-11-06 | 1 | Linux, Python 3.14, `Tests under coverage (dashboard 1)`; run 42223113240, push to main | "AssertionError: 0 != 1 : Compass: port 46867 is already in use." | open | |
| `test_observer.SupervisedModelCallTest.test_a_cli_that_floods_its_output_file_is_stopped_near_the_bound` | 2026-11-06 | 2026-11-06 | 1 | macOS, Python 3.15, `Tests (macos-latest, Python 3.15, dashboard)`; run 42227928443, push to main | "AssertionError: Tuples differ: ('', 'oversized') != ('', 'unstopped')" (subtest `cli='codex'`) | open | |
