# Commits and PRs

The contribution rules every change to chisel-releases follows. The authority is
the repo's own [CONTRIBUTING.md](https://github.com/canonical/chisel-releases/blob/main/CONTRIBUTING.md);
this is the part that comes up on every change.

## Commit messages

[Conventional commits](https://www.conventionalcommits.org/en/v1.0.0/):
`feat:`, `fix:`, `test:`, `ci:`, `chore:`, `docs:`, `refactor:`.

- subject lowercase, imperative, <= 50 chars, no trailing period
- body wrapped at 72
- one category per commit -- the SDF lands as `feat:`, its spread test as `test:`

## PRs

- **Branch off the target release branch**, never `main`. A PR into `main` is wrong.
- **One cohesive change per PR.** Do not mix unrelated slice definitions.
- **Two maintainer approvals**, CLA signed, and green CI before review.
- **No force-push** once review comments exist.
