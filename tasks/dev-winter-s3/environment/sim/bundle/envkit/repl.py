"""A terminal console for playing an environment by hand.

A person at this console has the same tools, the same operation budget and
the same information as an agent. The session is written to a trace file,
which can then be replayed as a reference run:

    envkit play depot-basic --record traces/alice.jsonl
    # then in the scenario:  reference = "replay:traces/alice.jsonl"

Commands:
    <tool> key=value ...     call a tool        e.g.  order_stock item=A qty=40
    <tool> {"json": ...}     call a tool with a JSON object of arguments
    tools                    list tools and their arguments
    prompt                   show the task prompt again
    quit                     stop here; remaining windows run unattended

The console drives any `Client`, so a browser front end can reuse it: all it
needs is `tools()` and `call()`.
"""
from __future__ import annotations

import json
import shlex
from typing import Any, Callable

from .policies import Client


def parse_command(line: str) -> tuple[str, dict[str, Any]]:
    """'order_stock item=A qty=40' -> ('order_stock', {'item': 'A', 'qty': 40})"""
    line = line.strip()
    name, _, rest = line.partition(" ")
    rest = rest.strip()
    if rest.startswith("{"):
        args = json.loads(rest)
        if not isinstance(args, dict):
            raise ValueError("JSON arguments must be an object")
        return name, args
    args = {}
    for token in shlex.split(rest):
        key, sep, value = token.partition("=")
        if not sep:
            raise ValueError(f"expected key=value, got '{token}'")
        try:
            args[key] = json.loads(value)
        except json.JSONDecodeError:
            args[key] = value  # a bare word is a string
    return name, args


def format_tools(tools: list[dict[str, Any]]) -> str:
    lines = []
    for t in tools:
        props = t["input_schema"].get("properties", {})
        required = set(t["input_schema"].get("required", []))
        sig = " ".join(f"{k}=" if k in required else f"[{k}=]" for k in props)
        lines.append(f"  {t['name']} {sig}".rstrip())
        lines.append(f"      {t['description']}")
    return "\n".join(lines)


def format_header(h: dict[str, Any]) -> str:
    core = f"window {h['window']}/{h['windows_total']} | ops left {h['ops_left']} | {h['clock']}"
    extra = " | ".join(f"{k} {v}" for k, v in h.items()
                       if k not in ("window", "windows_total", "ops_left", "clock", "done", "end_reason"))
    return f"[{core}{' | ' + extra if extra else ''}]"


def run_console(client: Client, prompt_text: str, read: Callable[[str], str] = input,
                write: Callable[[str], None] = print) -> None:
    write(prompt_text)
    write("Tools:\n" + format_tools(client.tools()))
    write("\nType a tool call (e.g. `end_window`), `tools`, `prompt`, or `quit`.\n")
    while not client.done:
        try:
            line = read("> ").strip()
        except (EOFError, KeyboardInterrupt):
            write("")
            break
        if not line:
            continue
        if line in ("quit", "exit"):
            break
        if line == "tools":
            write(format_tools(client.tools()))
            continue
        if line == "prompt":
            write(prompt_text)
            continue
        try:
            name, args = parse_command(line)
        except ValueError as e:
            write(f"could not parse that: {e}")
            continue
        response = client.call(name, **args)
        body = response["result"] if response["ok"] else {"error": response["error"]}
        write(json.dumps(body, indent=2))
        write(format_header(response["header"]))
    if client.done:
        write("The episode is over.")
