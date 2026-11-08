# Artifactum · `atfm`

[atfm.io](https://atfm.io) · `pip install artifactum` · `import artifactum as atfm` · the `atfm` command

A registry and lineage tracker for the files data teams produce: datasets, models, results and figures.

Every file you publish gets a permanent ID, and Artifactum records where it came from: the artifacts your
code read, the git commit and code that ran, and who published it. Files stay in your own Google Cloud
Storage bucket; Artifactum stores only metadata.

## Install

```bash
pip install artifactum
artifactum init
```

`init` asks for your API token (from Settings at [atfm.io](https://atfm.io)), your server URL (`https://atfm.io`
unless your team runs its own) and your GCS bucket. `atfm` is the short name for the same command:
`atfm init`, `atfm search`, and so on.

## Use

```python
import artifactum as atfm
import pandas as pd

events = pd.read_parquet(atfm.artifact("C4LN9E2A"))  # fetched and cached locally
features = build_features(events)
features.to_parquet("features.parquet")

atfm.publish(
    "features.parquet",
    description="Feature matrix, nulls dropped",
    tags=["features"],
)
# C4LN9E2A is recorded as the parent automatically, along with the git commit and code.
```

From the shell (bash, R, Nextflow, Snakemake, ...):

```bash
eval "$(atfm run start 'align reads')"      # lineage is recorded across the commands below
bwa mem "$(atfm get GRCH38RF)" "$(atfm get FQ7R1A2B)" > aligned.sam
atfm publish aligned.bam -d "Reads aligned with BWA-MEM" --code align.sh
eval "$(atfm run end)"
```

`atfm get` prints a local path and `atfm publish` prints the new ID, so both compose with other
commands. Use `--parent ID` to set parents explicitly.

Browsing from the terminal:

```bash
artifactum log K9PWQM7T      # upstream lineage
artifactum browse            # interactive browser
atfm log K9PWQM7T            # `atfm` is a short alias for `artifactum`
```
