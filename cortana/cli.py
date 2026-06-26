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
    """Start the Cortana assistant daemon (chat WebSocket + optional voice)."""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run(voice=voice))


async def _run(voice: bool):
    from cortana.core.orchestrator import Orchestrator
    from cortana.core.ws_server import serve as chat_serve
    from cortana.core.terminal_server import serve as term_serve
    from cortana.core.file_server import serve as file_serve

    orch = Orchestrator()
    await orch.start()

    console.print("[bold cyan]Cortana[/bold cyan] daemon starting…")
    console.print("  Chat WebSocket  → [cyan]ws://localhost:8765[/cyan]")
    console.print("  Terminal server → [cyan]ws://localhost:8766[/cyan]")
    console.print("  File API        → [cyan]http://localhost:8767[/cyan]")

    tasks = [
        asyncio.create_task(chat_serve(orch)),
        asyncio.create_task(term_serve()),
        asyncio.create_task(file_serve()),
    ]

    if voice:
        from cortana.voice.pipeline import VoicePipeline
        from cortana.core.ws_server import set_voice_pipeline
        pipeline = VoicePipeline(orch)
        set_voice_pipeline(pipeline)
        tasks.append(asyncio.create_task(pipeline.start()))
        console.print("  Voice pipeline  → [green]active[/green]")

    console.print("\n[dim]Press Ctrl-C to stop.[/dim]\n")
    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[dim]Cortana stopped.[/dim]")


@app.command()
def chat():
    """Interactive text chat in the terminal (no UI needed)."""
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_chat_loop())


async def _chat_loop():
    from cortana.core.orchestrator import Orchestrator, Request
    orch = Orchestrator()
    await orch.start()
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
