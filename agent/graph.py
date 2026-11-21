"""A minimal LangGraph tool loop: the same shape as LangGraph 3, wired for a web request.

This is a skeleton to prove your deployment works end to end. Replace it with your
own design. Keep the rules in code and give the model only the judgment calls.
"""
# Annotated lets us attach a reducer to a state field; TypedDict describes the state keys.
import json
from operator import add
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent.llm import get_llm
from agent.intake import inspect_request, missing_fields_message
from agent.rules import (
    batch_exists_in_master,
    claim_within_policy_window,
    credit_note_sla,
    ignore_email_override_instructions,
    invoice_reference_or_exception,
    no_duplicate_active_claim,
    quantity_not_above_invoiced,
    required_fields_present,
    verbal_approval_not_sufficient,
)
from agent.tools import TOOLS, match_primary_sale, lookup_batch, search_claims

# Stop after four model turns so a tool-calling loop cannot run forever.
MAX_TRIPS = 4
# This instruction asks for tool-backed facts and makes the model report missing data.
SYSTEM = (
    "You answer questions about Pfizer Limited's General Medicines trade channel for an internal user. "
    "Use the tools for every fact. For a claim status or credit-note question with a claim number, always use "
    "search_claims before answering. If a tool returns found=false, say so. Never invent a batch, date or number."
)


def available_tools(state: dict) -> list:
    """Expose only tools that are valid for the deterministic intake intent."""
    intent = state["intake"].get("intent")
    if intent == "claim_status":
        return [tool for tool in TOOLS if tool.name == "search_claims"]
    if intent in {"claim_triage", "batch_lookup"}:
        return [tool for tool in TOOLS if tool.name == "lookup_batch"]
    return TOOLS


class State(TypedDict):
    # LangGraph merges new messages into this list using add_messages below.
    messages: Annotated[list[AnyMessage], add_messages]
    # Number of times the model node has run in this request.
    trips: int
    # Deterministic classification and extracted fields from the user's input.
    intake: dict
    # Append-only events for debugging one graph request.
    debug_trace: Annotated[list[dict], add]
    # Tool facts and deterministic policy outcomes for a claim request.
    facts: dict
    evidence: Annotated[list[str], add]
    rule_outcomes: list[dict]


def _trace(state: State, event: str, offset: int = 0, **details) -> dict:
    """Create one ordered event and print it in the server console."""
    entry = {"step": len(state.get("debug_trace", [])) + offset + 1, "event": event, **details}
    print(f"[Sankalp trace] {json.dumps(entry, default=str)}")
    return entry


def validate_input(state: State) -> dict:
    """Check claim-search fields before a model is allowed to call a tool."""
    intake = inspect_request(state["messages"][0].content)
    checked = _trace(
        state,
        "intake_checked",
        intent=intake["intent"],
        ready=intake["ready"],
        entities={key: value for key, value in intake["entities"].items() if value},
        missing=intake["missing"],
    )
    if intake["ready"]:
        routed = _trace(state, "intake_routed", offset=1, destination="model")
        return {"intake": intake, "debug_trace": [checked, routed]}
    blocked = _trace(state, "request_blocked", offset=1, reason="mandatory_claim_fields_missing")
    routed = _trace(state, "intake_routed", offset=2, destination="__end__")
    return {
        "intake": intake,
        "messages": [AIMessage(content=missing_fields_message(intake))],
        "debug_trace": [checked, blocked, routed],
    }


def route_intake(state: State) -> str:
    """End immediately when required claim fields are missing."""
    if not state["intake"]["ready"]:
        return END
    if state["intake"]["intent"] in {"claim_triage", "claim_status"}:
        return "gather_facts"
    return "model"


def gather_claim_facts(state: State) -> dict:
    """Call the correct data tools from extracted fields, without model-selected identifiers."""
    intake = state["intake"]
    entities = intake["entities"]
    facts = {}
    events = []

    def collect(tool, args: dict, key: str) -> None:
        result = tool.invoke(args)
        facts[key] = result
        events.append(_trace(
            state,
            "tool_completed",
            offset=len(events),
            tool=tool.name,
            arguments=args,
            found=result.get("found"),
            record_count=len(result.get("records", [])) if isinstance(result.get("records"), list) else None,
        ))
    if intake["intent"] == "claim_status":
        collect(search_claims, {"claim_no": entities["claim_no"]}, "claim")
    else:
        collect(lookup_batch, {"batch_no": entities["batch_no"]}, "batch")
        collect(match_primary_sale, {
            "invoice_ref": entities["invoice_ref"],
            "batch_no": entities["batch_no"],
            "stockist_code": entities["stockist_code"],
        }, "sale")
        collect(search_claims, {
            "batch_no": entities["batch_no"],
            "stockist_code": entities["stockist_code"],
        }, "claim_history")

    evidence = [json.dumps({"tool": key, **value}, default=str) for key, value in facts.items()]
    return {"facts": facts, "evidence": evidence, "debug_trace": events}


def apply_claim_rules(state: State) -> dict:
    """Run plain Python policy checks using intake fields and gathered tool results."""
    intake = state["intake"]
    entities = intake["entities"]
    facts = state.get("facts", {})
    outcomes = [ignore_email_override_instructions()]

    if intake["intent"] == "claim_triage":
        batch = facts.get("batch")
        sale = facts.get("sale")
        history = facts.get("claim_history")
        outcomes.extend([
            required_fields_present(entities),
            batch_exists_in_master(batch),
            claim_within_policy_window(
                entities.get("claim_type"),
                entities.get("claim_date"),
                (batch or {}).get("expiry_date") if batch and batch.get("found") else None,
            ),
            quantity_not_above_invoiced(
                entities.get("qty"),
                ({
                    "invoiced_qty": sum(float(row.get("invoiced_qty") or 0) for row in sale["records"]),
                    "free_qty": sum(float(row.get("free_qty") or 0) for row in sale["records"]),
                } if sale and sale.get("found") else None),
            ),
            no_duplicate_active_claim(
                history.get("records") if history is not None and history.get("found") else ([] if history else None),
                entities["stockist_code"],
                entities["batch_no"],
            ),
            invoice_reference_or_exception(
                entities.get("invoice_ref"),
                ledger_verified=entities.get("invoice_exception_documented", False),
                area_manager_approval=entities.get("invoice_exception_documented", False),
            ),
            verbal_approval_not_sufficient(entities.get("verbal_approval", False)),
        ])
    elif intake["intent"] == "claim_status":
        claim_rows = (facts.get("claim") or {}).get("records", [])
        if claim_rows:
            claim = claim_rows[0]
            outcomes.append(credit_note_sla(
                claim.get("receipt_date"),
                None,
                claim.get("credit_note_no"),
            ))

    events = [_trace(
        state,
        "rules_applied",
        rule_count=len(outcomes),
        passed=sum(outcome["passed"] is True for outcome in outcomes),
        failed=sum(outcome["passed"] is False for outcome in outcomes),
        unevaluable=sum(outcome["passed"] is None for outcome in outcomes),
    )]
    return {"rule_outcomes": outcomes, "debug_trace": events}


def compose_claim_answer(state: State) -> dict:
    """Ask the model to explain already-gathered facts and rule results, with no tools available."""
    rule_context = SystemMessage(
        "Write a concise answer for this claim request. Use only the verified tool facts and rule results below. "
        "Never claim approval. Explain failed or unevaluable checks and ask for missing evidence. "
        f"Verified tool facts: {json.dumps(state.get('facts', {}), default=str)}. "
        f"Deterministic rule outcomes: {json.dumps(state.get('rule_outcomes', []), default=str)}"
    )
    reply = get_llm().invoke([rule_context, *state["messages"]])
    event = _trace(state, "answer_composed", model_turn=state.get("trips", 0) + 1)
    return {"messages": [reply], "trips": state.get("trips", 0) + 1, "debug_trace": [event]}


def call_model(state: State) -> dict:
    # Create a model client and expose the available LangChain tools to it.
    tools = available_tools(state)
    llm = get_llm().bind_tools(tools)
    # Send the safety instruction followed by the conversation so far.
    context = SystemMessage(
        "The deterministic intake classified this request as "
        f"{state['intake']['intent']}. Use only the tools provided for this intent. "
        f"Verified extracted fields: {json.dumps(state['intake']['entities'])}."
    )
    reply = llm.invoke([SystemMessage(SYSTEM), context, *state["messages"]])
    event = _trace(
        state,
        "model_responded",
        model_turn=state.get("trips", 0) + 1,
        requested_tools=[call["name"] for call in getattr(reply, "tool_calls", [])],
    )
    next_destination = "tools" if getattr(reply, "tool_calls", None) and state.get("trips", 0) + 1 < MAX_TRIPS else "__end__"
    routed = _trace(state, "model_routed", offset=1, destination=next_destination, trips=state.get("trips", 0) + 1)
    # Return only state updates: append the reply and increment the turn counter.
    return {"messages": [reply], "trips": state.get("trips", 0) + 1, "debug_trace": [event, routed]}


def run_tools(state: State) -> dict:
    # Index tools by their public name so model tool calls can be dispatched.
    by_name = {tool.name: tool for tool in available_tools(state)}
    # Accumulate tool results as LangChain ToolMessage objects.
    out = []
    events = []
    # The model can request one or more tools in a single response.
    for call in state["messages"][-1].tool_calls:
        if call["name"] not in by_name:
            events.append(_trace(state, "tool_blocked", offset=len(events), tool=call["name"], reason="not_available_for_intent"))
            out.append(ToolMessage(
                content=json.dumps({"found": False, "reason": "This tool is not available for the current request type."}),
                tool_call_id=call["id"],
                name=call["name"],
            ))
            continue
        # Execute the selected tool with the arguments supplied by the model.
        result = by_name[call["name"]].invoke(call["args"])
        summary = {"found": result.get("found")} if isinstance(result, dict) and "found" in result else {}
        if isinstance(result, dict) and "records" in result:
            summary["record_count"] = len(result["records"])
        events.append(_trace(state, "tool_completed", offset=len(events), tool=call["name"], arguments=call["args"], **summary))
        # Attach the result to its call ID so the model can interpret the evidence.
        out.append(ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"], name=call["name"]))
    # LangGraph appends these tool results to the conversation state.
    return {"messages": out, "debug_trace": events}


def route(state: State) -> str:
    # Inspect the latest model response to decide whether another tool step is needed.
    last = state["messages"][-1]
    # Continue to the tool node only when there are tool calls and turns remain.
    if getattr(last, "tool_calls", None) and state["trips"] < MAX_TRIPS:
        return "tools"
    # Otherwise finish this graph execution.
    return END


# Define the graph's state schema so each node shares messages and trip count.
builder = StateGraph(State)
# Register the Python functions as named graph nodes.
builder.add_node("validate_input", validate_input)
builder.add_node("gather_facts", gather_claim_facts)
builder.add_node("apply_rules", apply_claim_rules)
builder.add_node("compose_answer", compose_claim_answer)
builder.add_node("model", call_model)
builder.add_node("tools", run_tools)
# Every user question starts with deterministic intake validation.
builder.add_edge(START, "validate_input")
# Missing claim fields produce a direct response; complete requests go to the model.
builder.add_conditional_edges(
    "validate_input",
    route_intake,
    {"gather_facts": "gather_facts", "model": "model", END: END},
)
# Claim requests gather facts, run deterministic Python rules, then compose the response.
builder.add_edge("gather_facts", "apply_rules")
builder.add_edge("apply_rules", "compose_answer")
builder.add_edge("compose_answer", END)
# After a model turn, choose tools or END using the route function.
builder.add_conditional_edges("model", route, {"tools": "tools", END: END})
# After tools return evidence, ask the model again to interpret it or request more.
builder.add_edge("tools", "model")
# Compile the graph into an executable object.
graph = builder.compile()


def run_question(question: str) -> dict:
    # Start a fresh conversation containing only this user's question.
    final = graph.invoke({
        "messages": [HumanMessage(question)],
        "trips": 0,
        "intake": {},
        "debug_trace": [],
        "facts": {},
        "evidence": [],
        "rule_outcomes": [],
    })
    # Extract tool messages as evidence for the API response.
    evidence = [*final["evidence"], *(m.content for m in final["messages"] if isinstance(m, ToolMessage))]
    # Return the final model answer, tool evidence, and number of model turns.
    return {
        "answer": final["messages"][-1].content,
        "evidence": evidence,
        "model_calls": final["trips"],
        "debug_trace": final["debug_trace"],
        "rule_outcomes": final["rule_outcomes"],
    }
