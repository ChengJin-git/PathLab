# Paper Generation Gateway Bridge

This package is intentionally a thin compatibility bridge for the front-end
`/papers` API. The Paper Agent implementation, uv environment, docs, tests,
templates, and research notes now live under:

```text
pathlab/pathlab-client/server/paper_agent/
```

Gateway keeps this package only so existing imports such as
`gateway.paper_generation.routes` and the mounted `/papers` routes remain stable.
Do not add agent implementation here; put new code under `server/paper_agent/`.
