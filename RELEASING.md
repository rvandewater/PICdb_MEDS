# Releasing PICdb-MEDS

The version lives in `pyproject.toml` and always holds the **last released** version. A release
bumps it with `uv version --bump`, commits the bump together with the updated
[`CITATION.cff`](CITATION.cff), and tags that commit with the version it was just bumped to.
The tag is read back from `pyproject.toml`, never typed, so it cannot name the wrong version;
the publish workflow also refuses any tag that differs from `pyproject.toml` or from the
version in `CITATION.cff`. Pushing the tag publishes to PyPI and creates the GitHub release,
which Zenodo archives with a DOI.

The version is stamped into every MEDS output as `metadata/dataset.json` `dataset_version` =
`<PIC release>:<package version>` (e.g. `1.1.0:0.0.3`).

## Choosing the bump

Tags are plain [SemVer](https://semver.org) numbers without a `v` prefix (`0.0.3`, not
`v0.0.3`), identical to the PyPI version.

| Change since the last release                                                                    | Bump    | Example         |
| ------------------------------------------------------------------------------------------------ | ------- | --------------- |
| Docs, CI, packaging, or a fix that leaves every code and its meaning unchanged                   | `patch` | `0.0.3 → 0.0.4` |
| Output changes: new or renamed codes, events moved in time, values parsed differently            | `minor` | `0.0.4 → 0.1.0` |
| `1.0.0` once the code vocabulary is stable; afterwards, any change that breaks downstream models | `major` | `0.4.0 → 1.0.0` |

Before `1.0.0`, a minor bump is how to flag an output change that would break a model trained
on the previous output. Preview a bump without changing anything with
`uv version --bump patch --dry-run`.

A version number is used once. `0.0.2` was tagged and archived on GitHub and Zenodo but never
reached PyPI, so `pyproject.toml` holds `0.0.2` and the next patch bump releases `0.0.3`.

The PIC data release is versioned separately, as `sources.dataset_version` in
[`src/PICdb_MEDS/event_configs.yaml`](src/PICdb_MEDS/event_configs.yaml). Change it only when
the spec targets a new PhysioNet release, and release the package with at least a minor bump.

## One-time setup

The publish job uses PyPI [trusted publishing](https://docs.pypi.org/trusted-publishers/)
through the `pypi` environment, so no API token is stored in GitHub. It is already set up:
PICdb-MEDS 0.0.1 was published this way. If the workflow file or environment is ever renamed,
update the trusted publisher under the project's *Publishing* settings on PyPI to match.

## Releasing

1. Start from an up-to-date, clean `main` whose checks are green (Tests, Synthetic ETL, Code
    Quality Main):

    ```bash
    git switch main && git pull --ff-only && git status --short # must print nothing
    ```

2. Bump, update the citation, test, build, commit, tag and push. Use `patch`, `minor` or
    `major` as chosen above:

    ```bash
    uv version --bump patch
    VERSION=$(uv version --short)
    perl -pi -e "s/^version: .*/version: $VERSION/; s/^date-released: .*/date-released: '$(date +%F)'/; s|(repository-code: .*/tree/).*|\${1}$VERSION|" CITATION.cff
    uv run pytest
    uv build --clear
    git add pyproject.toml uv.lock CITATION.cff
    git commit -m "Release $VERSION"
    git tag -a "$VERSION" -m "Release $VERSION"
    git push origin main "$VERSION"
    ```

    The `perl` line sets `version`, `date-released` and the tag in `repository-code`; check it
    with `git diff CITATION.cff` before committing.

    If `pytest` or `uv build` fails, stop: nothing is committed yet. Undo the bump with
    `git checkout pyproject.toml uv.lock CITATION.cff`, fix the problem on `main`, and start
    again.

    Do not create the GitHub release by hand; the workflow creates it and fails if it already
    exists.

3. The tag push runs [`python-build.yaml`](.github/workflows/python-build.yaml). Follow it
    with `gh run watch`. It:

    - fails unless the tag equals the `pyproject.toml` version and `CITATION.cff` cites it;
    - builds the wheel and sdist and publishes them to PyPI;
    - signs the dists with Sigstore and attaches them to a new GitHub release named after the
        tag.

4. Check the result:

    ```bash
    uv run --no-project --with PICdb-MEDS==$VERSION python -c \
    	"import importlib.resources as r; print(r.files('PICdb_MEDS').joinpath('event_configs.yaml').is_file())"
    ```

    It must print `True`: a wheel without the spec cannot run `meds-extract-run spec=PICdb`.

## When something goes wrong

- **The workflow fails on the tag push** (e.g. the tag check): nothing was published, because
    the PyPI upload and the GitHub release only run after a successful build. Delete the tag,
    fix `main`, and release again; the next bump skips the failed number, which is fine:

    ```bash
    git push --delete origin "$VERSION" && git tag -d "$VERSION"
    ```

    Only do this if no GitHub release exists for the tag; once one does, Zenodo has archived
    it, so leave the tag and release the fix under the next number.

- **PyPI rejects the upload** with `invalid-publisher`: the trusted publisher on PyPI no longer
    matches the repository, workflow file name or environment. Fix it on PyPI and re-run the
    failed job; the tag can stay.

- **A wrong release was published**: PyPI never accepts the same version twice, even after
    deleting it. Leave the tag in place, release the fix as the next patch, and if needed
    [yank](https://pypi.org/help/#yanked) the bad version on PyPI.

Never move or re-create a tag that reached PyPI or a GitHub release.
