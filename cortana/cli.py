"""Cortana local-agent CLI."""
from __future__ import annotations

import asyncio
import logging

import typer
from rich.console import Console
from rich.prompt import Prompt

app = typer.Typer(name="cortana", help="OpenAI-powered personal computer agent")
console = Console()


@app.command()
def start(
    voice: bool = typer.Option(False, "--voice", "-v", help="Enable optional local voice I/O"),
    debug: bool = typer.Option(False, "--debug", help="Verbose logging"),
):
    """Start the privileged local bridge used by the authenticated web app."""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # WebSockets DEBUG includes raw frame payloads. Bridge credentials are sent
    # in the first frame, so protocol logging must remain metadata-only.
    logging.getLogger("websockets").setLevel(logging.INFO)
    asyncio.run(_run(voice=voice))


async def _run(voice: bool):
    from cortana.core.orchestrator import Orchestrator
    from cortana.core.ws_server import serve as bridge_serve

    orchestrator = Orchestrator()
    await orchestrator.start()
    console.print("[bold cyan]Cortana[/bold cyan] OpenAI agent starting…")
    console.print("  Local web bridge → [cyan]wss://localhost:8765[/cyan]")

    tasks = [asyncio.create_task(bridge_serve(orchestrator))]
    if voice:
        from cortana.core.ws_server import set_voice_pipeline
        from cortana.voice.pipeline import VoicePipeline

        pipeline = VoicePipeline(orchestrator)
        set_voice_pipeline(pipeline)
        tasks.append(asyncio.create_task(pipeline.start()))
        console.print("  Voice pipeline   → [green]active[/green]")

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        await orchestrator.stop()


@app.command()
def chat():
    """Talk to the OpenAI-powered local agent from a terminal."""
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_chat_loop())


async def _chat_loop():
    from cortana.core.orchestrator import Orchestrator, Request

    orchestrator = Orchestrator()
    await orchestrator.start()
    console.print("[bold cyan]Cortana[/bold cyan] — OpenAI agent. Ctrl-C to quit.\n")
    while True:
        try:
            text = Prompt.ask("[bold]You[/bold]")
        except (KeyboardInterrupt, EOFError):
            break
        if text.strip():
            response = await orchestrator.handle(Request(text=text, source="text"))
            console.print(f"\n[bold cyan]Cortana:[/bold cyan] {response.text}\n")


if __name__ == "__main__":
    app()
