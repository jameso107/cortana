"""Cortana CLI — `cortana` entrypoint."""
from __future__ import annotations

import asyncio
import logging

import typer
from rich.console import Console
from rich.prompt import Prompt

app = typer.Typer(name="cortana", help="Cortana local AI assistant")
console = Console()


@app.command()
def start(
    voice: bool = typer.Option(False, "--voice", "-v", help="Enable voice I/O"),
    debug: bool = typer.Option(False, "--debug", help="Verbose logging"),
):
    """Start the Cortana assistant."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    asyncio.run(_run(voice=voice))


async def _run(voice: bool):
    from cortana.core.orchestrator import Orchestrator, Request

    orch = Orchestrator()
    await orch.start()

    if voice:
        from cortana.voice.pipeline import VoicePipeline
        pipeline = VoicePipeline(orch)
        await pipeline.start()
        return

    console.print("[bold cyan]Cortana[/bold cyan] — type your request, Ctrl-C to quit.\n")
    while True:
        try:
            text = Prompt.ask("[bold]You[/bold]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break
        if not text.strip():
            continue
        response = await orch.handle(Request(text=text, source="text"))
        console.print(f"\n[bold cyan]Cortana:[/bold cyan] {response.text}\n")


@app.command()
def ui():
    """Launch the Cortana web UI (Vite dev server)."""
    import subprocess
    subprocess.run(["npm", "run", "dev"], cwd="ui", check=True)


if __name__ == "__main__":
    app()
