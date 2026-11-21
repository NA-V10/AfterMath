"""The asyncpg checkpoint saver behind a real LangGraph graph with a human interrupt."""

from __future__ import annotations

import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.database.checkpointer import AsyncpgCheckpointSaver
from app.database.session import Database


class S(TypedDict, total=False):
    log: list[str]
    answer: str


def first(state: S) -> S:
    return {"log": [*state.get("log", []), "first"]}


def ask(state: S) -> S:
    answer = interrupt({"question": "which asset?"})
    return {"answer": answer, "log": [*state["log"], "ask"]}


def last(state: S) -> S:
    return {"log": [*state["log"], f"last:{state['answer']}"]}


def build(saver: AsyncpgCheckpointSaver):  # type: ignore[no-untyped-def]
    g = StateGraph(S)
    g.add_node("first", first)
    g.add_node("ask", ask)
    g.add_node("last", last)
    g.add_edge(START, "first")
    g.add_edge("first", "ask")
    g.add_edge("ask", "last")
    g.add_edge("last", END)
    return g.compile(checkpointer=saver)


async def test_interrupt_survives_a_new_saver_and_graph_instance(database: Database) -> None:
    thread = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph = build(AsyncpgCheckpointSaver(database.engine))
    await graph.ainvoke({"log": []}, thread)
    paused = await graph.aget_state(thread)
    assert paused.next == ("ask",)
    assert paused.tasks[0].interrupts[0].value == {"question": "which asset?"}

    # Simulate a process restart: brand-new saver and compiled graph, same database.
    graph2 = build(AsyncpgCheckpointSaver(database.engine))
    result = await graph2.ainvoke(Command(resume="SUB-02"), thread)
    assert result["log"] == ["first", "ask", "last:SUB-02"]
    final = await graph2.aget_state(thread)
    assert final.next == ()

    saver = AsyncpgCheckpointSaver(database.engine)
    history = [c async for c in saver.alist(thread)]
    assert len(history) >= 4
    assert history[0].checkpoint["id"] > history[-1].checkpoint["id"]  # newest first
    limited = [c async for c in saver.alist(thread, limit=2)]
    assert len(limited) == 2

    await saver.adelete_thread(thread["configurable"]["thread_id"])
    assert await saver.aget_tuple(thread) is None
