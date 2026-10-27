# Releasing PICdb-MEDS

A release is a git tag. The package version comes from the tag (setuptools-scm), so there is
no version number to edit in `pyproject.toml`: pushing tag `0.0.3` builds `PICdb-MEDS 0.0.3`,
publishes it to PyPI and creates the GitHub release. The same version is stamped into every
MEDS output as `metadata/dataset.json` `dataset_version` = `<PIC release>:<package version>`
(e.g. `1.1.0:0.0.3`).

## Choosing the version ("bumping")

Bumping means choosing the next tag. Tags are plain [SemVer](https://semver.org) numbers
without a `v` prefix (`0.0.3`, not `v0.0.3`), which keeps them identical to the PyPI version.

| Change since the last release                                                                    | Bump  | Example         |
| ------------------------------------------------------------------------------------------------ | ----- | --------------- |
| Docs, CI, packaging, or a fix that leaves every code and its meaning unchanged                   | patch | `0.0.3 → 0.0.4` |
| Output changes: new or renamed codes, events moved in time, values parsed differently            | minor | `0.0.4 → 0.1.0` |
| `1.0.0` once the code vocabulary is stable; afterwards, any change that breaks downstream models | major | `0.4.0 → 1.0.0` |

Before `1.0.0`, a minor bump is how to flag an output change that would break a model trained
on the previous output.

The PIC data release is versioned separately, as `sources.dataset_version` in
[`src/PICdb_MEDS/event_configs.yaml`](src/PICdb_MEDS/event_configs.yaml). Change it only when
the spec targets a new PhysioNet release, and release the package with at least a minor bump.

A version number is used once. `0.0.2` was tagged and archived on GitHub and Zenodo but never
reached PyPI, so the next release is `0.0.3`.

To see the last release and what the current commit would build as:

```bash
git describe --tags --abbrev=0                      # last release tag
uvx --from setuptools-scm python -m setuptools_scm  # e.g. 0.0.4.dev2+g7a28785
```

## One-time setup

The publish job uses PyPI [trusted publishing](https://docs.pypi.org/trusted-publishers/)
through the `pypi` environment, so no API token is stored in GitHub. It is already set up:
PICdb-MEDS 0.0.1 was published this way. If the workflow file or environment is ever renamed,
update the trusted publisher under the project's *Publishing* settings on PyPI to match.

## Releasing

1. Make sure `main` holds everything to release and its checks are green (Tests, Synthetic
    ETL, Code Quality Main).

2. Update [`CITATION.cff`](CITATION.cff) for the new version and merge it to `main`: `version`,
    `date-released`, and the tag in `repository-code`
    (`https://github.com/rvandewater/PICdb_MEDS/tree/<version>`). This is the only file that
    names the version.

3. Tag the release commit on `main` and push the tag:

    ```bash
    git switch main && git pull --ff-only
    git tag -a 0.0.3 -m "PICdb-MEDS 0.0.3"
    git push origin 0.0.3
    ```

    Do not create the GitHub release by hand; the workflow creates it and fails if it already
    exists.

4. The tag push runs [`python-build.yaml`](.github/workflows/python-build.yaml). Follow it
    with `gh run watch`. It:

    - builds the wheel and sdist from the full git history;
    - fails unless the wheel's version is exactly the tag (so a dev version can never be
        published);
    - publishes to PyPI;
    - signs the dists with Sigstore and attaches them to a new GitHub release named after the
        tag, which Zenodo archives with a DOI.

5. Check the result:

    ```bash
    uv run --no-project --with PICdb-MEDS==0.0.3 python -c \
        "import importlib.resources as r; print(r.files('PICdb_MEDS').joinpath('event_configs.yaml').is_file())"
    ```

    It must print `True`: a wheel without the spec cannot run `meds-extract-run spec=PICdb`.

## When something goes wrong

- **The build fails on a tag push** (e.g. the version check): nothing was published, because
    PyPI upload and the GitHub release only run after a successful build. Delete the tag, fix
    `main`, and tag again:

    ```bash
    git push --delete origin 0.0.3 && git tag -d 0.0.3
    ```

    Only do this if no GitHub release exists for the tag; once one does, Zenodo has archived
    it, so release the fix under the next patch number instead.

- **PyPI rejects the upload** with `invalid-publisher`: the trusted publisher on PyPI no longer
    matches the repository, workflow file name or environment. Fix it on PyPI and re-run the
    failed job; the tag can stay.

- **A wrong release was published**: PyPI never accepts the same version twice, even after
    deleting it. Leave the tag in place, release the fix as the next patch, and if needed
    [yank](https://pypi.org/help/#yanked) the bad version on PyPI.

Never move or re-create a tag that reached PyPI or a GitHub release.
