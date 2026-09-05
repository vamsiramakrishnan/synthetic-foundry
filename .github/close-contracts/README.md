# Temporary integration workspace

The current editing environment cannot clone the repository over the network. Source edits are prepared against the supplied distribution, with modified baseline blobs checked against the live repository. Small patches in this directory are applied to the pinned PR head and tested in GitHub Actions before the implementation is committed.

This directory and its one-shot workflow must be removed after verification. CI must never relax a validator, rewrite golden fixtures, or silently move a branch that has changed since checkout.
