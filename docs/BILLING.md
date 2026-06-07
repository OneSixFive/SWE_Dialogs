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
