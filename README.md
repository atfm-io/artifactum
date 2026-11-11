# Artifactum · `atfm`

[atfm.io](https://atfm.io) · `pip install artifactum` · `import artifactum as atfm` · the `atfm` command

A registry and lineage tracker for the files data teams produce: datasets, models, results and figures.

Every file you publish gets a permanent ID, and Artifactum records where it came from: the artifacts your
code read, the git commit and code that ran, and who published it. Files stay in storage your team
controls, a shared directory or a Google Cloud Storage bucket; Artifactum stores only metadata.

## Install

```bash
pip install artifactum
atfm init
```

`init` asks for your API token (from Settings at [atfm.io](https://atfm.io)), your server URL (`https://atfm.io`
unless your team runs its own) and where to store files. Or give them and skip the questions:

```bash
atfm init --token atfm_... --storage ~/atfm-files
```

## Storage

Artifactum never holds your files. Each one is copied to your team's storage when it's published and
fetched from there when someone reads it, then cached locally.

| Storage | Location to give `init` | Install |
| --- | --- | --- |
| A shared directory (lab server, cluster, network drive) | `/groups/lab/atfm` | `pip install artifactum` |
| Google Cloud Storage | `gs://my-team-bucket/atfm` | `pip install 'artifactum[gcs]'` |

A shared directory needs no cloud account: everyone on the team just needs to reach it **at the same
path**, since the registry records where each file is. Files are stored by content, under
`<location>/<hash[:2]>/<hash>/<filename>`, and never overwritten.

For Google Cloud Storage, each person signs in once with `gcloud auth application-default login` and needs
read and write access to the bucket.

To try Artifactum on your own, a folder like `~/atfm-files` is enough. When you bring in your team, move
what you've published to shared storage; the files are copied, checked against their hashes and their
records updated, and the old copies are left in place:

```bash
atfm storage move /groups/lab/atfm      # or gs://my-team-bucket/atfm
```

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

Add `--json` to `get`, `publish`, `describe`, `log` or `run status` to get one JSON object on stdout
instead, for tools that parse rather than split strings. Messages and errors stay on stderr, and a
failure exits non-zero.

```bash
$ atfm get C4LN9E2A --json
{"id": "C4LN9E2A", "path": "/home/me/.artifactum/cache/3f9a..."}
$ atfm publish model.rds -p C4LN9E2A --json
{"id": "M0DL3V3X", "file": "/home/me/project/model.rds", "parents": ["C4LN9E2A"], "run_id": null}
```

From R, call the command and read its JSON with `jsonlite`:

```r
atfm <- function(...) {
  out <- system2("atfm", c(..., "--json"), stdout = TRUE)
  if (!is.null(attr(out, "status"))) stop("atfm failed")
  jsonlite::fromJSON(paste(out, collapse = ""))
}

counts <- read.csv(atfm("get", "C4LN9E2A")$path)
saveRDS(fit, "model.rds")
atfm("publish", "model.rds", "-p", "C4LN9E2A", "-d", shQuote("GLM on cleaned counts"))$id
```

There's no R package yet. If you'd like one, email hello@atfm.io.

Browsing from the terminal:

```bash
atfm log K9PWQM7T      # upstream lineage
atfm browse            # interactive browser (preview: recent artifacts, no search yet)
```
