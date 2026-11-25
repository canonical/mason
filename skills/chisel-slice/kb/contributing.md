# Contributing to chisel-releases

Upstream's [CONTRIBUTING.md](https://github.com/canonical/chisel-releases/blob/main/CONTRIBUTING.md) is the authority: its
[Commit Conventions](https://github.com/canonical/chisel-releases/blob/main/CONTRIBUTING.md#commit-conventions) and
[Pull Request Etiquette](https://github.com/canonical/chisel-releases/blob/main/CONTRIBUTING.md#pull-request-etiquette) sections cover commit
messages and PRs. It lives on `main`; release branches carry no copy.

What it does not say, from the release branches' own history:

- The commit scope is usually the release -- `feat(26.04): add tomcat11 slices`,
  `fix(24.04): base-files as essential of apparmor package` -- and sometimes left out.
- The `(#NNNN)` suffix on subjects comes from the squash merge, not from the author.
