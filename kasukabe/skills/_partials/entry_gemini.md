## Platform: Gemini CLI

### Installation

```bash
bash setup.sh --host gemini
```

This renders skill templates for use with the Gemini CLI.

### How It Works

- Skills are loaded via `activate_skill`
- The Foreman activates each pipeline skill, provides context (workspace, origin, size), and each skill completes its task by writing output files

### Usage

In Gemini CLI:

```
/kasukabe-build house.jpg at 100,64,200 size 12x8x10
```
