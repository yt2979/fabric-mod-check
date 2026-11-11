"""Deep Research workflow built on the course starter's Agents SDK and Vertex model."""

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm
from agents import Agent, ModelSettings, RunContextWrapper, Runner, function_tool, set_tracing_disabled
from agents.extensions.models.litellm_model import LitellmModel
from pydantic import BaseModel

from catalog import Catalog

set_tracing_disabled(True)
litellm.suppress_debug_info = True
CATALOG = Catalog.load()
MODEL_NAME = os.getenv("MODEL_NAME", "vertex_ai/gemini-3.5-flash-lite")
MODEL = LitellmModel(model=MODEL_NAME, api_key="unused")
ROLES = {
    "versions": "Version researcher",
    "dependencies": "Dependency researcher",
    "notes": "Maintainer researcher",
}
SCOPE = (
    "Fabric Mod Check covers Minecraft Java Edition 1.21.1, Fabric, and only "
    "Sodium, Iris, Indium, and Continuity. External requirements such as Fabric API "
    "can be reported when declared, but their versions and actual runtime behavior "
    "are outside the dataset."
)


class Job(BaseModel):
    role: Literal["versions", "dependencies", "notes"]
    question: str
    version_ids: list[str]


class Plan(BaseModel):
    kind: Literal["research", "clarify", "outside_scope"]
    message: str
    jobs: list[Job]
    wants_changes: bool
    keep: list[str]


class Review(BaseModel):
    jobs: list[Job]


class Finding(BaseModel):
    summary: str
    sources: list[str]
    gaps: list[str]


class Statement(BaseModel):
    text: str
    sources: list[str]


class Report(BaseModel):
    headline: str
    findings: list[Statement]
    limitations: list[str]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def settings():
    extra = {"vertex_location": os.getenv("VERTEX_LOCATION", "global"), "timeout": 35}
    if project := os.getenv("GOOGLE_CLOUD_PROJECT"):
        extra["vertex_project"] = project
    return ModelSettings(temperature=0.1, max_tokens=2800, extra_args=extra)


@dataclass
class ResearchContext:
    catalog: Catalog
    trace: list[dict]
    agent: str
    round_number: int
    seen: set[str] = field(default_factory=set)
    evidence: list[dict] = field(default_factory=list)
    version_ids: list[str] = field(default_factory=list)
    relevant_mods: set[str] = field(default_factory=set)
    locked_mods: list[str] = field(default_factory=list)

    def use(self, name, args):
        started = now()
        if name == "read_version":
            try:
                version = self.catalog.version(args["version_id"])
                result = {"version": version, "sources": [version["source"]]}
            except ValueError as error:
                result = {"error": str(error)}
        else:
            operations = {
                "list_versions": self.catalog.list_versions,
                "check_pack": self.catalog.check_pack,
                "find_alternatives": self.catalog.alternatives,
                "read_notes": self.catalog.notes,
            }
            try:
                result = operations[name](**args)
            except ValueError as error:
                result = {"error": str(error)}
        self.seen.update(result.get("sources", []))
        self.evidence.append({"tool": name, "data": result})
        output = json.dumps(result, ensure_ascii=False)
        self.trace.append({
            "agent": self.agent, "name": name, "args": args, "result": output,
            "round": self.round_number, "started_at": started, "ended_at": now(),
        })
        return output


@function_tool
def collect_versions(
    ctx: RunContextWrapper[ResearchContext], version_ids: list[str], mods: list[str],
) -> str:
    """Read exact releases and their pinned dependency versions, or list named mods."""
    c = ctx.context
    version_ids = c.version_ids or version_ids
    if version_ids:
        ids = list(dict.fromkeys(version_ids))[:4]
        dependencies = [
            dep["version_id"] for vid in ids if vid in c.catalog.versions
            for dep in c.catalog.version(vid)["dependencies"]
            if dep["dependency_type"] == "required" and dep["version_id"] in c.catalog.versions
        ]
        for vid in dict.fromkeys([*ids, *dependencies]):
            c.use("read_version", {"version_id": vid})
    else:
        for mod in list(dict.fromkeys(mods))[:4]:
            c.use("list_versions", {"mod": mod})
    return json.dumps(c.evidence)


@function_tool
def collect_dependencies(
    ctx: RunContextWrapper[ResearchContext], version_ids: list[str],
    mods: list[str], keep: list[str],
) -> str:
    """Check the selected pack. In a follow-up, search alternatives. Keep takes mod slugs."""
    c = ctx.context
    version_ids = c.version_ids or version_ids
    if version_ids:
        c.use("check_pack", {"version_ids": version_ids})
        if c.round_number == 2:
            locked = c.locked_mods or [c.catalog.version(k)["mod"] if k in c.catalog.versions else k.lower() for k in keep]
            c.use("find_alternatives", {"version_ids": version_ids, "keep": locked})
            for row in c.evidence[-1]["data"].get("options", []):
                for vid in row["selected"].values():
                    if c.catalog.version(vid)["source"] not in {x["data"].get("version", {}).get("source") for x in c.evidence}:
                        c.use("read_version", {"version_id": vid})
    else:
        for mod in list(dict.fromkeys(mods))[:4]:
            c.use("list_versions", {"mod": mod})
    return json.dumps(c.evidence)


@function_tool
def collect_notes(ctx: RunContextWrapper[ResearchContext], mods: list[str]) -> str:
    """Read maintainer notes for the relevant mod slugs."""
    c = ctx.context
    relevant = [mod for mod in mods if not c.relevant_mods or mod.lower() in c.relevant_mods]
    for mod in list(dict.fromkeys(relevant))[:4]:
        c.use("read_notes", {"mod": mod})
    return json.dumps(c.evidence)


RESEARCH_TOOLS = {
    "versions": collect_versions, "dependencies": collect_dependencies, "notes": collect_notes,
}


def agent(name, instructions, output_type, tool=None, language="English"):
    model_settings = settings()
    if tool:
        model_settings.tool_choice = "required"
        model_settings.parallel_tool_calls = False
    return Agent(
        name=name, instructions=f"{SCOPE}\nWrite all prose in {language}.\n{instructions}", output_type=output_type,
        model=MODEL, model_settings=model_settings, tools=[tool] if tool else [],
        tool_use_behavior="stop_on_first_tool" if tool else "run_llm_again",
    )


def render_report(report, allowed, catalog):
    used = []
    lines = ["## " + " ".join(report.headline.split()), ""]
    for item in report.findings:
        ids = list(dict.fromkeys(item.sources))
        if not ids or any(s not in allowed or s not in catalog.evidence for s in ids):
            raise ValueError("Unverified citation in report.")
        for s in ids:
            if s not in used:
                used.append(s)
        refs = " ".join(f"[{used.index(s) + 1}]" for s in ids)
        lines.append(f"- {' '.join(item.text.split())} {refs}")
    if report.limitations:
        lines.extend(["", "## Limits", *["- " + " ".join(limit.split()) for limit in report.limitations]])
    lines.extend(["", "## Sources"])
    for i, source in enumerate(used, 1):
        evidence = catalog.evidence[source]
        title = evidence["title"].replace("[", "(").replace("]", ")")
        lines.append(f"{i}. [{title}]({evidence['url']})")
    return "\n".join(lines)


async def investigate(question, history=None, runner=Runner.run):
    """Return the starter-compatible response and flattened, attributed tool calls."""
    language = "Simplified Chinese" if re.search(r"[\u4e00-\u9fff]", question) else "English"
    trace = []
    source_ids = set()
    index = {
        mod: [[v["version_number"], v["id"]] for v in CATALOG.versions.values() if v["mod"] == mod]
        for mod in CATALOG.projects
    }
    lead = agent("Lead", (
        "Classify the current request. Ask one focused question if the game/mod/version is "
        "materially ambiguous and cannot be resolved by the index or recent conversation. "
        "Explicitly outside-scope inputs get a short answer explaining available coverage. "
        "For a supported investigation return exactly three independent jobs in this turn, "
        "one for each role: versions, dependencies, notes. Resolve version IDs from the "
        "provided index, not memory. Include known pack IDs in each job. For general "
        "release or feature questions use an empty ID list and have Researchers find records. "
        "Set wants_changes=true for requests for a fix, minimal changes, or alternatives. "
        "In keep list only mod slugs the user explicitly says to keep fixed. "
        "Do not give the research answer yourself. For non-research replies set jobs=[]."
    ), Plan, language=language)
    plan = (await runner(
        lead, json.dumps({"question": question, "recent_messages": history or [], "version_index": index}),
        context=None, max_turns=1,
    )).final_output
    clarification = ("你想检查哪几个 Mod 和版本？目前支持 Minecraft 1.21.1 Fabric 的 Sodium、Iris、Indium 和 Continuity。"
                     if language == "Simplified Chinese" else
                     "Which mods and exact versions would you like to check? I cover Sodium, Iris, Indium and Continuity on Minecraft 1.21.1 Fabric.")
    if plan.kind != "research":
        return plan.message or clarification, trace
    # The planner sees a version index, so a guessed ID alone cannot establish user intent.
    user_text = " ".join([question, *(m["content"] for m in (history or []) if m["role"] == "user")])
    named_mod = any(re.search(r"\b" + slug + r"\b", user_text.lower()) for slug in CATALOG.projects)
    named_version = any(re.search(r"\b" + vid + r"\b", user_text) for vid in CATALOG.versions)
    if not (named_mod or named_version):
        return clarification, trace
    if len(plan.jobs) != 3 or {job.role for job in plan.jobs} != set(ROLES):
        return "The research plan could not be formed. Try selecting an example or listing exact mod versions.", trace

    researcher_instructions = {
        "versions": "Retrieve the exact releases in version_ids and linked required pins. When no IDs are supplied, look up the named mods.",
        "dependencies": "Check the selected version_ids exactly. On follow-up, pass the mod slugs (e.g. iris) the user wants to keep in keep. On the first round report conflicts and identify unexamined requested alternatives.",
        "notes": "Read notes for the mods implicated by the question. For any Indium or Fabric Rendering API issue, query both indium and sodium.",
    }
    collected = []

    async def run_job(job, round_number):
        label = ROLES[job.role]
        ids = [vid for vid in job.version_ids if vid in CATALOG.versions]
        mentioned = {slug for slug in CATALOG.projects if re.search(r"\b" + slug + r"\b", question.lower())}
        relevant = mentioned | {CATALOG.version(vid)["mod"] for vid in ids}
        if "indium" in relevant:
            relevant.add("sodium")
        locked = [slug for slug in plan.keep if slug in {CATALOG.version(vid)["mod"] for vid in ids}]
        context = ResearchContext(CATALOG, trace, label, round_number,
                                  version_ids=ids, relevant_mods=relevant, locked_mods=locked)
        start = now()
        subject = agent(label, researcher_instructions[job.role] +
                        " Call the supplied evidence tool once with the exact IDs in the request.",
                        None, RESEARCH_TOOLS[job.role])
        request = {
            "question": question, "task": job.question, "round": round_number,
            "version_ids": ids, "keep": locked,
        }
        try:
            data = (await runner(subject, json.dumps(request), context=context, max_turns=1)).final_output
            summary_agent = agent(label, (
                researcher_instructions[job.role] +
                " Summarize the supplied tool result. Use the exact returned source IDs. "
                "Explain unresolved questions and do not claim a launch test. "
                "A lack of notes alone is not a compatibility determination."
            ), Finding)
            finding = (await runner(summary_agent, json.dumps({
                **request, "tool_result": data, "valid_sources": sorted(context.seen),
            }), context=None, max_turns=1)).final_output
            citations = [sid for sid in finding.sources if sid in context.seen]
            finding = Finding(summary=finding.summary, sources=citations, gaps=finding.gaps)
        except Exception as exc:
            finding = Finding(summary=f"{label} could not finish ({type(exc).__name__}).",
                              sources=[], gaps=["This research task did not finish."])
        trace.append({
            "agent": "Lead", "name": "dispatch_research",
            "args": {"researcher": label, "question": job.question},
            "result": finding.model_dump_json(), "round": round_number,
            "started_at": start, "ended_at": now(),
        })
        source_ids.update(context.seen)
        collected.extend(context.evidence)
        return finding

    findings = list(await asyncio.gather(*(run_job(job, 1) for job in plan.jobs)))
    review = agent("Lead review", (
        "Review the parallel findings against the question. Return one targeted follow-up job "
        "only if a specific missing piece can be retrieved with the local tools. A conflict "
        "without an examined requested alternative is actionable. A missing launch test or "
        "out-of-scope mod is a limitation, not a reason to dispatch. Return jobs=[] when enough "
        "evidence is present. The follow-up runs in a fresh context, so include exact details and IDs."
    ), Review)
    checks = [entry["data"] for entry in collected if entry["tool"] == "check_pack"]
    needs_options = next(
        (check for check in checks if check.get("conflicts") or check.get("missing")),
        None,
    ) if plan.wants_changes else None
    review_input = {
        "question": question, "findings": [f.model_dump() for f in findings],
        "version_index": index, "recorded_checks": checks,
        "missing_requested_alternatives": bool(needs_options), "keep": plan.keep,
    }
    review_started = now()
    reviewed = (await runner(review, json.dumps(review_input), context=None, max_turns=1)).final_output
    follow_up = reviewed.jobs[:1]
    if needs_options:
        # A requested fix remains unanswered until a candidate search has run.
        follow_up = [Job(
            role="dependencies",
            question=f"Find the smallest set of recorded changes that resolves the pack. Keep these mods fixed: {plan.keep}.",
            version_ids=list(needs_options["selected"].values()),
        )]
    trace.append({
        "agent": "Lead", "name": "review_evidence",
        "args": {"completed_tasks": len(findings)},
        "result": json.dumps({"follow_up": [job.model_dump() for job in follow_up]}),
        "round": 1, "started_at": review_started, "ended_at": now(),
    })
    if follow_up:
        findings.append(await run_job(follow_up[0], 2))
    trace.sort(key=lambda event: event["started_at"])
    if not source_ids:
        return "The researchers did not retrieve enough evidence to answer. Try an exact mod version from the catalog.", trace

    writer = agent("Writer", (
        "Answer the user's question using the supplied findings and citations. Use a precise "
        "headline, up to five short cited findings, and plain-language limits. Every factual "
        "finding must cite one or more supplied source IDs. Do not cite URLs or IDs not "
        "provided. Quote exact versions where necessary, preserve user's locked versions, "
        "only propose alternatives returned by find_alternatives, and do not claim a pack launched, rendered or performed well. An absent constraint "
        "in the registry is only absence in the captured metadata. If findings disagree, "
        "surface the disagreement. State plainly when evidence cannot answer."
    ), Report, language=language)
    report = (await runner(writer, json.dumps({
        "question": question, "findings": [f.model_dump() for f in findings],
        "allowed_sources": [CATALOG.evidence[s] for s in sorted(source_ids)],
        "tool_evidence": collected,
    }), context=None, max_turns=1)).final_output
    try:
        return render_report(report, source_ids, CATALOG), trace
    except ValueError:
        fallback = Report(
            headline="Retrieved evidence",
            findings=[Statement(text=f.summary, sources=f.sources) for f in findings if f.sources],
            limitations=["The report could not be cited reliably. The sourced research findings are shown above."],
        )
        return render_report(fallback, source_ids, CATALOG), trace
