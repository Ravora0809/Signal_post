import asyncio
import json
import logging
import click
import structlog
from .db import session_scope, get_session_factory
from .pipeline import SignalPostPipeline
from .phases.p8_bulk_profiles import load_orgnrs, run_bulk
from .phases.p9_evaluation import evaluate_sample


def _setup_logging():
    from .config import get_settings
    logging.basicConfig(level=get_settings().log_level)
    structlog.configure(processors=[structlog.processors.add_log_level, structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()], wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))


@click.group()
def cli(): _setup_logging()


@cli.command("research")
@click.argument("orgnr")
def research(orgnr):
    async def _go():
        pipeline = SignalPostPipeline()
        try:
            with session_scope() as session:
                result = await pipeline.research_one(session, orgnr)
                click.echo(json.dumps(result, indent=2, default=str))
        finally: await pipeline.aclose()
    asyncio.run(_go())


@cli.command("bulk")
@click.argument("path", type=click.Path(exists=True))
@click.option("--concurrency", default=4, type=int)
def bulk(path, concurrency):
    orgs = load_orgnrs(path)
    async def _go():
        pipeline = SignalPostPipeline()
        try:
            result = await run_bulk(get_session_factory(), pipeline, orgs, concurrency=concurrency)
            click.echo(json.dumps(result, indent=2))
        finally: await pipeline.aclose()
    asyncio.run(_go())


@cli.command("evaluate")
@click.option("--n", default=100, type=int)
def evaluate(n):
    with session_scope() as session:
        click.echo(json.dumps(evaluate_sample(session, n=n), indent=2, default=str))


if __name__ == "__main__": cli()
