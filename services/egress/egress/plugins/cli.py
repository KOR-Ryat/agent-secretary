"""CLI deliverer — prints result to stdout.

Used for manual dry-run testing (the CLI ingress submits an event with
`response_routing.primary.channel == 'cli'`).
"""

from __future__ import annotations

from agent_secretary_schemas import ResultEvent

from egress.logging import get_logger
from egress.plugins._base import ChannelDeliverer

log = get_logger("egress.plugins.cli")


class CliDeliverer(ChannelDeliverer):
    name = "cli"

    async def deliver(self, result: ResultEvent) -> None:
        log.info(
            "cli.deliver",
            result_id=result.result_id,
            event_id=result.event_id,
            decision=result.output.get("cto_output", {}).get("decision"),
        )
        print(f"\n=== ResultEvent {result.result_id} (event {result.event_id}) ===")
        print(result.summary_markdown)
        print("=== end ===\n", flush=True)
