"""Read-only MCP tools for selective local decision assistance."""
from __future__ import annotations

import asyncio
from typing import Any, Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from .decision_client import DecisionClient
from .decisions import DecisionBackendError, DecisionInputError


INSTRUCTIONS = (
    "Use structured decisions for bounded classification tasks. Use decision_preflight to route an "
    "actionable request and run_decision_workflow for an explicit multi-stage decision graph. "
    "The runner evaluates every defined stage automatically; it does not intercept hidden "
    "model reasoning. Batch independent questions and use deterministic rules between stages. "
    "Submit compact relevant facts, "
    "not secrets, full vaults or hidden reasoning. Results are uncalibrated suggestions, never "
    "evidence, current device state or permission. Respect needs_review and independently "
    "validate any control arguments. On failure continue normal reasoning without retry loops."
)


class ChoiceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["choice"]
    instructions: str
    criteria: dict[str, str | None]


class ScoreQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["score"]
    instructions: str
    criteria: list[str]


class YesNoQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["noul"]
    instructions: str
    criteria: dict[Literal["true", "false"], str] | None = None


Question = Annotated[ChoiceQuestion | ScoreQuestion | YesNoQuestion, Field(discriminator="type")]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                            idempotentHint=True, openWorldHint=False)


def build_server(client=None):
    client = client or DecisionClient()
    server = FastMCP("Aiden Decisions", instructions=INSTRUCTIONS, log_level="WARNING")

    async def call(function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except (DecisionInputError, DecisionBackendError):
            raise ToolError("Local decision helper could not answer. Continue normal reasoning; no action was performed.") from None
        except Exception:
            raise ToolError("Local decision helper failed. Continue normal reasoning; no action was performed.") from None

    @server.tool(annotations=READ_ONLY)
    async def route_request(request: str) -> dict[str, Any]:
        """Suggest an Aiden handler and draft intent for a household request (max 4000 bytes).

        Supported commands use zero model tokens; unfamiliar wording uses local inference.
        Use for reusable routing work. This neither reads live device state nor executes controls.
        """
        return await call(client.route, request)

    @server.tool(annotations=READ_ONLY)
    async def classify_or_score(state: str | dict[str, Any] | list[Any],
                                questions: dict[str, Question]) -> dict[str, Any]:
        """Classify compact supplied facts using named choice, noul (yes/no) or score questions.

        Batch related questions in one call. Choice criteria are 2–24 named options; score
        criteria are 2–24 ordered descriptions. Max 64 questions / 64 KiB. Probabilities
        are uncalibrated; use ordinary reasoning for uncertain or consequential conclusions.
        """
        clean = {key: value.model_dump(exclude_none=True) for key, value in questions.items()}
        return await call(client.decide, state, clean)

    @server.tool(annotations=READ_ONLY)
    async def decision_preflight(request: str) -> dict[str, Any]:
        """Automatically classify a request, check confidence, apply policy and return verification steps.

        This covers visible workflow decisions only. Model calibration is task-scoped and
        failed candidates stay disabled. It never changes devices or grants permission.
        """
        return await call(client.preflight, request)

    @server.tool(annotations=READ_ONLY)
    async def run_decision_workflow(state: str | dict[str, Any] | list[Any],
                                    stages: list[dict[str, Any]]) -> dict[str, Any]:
        """Run every stage of a declared bounded decision graph automatically.

        Stages have id, optional after/when, and either typed questions or an all/any rule.
        Conditions reference stage/question/op/value with eq/gte/lte. Independent stages
        share one native model call. Max 12 stages, 64 questions, 64 KiB; no arbitrary code,
        shell, tool execution or model-internal reasoning. Inspect trace and review flags.
        """
        return await call(client.workflow, state, stages)

    @server.tool(annotations=READ_ONLY)
    async def decision_health() -> dict[str, Any]:
        """Check the local helper when troubleshooting. Do not call before every decision."""
        return await call(client.health)

    return server


def main():
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
