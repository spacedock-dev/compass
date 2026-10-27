# GitLab merge request read: what is not measured

**Synthetic, not captured.** No real GitLab merge request, `glab` install or GitLab server stood
behind the GitLab half of the pull request CI read. It was built from GitLab's documented REST
shapes and tested against a stub `glab` that answers those shapes. Nothing below is a measurement.
This note exists so that the gap is written down and a later capture can replace it.

## What Claude Code writes for a merge request

Whether Claude Code writes a `pr-link` transcript record, or a `toolUseResult.gitOperation.push`
record, when a session opens or updates a GitLab merge request is **unmeasured**. The GitHub read
binds from those records when their repository matches the session folder's own `origin`
([the synthetic GitHub shapes](pr-link-and-push-shapes-synthetic.jsonl) are themselves unmeasured
for a push). For GitLab no record binds anything. Only a merge request URL in the goal binds one:
`https://HOST/GROUP/.../PROJECT/-/merge_requests/N`, where `HOST` is a dotted name and not an IP
literal, and `GROUP/.../PROJECT` is one to twenty path segments below the host.

## What the read assumes about `glab`

Each of these is taken from GitLab's public API documentation or from `glab`'s own help, and none
was run here:

- `glab api ENDPOINT --hostname HOST --method GET` makes one authenticated GET with the login `glab`
  stored for that host, and prints the response body. On an HTTP error it exits non-zero and the
  body holds the refusal. The read classifies a non-zero exit and never parses that body as data.
- `GET projects/:path/merge_requests/:iid` answers an object with `iid`, `sha` (the source branch's
  head commit) and `head_pipeline`, which is `null` or an object with `id` and `status`.
- `GET projects/:path/pipelines/:id/jobs?per_page=100&page=N` answers an array of jobs with `name`,
  `status`, `allow_failure` and `finished_at`. Retried jobs are left out by default.
- A pipeline status and a job status come from a closed set: `created`, `waiting_for_resource`,
  `preparing`, `pending`, `running`, `success`, `failed`, `canceling`, `canceled`, `skipped`,
  `manual`, `scheduled`, and `waiting_for_callback` for a job. Anything outside the set makes the
  read unreadable and never a pass.
- `glab`'s configuration is `glab-cli/config.yml` under `XDG_CONFIG_HOME`, else `~/.config`, with a
  `hosts:` mapping whose keys are host names. Only those keys are read; the values hold tokens and
  are never kept. Where this build reads the file differently from `glab`, for example a
  `GLAB_CONFIG_DIR` the reader set, the child does not see that variable either, so both use the
  default location.
- A merged-results pipeline carries a merge commit as its own `sha`. The read compares the merge
  request's `sha`, not the pipeline's, so it still matches the session's commit.
- A trigger job's child pipeline is not a job of the parent. A parent whose own status disagrees
  with its jobs is listed as one check named `pipeline`.

## What a capture would settle

On a throwaway GitLab project, record with the recorder under `docs/captures/`: the transcript
records a Claude Code session writes after `glab mr create` and after a push to an existing merge
request; the three `glab api` response shapes above with every value removed; the exit status and
body of a 401, 404 and 429; and the keys of `glab`'s `config.yml` after `glab auth login` on a
self-managed host. Field names, value types and the harness's fixed words only.
