# Changelog

## [0.2.2](https://github.com/atfm-io/artifactum/compare/v0.2.1...v0.2.2) (2026-11-13)


### Documentation

* badges for PyPI, Python versions, downloads, tests, coverage and license ([129f20e](https://github.com/atfm-io/artifactum/commit/129f20e321ede3eec975193cab1871bac2d34fe2))
* downloads badge from shields.io, which renders before the counts exist ([6232ecd](https://github.com/atfm-io/artifactum/commit/6232ecd193f308c4f16108bae8f9fe4d485e2ca4))
* shorter Python badge (&gt;= 3.10, from requires-python) ([bcd0f45](https://github.com/atfm-io/artifactum/commit/bcd0f452ffad65b1b00296fc9b82b80c558ecd8d))

## [0.2.1](https://github.com/atfm-io/artifactum/compare/v0.2.0...v0.2.1) (2026-11-13)


### Documentation

* mention the atfm placeholder package ([aedfe83](https://github.com/atfm-io/artifactum/commit/aedfe83576a87ad98c5cb9e6328bf41dfac8edde))
* say why the atfm placeholder exists ([c0ffe19](https://github.com/atfm-io/artifactum/commit/c0ffe193d8f98990f313a00621ac766fb419e6de))

## [0.2.0](https://github.com/atfm-io/artifactum/compare/v0.1.0...v0.2.0) (2026-11-13)


### ⚠ BREAKING CHANGES

* **storage:** google-cloud-storage is no longer installed by default. Install `artifactum[gcs]` to keep storing files in a bucket.
* **cli:** the `artifactum` console script no longer exists. Run `atfm` instead.

### Features

* **cli:** add --json output to get, publish, describe, log and run status ([16f97aa](https://github.com/atfm-io/artifactum/commit/16f97aafbcdca2c34815cc49d9502ff3e3abe431))
* **cli:** atfm --version ([5f16856](https://github.com/atfm-io/artifactum/commit/5f1685657061c83e92da738cc2e650a3f191d932))
* **cli:** atfm init --token --storage, and atfm storage move ([6aecb95](https://github.com/atfm-io/artifactum/commit/6aecb95afca1c751ee88f04a0ed960358af57f98))
* **cli:** label the terminal browser as a preview ([b6a9940](https://github.com/atfm-io/artifactum/commit/b6a99403ec090edb2dbf34d98653b6a0a4e32e13))
* **cli:** the command is atfm only ([0777167](https://github.com/atfm-io/artifactum/commit/0777167210378998a1f46601a87ba8f7fd31f982))
* **storage:** store files in a shared directory, or a GCS bucket ([3db014f](https://github.com/atfm-io/artifactum/commit/3db014fc0d89c4ba53ca7fa1480b9c6517eeff32))
* support Python 3.10 ([070f6c4](https://github.com/atfm-io/artifactum/commit/070f6c4e69ec3756777a5debcb1d1f1223684e12))


### Bug Fixes

* accept artifact IDs in lowercase ([be79ec2](https://github.com/atfm-io/artifactum/commit/be79ec2a4a103d5b43c7ba0416abb0073dfb2595))
* **cli:** clear errors instead of tracebacks, and other fixes found by new tests ([fd3fe10](https://github.com/atfm-io/artifactum/commit/fd3fe1085535fb724740d6ba312c91d92a4ff1b6))
* **cli:** no hint about parents on the first publish ([451b737](https://github.com/atfm-io/artifactum/commit/451b737cd02f12b36aea031e25345de404d09e3d))


### Documentation

* MIT license ([7ad2ce5](https://github.com/atfm-io/artifactum/commit/7ad2ce50729fba95843b57b8546e01542d3316c4))
* README no longer mentions an atfm search command ([2d9b86e](https://github.com/atfm-io/artifactum/commit/2d9b86e2aa1a97ee47ef54a4c9872265d51fd946))
