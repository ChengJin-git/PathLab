# GitHub capability synchronization

Skill and connector definitions can attach a public HTTPS GitHub repository, tree,
blob or raw URL. Built-in imported skills derive their original repository, path
and commit from the bundled source lock. Skill frontmatter may specify
`source_url`, `repository` or `homepage`; arbitrary links in instructions are not
treated as the skill's own source.

`POST /capabilities/{id}/sync-github` accepts `revision` and optional `source_url`.
The owner or administrator may synchronize; built-ins require an administrator.
The fetch resolves the tracked branch to a commit, downloads and validates an
archive, selects one entrypoint and atomically publishes the complete resource
package. Revision is checked before and after network I/O, so intervening edits
are preserved. Files aren't executed during import. Existing research snapshots
remain fixed; subsequent Chat loads and research snapshots use the new package.

Connector sync stores source revision/description/license and artwork. Its MCP
endpoint, private credentials, activation and verified tools remain unchanged.
Changing the endpoint through ordinary editing still requires reconnection.

Logo discovery prefers the selected skill's PNG/SVG assets, then repository assets
and explicit relative README logo references. Images are bounded, raster images
are re-encoded, and SVGs reject active elements, declarations and external references.
Files are content-addressed and served by an authenticated endpoint. Source and
license are visible in the library. Missing logos use locally bundled Lucide
ISC/MIT SVGs selected by function. No third-party tracking image requests are made
by the browser.

All metadata uses existing `CapabilityEntry.config`; no schema migration or
startup backfill is required. File edits preserve source and artwork metadata.
