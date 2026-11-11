# Contributing

## Development

The development environment is defined in `pyproject.toml` (the `[tool.pixi.*]` tables):

```bash
pixi run test   # runs the tests and prints a coverage report
pixi run fmt    # formats the code and fixes what ruff can fix
pixi run lint   # what CI checks: formatting and lint, without changing anything
pixi run install-hooks   # once per clone: ruff then runs on every commit
```

Without pixi: `pip install -e ".[dev]"`, then `pytest`, `ruff format` and `ruff check`.
Style settings are in `[tool.ruff]` in `pyproject.toml`.

## Commit messages

Every commit on `main` follows [Conventional Commits](https://www.conventionalcommits.org/).
Releases are cut from these messages by [release-please](https://github.com/googleapis/release-please),
so a commit that doesn't follow the format is left out of the changelog.

```
<type>(<optional scope>): <summary in the imperative>

<optional body>

<optional footers, e.g. BREAKING CHANGE: ...>
```

| Type | Use for | In the changelog | Version bump |
| --- | --- | --- | --- |
| `feat` | a new feature | Features | minor |
| `fix` | a bug fix | Bug Fixes | patch |
| `perf` | a performance improvement | Performance | patch |
| `docs` | documentation only | Documentation | patch |
| `deps` | dependency updates | Dependencies | patch |
| `refactor`, `test`, `build`, `ci`, `chore`, `style` | everything else | hidden | none |

A `!` after the type (`feat!: ...`) or a `BREAKING CHANGE:` footer marks a breaking change.
While the version is below 1.0, breaking changes bump the minor version.

Pull requests are squash-merged, so the PR title becomes the commit message and must
follow the same format.

## Releases

release-please keeps a release PR open that collects unreleased changes, bumps the
version in `pyproject.toml` and updates `CHANGELOG.md`. Merging that PR tags the release
(`vX.Y.Z`), publishes a GitHub release with the built files attached, and uploads the
package to PyPI.
