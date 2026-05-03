"""Module entry point — makes `python -m agentminds <subcommand>` work.

This exists because the `agentminds` console script (defined as a
`[project.scripts]` entry in pyproject.toml) lands in
`<scheme>/Scripts/agentminds.exe` on Windows and `<scheme>/bin/agentminds`
on POSIX. The `<scheme>/Scripts/` dir is NOT added to PATH for Python
`--user` installs on Windows, so a stranger running `pip install
agentminds` then `agentminds connect` gets `command not found` even
though everything installed correctly.

`python -m agentminds connect` always works because the Python
interpreter the user just used to run pip is also on their PATH.
The website docs lead with this form for that reason.
"""
from agentminds._cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
