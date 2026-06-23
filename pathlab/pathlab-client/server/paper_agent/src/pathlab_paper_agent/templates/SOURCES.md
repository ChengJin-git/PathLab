# Official Template Sources

Downloaded on 2026-05-04 for the M4 template renderer worktree and refreshed on 2026-05-05 for the Scientific Reports Overleaf template migration.

- MICCAI / LNCS assets (`llncs.cls`, `splncs04.bst`) come from Springer's official LNCS LaTeX2e proceedings template package: https://resource-cms.springernature.com/springer-cms/rest/v1/content/19238648/data/v8
- Nature Scientific Reports now follows the Overleaf Scientific Reports template source (`\documentclass[fleqn,10pt]{wlscirep}`): https://www.overleaf.com/latex/templates/template-for-submissions-to-scientific-reports/xyrztqvdccns
- The bundled `wlscirep.cls` asset was downloaded from an Overleaf-template mirror of the `wlscirep` class: https://raw.githubusercontent.com/SFICSSS16-CircularEconomy/Documents/master/wlscirep.cls
- The bundled `naturemag.bst` asset was downloaded from CTAN because `wlscirep.cls` declares `\bibliographystyle{naturemag}`: https://mirrors.ctan.org/macros/latex/contrib/nature/naturemag.bst

The renderer keeps these assets in the per-template final directories and export bundles so each generated ZIP is dependency-closed without relying on a host TeX installation beyond standard packages.
