# atfm

This is a placeholder. Artifactum's command is `atfm`, so `pip install atfm` is an easy thing
to type by mistake. We hold this name to stop squatting attacks: without it, anyone could
publish a package called `atfm`, including malicious code, and catch people who meant to
install Artifactum.

It has no code of its own. Installing it installs [artifactum](https://pypi.org/project/artifactum/),
which provides the `atfm` command and `import artifactum as atfm`. Install that directly:

```bash
pip install artifactum
```

See [atfm.io](https://atfm.io) and [the repository](https://github.com/atfm-io/artifactum).
