# Identity-pinned certificates

`hellgate_v1.json.zlib` is a deterministic compressed JSON certificate produced by
`tools/hellgate_generate.py`. The plugin never trusts the producer: startup loads the
compressed bytes through the plugin identity inventory, decompresses them under a hard
size bound, and passes the raw JSON to the independent exact-rational checker in
`mcp/hellgate_verify.py`.

Acceptance is `status=bounded`, not `formal-bounded`. In addition to the Barta
eigenvalue enclosure, the checker returns exact-rational bounded diagnostics for
the normalized certificate trial `phi`. Those moments and residuals are not
ground-state quantities. A separately labelled lambda-strong-convexity transfer
encloses only the true ground-state quartic norm and energy functional. The
checker states the comparison and transfer assumptions plus their residual
non-claims in the returned result.
