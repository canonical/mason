# skill naming

How mason's skills are named. The rules are not specific to rocks or chisel;
they hold for any product or tool a future skill targets.

## rules

1. **Format**: `^[a-z0-9]+(-[a-z0-9]+)*$`, at most 64 characters, and the
   skill's directory name equals its `name` (the
   [Agent Skills spec](https://agentskills.io/specification)).
2. **Pattern `<domain>-<subject>-<action>`**, 2-3 words, about 25 characters
   or fewer.
   - **domain**: the product or tool the skill is about (`rock`, `chisel`).
     Skills of one domain group together when typing `/<domain>-`.
   - **subject**: what the skill works on. Leave it out when it would repeat
     the domain (`rock-debug`).
   - **action**: what the skill does. Keep it whenever the name would be
     unclear without it (`rock-sbom-generate`, not `rock-sbom`).
3. **Use the domain's own words**: take the action from the product's CLI or
   docs.
4. **Name the job, not a tool or a single command**: avoid names that read as
   the tool (`rock-craft` vs `rockcraft`) or as one CLI step when the skill
   does several (`rock-pack`).
5. **No `-er` agent nouns, gerunds, invented names or bare generic words**
   (`review`, `debug`, `verify`): generic words collide with agents' built-in
   commands.
6. **The `description` does the selecting**: third person, what the skill
   does and when to use it, with the words a user would say.
7. **Exception**: the kit's router skill is named after the kit (`mason`).

