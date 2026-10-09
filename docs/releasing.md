# Maintaining and releasing rapidxmltodict

## One-time setup (repository/account settings)

The workflow files alone do **not** configure repository protection or authorize
PyPI uploads. Complete these settings before pushing a release tag.

### Require pull requests and passing tests

In GitHub Settings → Rules → Rulesets, create an **active branch ruleset**
targeting `main`:

- Require a pull request before merging.
- Require status check **CI passed**, expected source **GitHub Actions**.
- Require branches to be up to date before merging.
- Block force pushes and deletions.
- Leave bypass actors empty, including administrators, if direct pushes must
  always be prohibited. Administrators can still change repository settings.
- Do not require approving reviews for a sole-maintainer repository: an author
  cannot approve their own PR. Add one or more approvals when another maintainer
  is available. Requiring a PR does not require an approving review.

Run the initial PR CI once so **CI passed** appears in the check selector.
Do not select a matrix job name that changes with Python/platform additions.
The aggregate runs even when prerequisites fail or skip, and accepts only
`success` for every prerequisite. There are no path filters or draft-PR skips.
A GitHub merge queue is supported through `merge_group`.

### PyPI Trusted Publishing (no stored API token)

For a new project, sign into
[PyPI account publishing](https://pypi.org/manage/account/publishing/) and add a
**pending GitHub publisher** with these exact values:

| Field | Value |
| --- | --- |
| PyPI project name | `rapidxmltodict` |
| GitHub owner | `nazarkhanov` |
| Repository | `rapidxmltodict` |
| Workflow filename | `release.yml` |
| Environment name | `pypi` |

The filename is not the workflow display name and not the full path. The file
in the repository is `.github/workflows/release.yml`.
The publisher is a persistent grant to this workflow. An account owner must
explicitly authorize it. First successful upload creates the project and turns
the pending publisher into a regular publisher; pending configuration does
**not** reserve a PyPI project name.

Create a GitHub Actions environment named **pypi**. Set deployment branches/tags
to **Selected branches and tags**, then allow **Tags** matching `v*` only.
Do not choose “Protected branches only”: the release runs from a tag.
No manual reviewer is required for fully automatic publishing. Add a reviewer
only if deliberate approval on every release is desired.

Before enabling the publisher, restrict creation of release tags `v*` to
trusted release maintainers using a tag ruleset. Use a separate tag ruleset
to block updates and deletions without bypasses. This protects the release
workflow itself: the main-history check prevents accidental off-main releases,
but someone who can create arbitrary tags could tag a modified workflow that
removes that check. Review workflow changes as carefully as code.
See [PyPI's tag/security guidance](https://docs.pypi.org/trusted-publishers/security-model/).

Keep 2FA enabled on GitHub and PyPI and retain account recovery codes securely.
Never paste a PyPI token into this repository or its workflow.

Official references:
- [Create a project through OIDC](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
- [Use a Trusted Publisher](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
- [GitHub environment deployment restrictions](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

## Cut a release

1. Merge reviewed changes through a green PR into `main`.
2. Choose a new version that has never been uploaded to PyPI.
3. Fetch and fast-forward your local main, then create and push one annotated tag:

```sh
git switch main
git pull --ff-only origin main
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
```

Use `vX.Y.Z` (for example `v0.1.0`), or canonical PEP 440 prereleases
such as `v0.2.0a1`, `v0.2.0b1`, `v0.2.0rc1`; `.postN` releases
are also accepted. Leading zeros, local versions, dev tags, missing `v`,
and incomplete `v1.2` versions are rejected. Push one tag at a time.
A tag outside main history is rejected before project code executes.

The workflow derives metadata and `rapidxmltodict.__version__` from the tag
using setuptools-scm. It checks that the inferred version equals the tag,
repeats the full CI suite for that commit, builds and tests installed wheels,
checks the version/assets in every distribution, then publishes to PyPI.
Only after publication succeeds does it create the GitHub Release, with
categorized PR notes, contributor links, a full comparison link when available,
installation instructions, and the distributions as assets. Prereleases are
marked accordingly and never marked latest.

No source build or project code runs in the OIDC-enabled publishing job.
All third-party actions are pinned to immutable commit SHAs. The release job
alone receives GitHub contents-write permission. Ordinary PR builds are
read-only and have no publishing credentials.

## Versions in development and source distributions

Do not edit a version constant or commit the generated `_version.py`.
Use a full Git checkout for development builds. Untagged commits get development
versions; exact valid tags get release versions. Published source distributions
include generated version data and PKG-INFO, so they rebuild without Git.
GitHub's automatically generated source ZIPs are not supported as a substitute
for the tested PyPI source distribution.

The packaging check constructs temporary, local-only stable/prerelease Git
fixtures and verifies tag → sdist → Git-free wheel → installed runtime version.
It never pushes those tags or uploads a package.

## Release notes

Use descriptive PR titles; these become the user-facing changelog.
Before merging, apply appropriate repository labels:

- `breaking`: backwards-incompatible changes; include migration advice in PR text.
- `enhancement` or `feature`: new features.
- `bug` or `fix`: fixes.
- `documentation`: documentation.
- `dependencies` or `maintenance`: maintenance.
- `skip-changelog`: exclude purely internal noise.

Create missing labels in GitHub as needed. Unlabeled PRs appear under “Other
changes”. Categories are configured in `.github/release.yml`.
Generated notes summarize merged PR titles and links, not detailed migration
instructions; edit or augment release notes for breaking changes.

## Failures and recovery

- **Test/build/validation failure:** nothing is published. Fix through another
  PR; use a fresh version/tag. Do not move an already published release tag.
- **Publisher denied / project name unavailable:** check exact publisher fields,
  environment restrictions, and PyPI project ownership. Never fall back to
  committing a long-lived credential.
- **Transient publish failure with zero files uploaded:** rerun failed jobs of
  the same run while the seven-day artifacts remain available.
- **Partial PyPI upload:** existing files are intentionally not silently skipped.
  Compare uploaded file SHA-256 hashes with the original workflow artifacts,
  then have a maintainer upload only missing, verified original files or choose
  a new version. PyPI filenames cannot be replaced. Do not blindly rebuild and
  overwrite or enable `skip-existing`.
- **PyPI succeeded, GitHub Release failed:** rerun only the failed release job.
  Do not rerun a successful publisher just to regenerate notes. If the release
  already exists, the job verifies that it is published and every expected asset
  has a matching SHA-256. Missing/unverified assets cause an explicit failure;
  repair them using the original artifacts.
- GitHub Releases and PyPI are separate services; publication is not atomic.
  A PyPI release can exist while GitHub release creation is being retried.

## Further maintenance recommendations

- Enable Dependabot (weekly grouped GitHub Actions updates and Python dependency
  checks), then review and merge its PRs through the same CI.
- Keep a SECURITY.md with a private vulnerability-reporting route and a
  CONTRIBUTING.md explaining supported versions and tests.
- Schedule native sanitizers and fuzzing separately from quick PR checks; see
  `tests/SANITIZERS.md`. Re-run benchmarks for performance-sensitive changes.
- Python 3.9 support is retained for compatibility. Revisit end-of-life Python
  support in a clearly announced release; add newer runtimes/architectures only
  after their native wheels and tests pass.
- Consider TestPyPI as a separate explicitly configured publisher/environment
  for future release rehearsals. The current PR runs all builds without upload.

These recommendations do not imply the corresponding account settings or
scheduled tasks have already been enabled.
