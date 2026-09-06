# Worldloom

**Read [AGENTS.md](AGENTS.md) first.** It is the harness guide: you are the model,
Worldloom builds the world and checks your prose against it. This file exists
because one coding harness reads it by name; the only thing it adds is the
slash-command list below.

## Skill and commands

A skill drives the whole loop, including the rejection cycle:

```
/worldloom
```

Individual steps, if you want to drive it yourself:

```
/worldloom-build      build a world from a seed
/worldloom-narrate    fetch requests, write prose, submit until accepted
/worldloom-render     materialise and validate
```
