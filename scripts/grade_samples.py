"""Run the three public prompts and the same model's no-tool baselines."""
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agents import Agent, Runner
from httpx import ASGITransport, AsyncClient

from app import app
from research import MODEL, MODEL_NAME, settings

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = json.loads((ROOT / "data" / "examples.json").read_text(encoding="utf-8"))


async def run_example(client, example):
    start = time.perf_counter()
    # instructions=None and tools=[] leave only the exact user message.
    baseline = Agent(name="Baseline", model=MODEL, model_settings=settings(), instructions=None, tools=[])
    response, comparison = await asyncio.gather(
        client.post("/chat", json={"message": example["question"]}),
        Runner.run(baseline, example["question"], max_turns=1),
    )
    response.raise_for_status()
    payload = response.json()
    elapsed = round(time.perf_counter() - start, 2)
    return {
        **example, "seconds": elapsed, "agent_answer": payload["response"],
        "baseline_answer": comparison.final_output, "tool_calls": payload["tool_calls"],
    }


async def main():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://local") as client:
        results = await asyncio.gather(*(run_example(client, example) for example in EXAMPLES))
        clarification = (await client.post("/chat", json={"message": "Will it work?"})).json()
    output = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL_NAME, "examples": results, "clarification": clarification,
    }
    target = ROOT / "data" / "sample-runs.json"
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for example in results:
        trace = example["tool_calls"]
        print(example["id"], example["seconds"], "s,", len(trace), "trace events")
        print(example["agent_answer"])
        print("BASELINE:", str(example["baseline_answer"])[:430])
    print("CLARIFICATION:", clarification["response"], "events=", len(clarification["tool_calls"]))
    conflict, repair, external = results
    for example in results:
        first_wave = [
            item for item in example["tool_calls"]
            if item["name"] == "dispatch_research" and item["round"] == 1
        ]
        assert len(first_wave) == 3, example["id"]
        assert max(item["started_at"] for item in first_wave) < min(item["ended_at"] for item in first_wave)
        assert "[1]" in example["agent_answer"] and all(item["agent"] for item in example["tool_calls"])
    assert "0.5.11" in conflict["agent_answer"] and "0.8.13" in conflict["agent_answer"]
    assert "0.8.13" in repair["agent_answer"] and "Indium" in repair["agent_answer"]
    assert any(word in repair["agent_answer"].lower() for word in ("remove", "drop"))
    assert any(
        option["selected"] == {"iris": "bAo1Qhte", "sodium": "SMxNOGZ6"}
        for item in repair["tool_calls"] if item["name"] == "find_alternatives"
        for option in json.loads(item["result"])["options"]
    )
    assert any(item["name"] == "find_alternatives" and item["round"] == 2
               for item in repair["tool_calls"])
    assert "Fabric API" in external["agent_answer"]
    assert any(
        item["name"] == "check_pack" and any(
            d["name"] == "Fabric API" and d["version_id"] is None
            for d in json.loads(item["result"])["external_requirements"]
        )
        for item in external["tool_calls"]
    )
    assert not clarification["tool_calls"] and "?" in clarification["response"]


if __name__ == "__main__":
    asyncio.run(main())
