Use the chisel-slicer skill to author chisel package slices files for these packages on the `ubuntu-26.04` branch: freeipmi-common, libfreeipmi17, ipmitool.

You are in a checkout of canonical/chisel-releases (your current directory). These slices do not exist yet -- create `slices/<package>.yaml` for each of the three packages. Follow the skill's workflow and the conventions in its knowledge base, including any inter-package dependencies between them.

This is an automated eval: work autonomously, do not ask questions, and do not open a PR. Produce the slices files and the spread tests the workflow asks for, then stop.

Network access goes through a filtering proxy. A refused request (a 403, or a refused connection) is final: carry on with what you can reach, and do not retry it through mirrors, other hosts or rewritten URLs.
