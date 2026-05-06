# PathLab Paper Generation — LaTeX compile sandbox.
#
# Used by the paper-generation pipeline to compile MICCAI / Nature SR papers
# without polluting the main PathLab container or host. See
# `pathlab/pathlab-client/server/paper_agent/docs/plan/paper_generation_agent_design.md` §6 and §10 M1.
#
# Build:
#   docker build -t pathlab/paper-latex:latest pathlab/pathlab-client/server/paper_agent/docker/paper-latex/
#
# Hello-world smoke test:
#   docker run --rm pathlab/paper-latex:latest hello
#
# Real compile (paths inside the container):
#   docker run --rm \
#       -v /host/path/to/paper_id:/work \
#       pathlab/paper-latex:latest \
#       compile miccai
#
# The `texlive/texlive:latest` image is large (~5 GB) but contains every
# package MICCAI / Nature SR needs out of the box. Pinning a date tag is
# advised once the system is in production.

FROM texlive/texlive:latest

# `latexmk` is already in the base image; we install only what we add.
# `qpdf` is used for ZIP bundle dry-run validation in M12.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        qpdf \
    && rm -rf /var/lib/apt/lists/*

# The upstream texlive image already ships a non-root `texlive` user/group with
# uid/gid 1000. Reuse it instead of creating our own user; otherwise builds fail
# with "GID '1000' already exists" on current texlive images.

WORKDIR /work
COPY --chown=texlive:texlive compile.sh /usr/local/bin/compile.sh
RUN chmod +x /usr/local/bin/compile.sh

USER texlive
ENTRYPOINT ["/usr/local/bin/compile.sh"]
CMD ["hello"]
