# Billing Endpoints

Use this only when working with OpenAI API usage/cost questions.

- Runtime inference key and billing/admin key are different concerns.
  The backend runtime secret file is `/home/dima/secure-secrets/llm.env`. Assume it contains a working `OPENAI_ADMIN_KEY` when this doc is relevant.
- Use the admin key only for organization/admin endpoints.
  Admin keys work for `/v1/organization/...` endpoints and are not valid for normal inference endpoints like `/v1/models`.
- For exact dollars, prefer `GET /v1/organization/costs`.
  This reconciles to billing better than inferring cost from tokens.
- Useful endpoints:
  - `GET /v1/organization/costs`
  - `GET /v1/organization/usage/completions`
- Always pass a bounded time range.
  Use `start_time`, and when investigating a specific day also pass `end_time`.
- For this project, day buckets are usually enough.
  `bucket_width=1d`
- The pagination cursor is not `page`.
  Use the returned `next_page` value as `after=...` or `cursor=...`. Using `page=...` returns `400 invalid page token`.
- The costs endpoint can usually be fetched in one page for short ranges.
  Try `limit=100` first before writing a paging loop.
- Large usage exports can hit `429`.
  If you need many pages, add backoff and keep the query narrow.
- Public pricing pages may not match the account's actual billed rates/snapshot pricing.
  If exact cost matters, trust the `costs` endpoint over any manual token x price estimate.
- Project/app DB state is not a billing ledger.
  Local lesson/session message history includes client-generated messages and must not be treated as authoritative OpenAI request counts.
- Backend OpenAI calls log one `openai_response_usage` JSON line per successful Responses API call.
  These logs intentionally avoid prompt/message text and include request type, lesson ID, model, cache key/options,
  elapsed time, ordinary/cache-read/cache-write token counts and ratios, effective input cost, net cache savings, request/input/schema hashes, and per-section character counts plus hash-only prefix fingerprints.
- The backend also persists successful OpenAI Responses API usage to `openai_usage_events` for the admin dashboard.
  Enable the dashboard by setting `SVENSKA_USAGE_DASHBOARD_TOKEN`; then visit `/admin/usage?token=...`.
  On the VM, Caddy serves the dashboard hostname at `https://jahausage.dima-ib.xyz:8443/admin/usage?token=...` and proxies it to the same backend on `127.0.0.1:8100`.
- Per-user dashboard cost is estimated from recorded tokens. Configure rates with `OPENAI_USAGE_PRICE_OVERRIDES_JSON`, for example:
  `{"gpt-5.6-sol":{"input_per_million":5,"cached_input_per_million":0.5,"cache_write_per_million":6.25,"output_per_million":30},"gpt-5.6-terra":{"input_per_million":2,"cached_input_per_million":0.2,"cache_write_per_million":2.5,"output_per_million":12}}`.
  For GPT-5.6, `cache_write_per_million` defaults to 1.25 times the configured normal input rate if omitted.
  Keep these values aligned with current account pricing.
  The dashboard matches pricing by the model string recorded on each request; it does not infer pricing from role names or config defaults.
  If any role changes to a model that is missing from this JSON, usage tokens still persist but estimated per-user dollars for those requests will be zero/blank until the new model's rates are added and the backend is restarted.
- Dashboard "OpenAI Actual" is an organization-level total from `/v1/organization/costs` when `OPENAI_ADMIN_KEY` is configured.
  OpenAI billing data is not attributed to app users, so per-user actual cost remains unavailable unless a future API adds that dimension.
