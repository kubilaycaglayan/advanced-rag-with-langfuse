"""Custom v2.17 StateGraph over the extracted, sequential execution boundaries.

The target remains unregistered. No checkpointing, retry policy, prebuilt agent,
message reducer, or provider substitution is enabled here.
"""
from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.observability import observation, update
from app.agent import execution
from app.agent.state import AgentRuntime, ExecutionState
from app.settings_definitions import TargetAgentSettings


class GraphState(TypedDict):
    # One ordered in-memory run object; no merge or message conversion is needed
    # because every transition has exactly one successor and tools stay sequential.
    agent: ExecutionState


BOUNDARIES = {
    'prepare': 'prepare_question',
    'decide': 'decide_next_turn',
    'select': 'select_model_turn',
    'tools': 'process_reply_tools',
    'review': 'review_answer_text',
    'budget': 'draft_budget',
    'final': 'finalize_answer',
}
ROUTES = {
    'prepare': {'decide': 'decide'},
    'decide': {'select': 'select', 'budget': 'budget'},
    'select': {'tools': 'tools', 'review': 'review'},
    'tools': {'decide': 'decide', 'budget': 'budget', 'final': 'final'},
    'review': {'decide': 'decide', 'final': 'final'},
    'budget': {'final': 'final'},
    'final': {'done': END},
}


def execution_limit(settings: TargetAgentSettings) -> int:
    """Allow the application's longest path plus one framework halt step.

    prepare + T*(decide, select, tools/review) + decide + budget + final
    = 3*T + 4 nodes. A whole reply's tools occupy one node regardless of count.
    The extra step lets LangGraph observe normal termination after finalization.
    """
    return 3 * settings.max_turns + 5


def boundary_node(name: str):
    def run(state: GraphState, runtime: Runtime[AgentRuntime]) -> GraphState:
        agent = state['agent']
        with observation(f"graph node: {name}", input=state_summary(agent),
                         metadata={"graph_node": name, "execution_backend": "langgraph"}) as span:
            getattr(execution, BOUNDARIES[name])(agent, runtime.context)
            if name == 'prepare':
                # Match the original preparation-before-schema-construction order.
                runtime.context.tool_specs = execution._tool_specs()
            update(span, output=state_summary(agent))
        return {'agent': agent}
    return run


def next_route(state: GraphState) -> str:
    return state['agent'].route


@lru_cache(maxsize=1)
def build_graph():
    graph = StateGraph(GraphState, context_schema=AgentRuntime)
    for name in BOUNDARIES:
        graph.add_node(name, boundary_node(name))
    graph.add_edge(START, 'prepare')
    for name, paths in ROUTES.items():
        graph.add_conditional_edges(name, next_route, paths)
    return graph.compile()


def invoke_graph(state: ExecutionState, runtime: AgentRuntime) -> ExecutionState:
    with observation("agent graph", input={"question": state.question}, metadata={
            "execution_backend": "langgraph", "target_pipeline": "v2.17",
            "recursion_limit": execution_limit(state.settings)}) as span:
        result = build_graph().invoke({'agent': state}, context=runtime,
                                     config={'recursion_limit': execution_limit(state.settings)})
        update(span, output=state_summary(result['agent']))
    return result['agent']


def state_summary(state: ExecutionState) -> dict:
    """Bounded routing measurements; usage/cost remain solely on generations."""
    return {"route": state.route, "turns": state.turns, "tool_calls": state.tool_calls,
            "collected_passages": len(state.evidence), "rejected_answers": len(state.rejected_answers),
            "verification_supported": state.verification_supported,
            "verification_reason": state.verification_reason,
            "budget_reason": state.budget_reason, "budget_drafted": state.budget_drafted,
            "final_prepared": state.final_prepared,
            "stopped": state.final_result.get("stopped") if state.final_result else None}
