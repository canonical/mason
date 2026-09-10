# Port libestr0 to 26.04

`libestr0` is sliced on the `ubuntu-24.04` branch of chisel-releases but not on `ubuntu-26.04`, and a downstream image on 26.04 needs it. Port it.

A checkout of `canonical/chisel-releases` is already at `./chisel-releases` in your working directory, with both `ubuntu-24.04` and `ubuntu-26.04` present as local branches and `ubuntu-26.04` checked out. Work inside that directory -- nothing written outside it can be seen.

Do not open a pull request.
