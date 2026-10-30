# symbol-checker-cli

A CLI checker that validates a project's `symbols.toml` schema and checks Python source files for forbidden subwords and forbidden terms, emitting findings with actionable suggestions.

## Configuration (`symbols.toml`)

```toml
[settings]
include = ["src/**/*.py", "tests/**/*.py"]
exclude = []
forbidden_subwords = ["data", "info", "item", "obj", "val", "temp"]
allowed_symbols = []

[[terms]]
term = "load"
definition = "Read and deserialize a configuration or source text from a filesystem path."
forbidden_terms = ["fetch", "retrieve", "obtain", "read_config"]
```

## Usage

```bash
# Check entire configured workspace
uv run symbol

# Filter to specific file(s) or directory(s)
uv run symbol src/symbol_checker/cli.py
uv run symbol src/
uv run symbol tests/

# Override config file path
uv run symbol --config path/to/symbols.toml
```

### Exit Codes

- `0`: No findings.
- `1`: One or more findings reported.
- `2`: Configuration file could not be read or parsed.

## Development

```bash
# Enable local git hooks (pre-commit and commit-msg)
git config core.hooksPath .githooks

uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run glossary
uv run symbol
uv run architecture
```
