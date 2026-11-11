# Fabric Mod Check

[Live Cloud Run service](https://fabric-mod-check-wsmvshdila-uc.a.run.app)

Fabric Mod Check helps Minecraft players and modpack maintainers investigate declared version conflicts before installing a pack. It covers **Minecraft Java 1.21.1 on Fabric** and four client mods: **Sodium, Iris, Indium and Continuity**.

**Research question:** Which exact version constraints prevent a selected mod list from being installed together, and which changes resolve the conflicts documented in the captured records?

## Run it

The project adapts the course's `agents-sdk-web` starter. It keeps FastAPI, SQLite chat sessions, the OpenAI Agents SDK with Gemini via LiteLLM, and the `/chat` response fields `response`, `session_id` and `tool_calls`.

Use Python 3.13 and [uv](https://docs.astral.sh/uv/). A Google Cloud project with Vertex AI enabled and Application Default Credentials (ADC) is required for model calls.

```sh
# Run the login command if you haven't configured ADC.
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=YOUR_COURSE_PROJECT_ID
uv run --locked --python 3.13 app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Choose an example, or open **Select versions from the snapshot**, pick versions, and press **Run investigation**. The research process below each report shows each tool's arguments, result, agent and timing. A follow-up in the same conversation can refer to the previous versions.

The default model is `vertex_ai/gemini-3.5-flash-lite`, inherited from the starter. `MODEL_NAME`, `VERTEX_LOCATION`, `PORT`, `HOST` and `SESSION_DB` can be set in the environment.

## Data and scope

[`data/catalog.json`](data/catalog.json) contains **37** captured version records: 22 Sodium, 12 Iris, 1 Indium and 2 Continuity. Each project's entry records the exact Modrinth API URL, and the file records the UTC capture time. The app ships with this snapshot and performs research against it without fetching Modrinth during a chat.

- [Modrinth version list API](https://docs.modrinth.com/api/operations/getprojectversions/): supported Minecraft releases and loaders, exact release IDs, dependency kinds, and exact dependency pins when declared.
- [Indium maintainer compatibility notice](https://modrinth.com/project/indium) and [Sodium 0.6 release notes](https://modrinth.com/mod/sodium/version/oZOSEhyy): attributed notes on Sodium's built-in Fabric Rendering API and Indium incompatibility.
- [`scripts/snapshot.py`](scripts/snapshot.py) reproduces the version collection. Run `uv run --locked python scripts/snapshot.py` to replace the snapshot from the public API. Preserve the supplied snapshot for grading against the examples below, or regenerate the example evidence after refreshing it.

The solver evaluates declared constraints for one release of each selected mod. It can find a minimum number of adds, removals or replacements **within the captured version catalog**. A required external project such as Fabric API remains an open requirement. Missing version constraints and metadata that looks compatible are insufficient to establish that the pack actually launches. No mod binaries are executed.

## Deep Research workflow

1. **Lead:** resolves names to snapshot version IDs, asks a focused clarification when inputs are ambiguous, and emits three distinct tasks in one planning turn.
2. **Researchers:** version, dependency and maintainer agents run concurrently via `asyncio.gather` with separate contexts. Each gets one bounded tool turn and one synthesis turn. Tools read the captured records and compute dependency conflicts in Python.
3. **Lead review:** reads the findings and permits one targeted follow-up in a fresh context. When the user asks for a fix and the first round finds a conflict, the follow-up searches alternative packs and honors locked mods.
4. **Writer:** synthesizes the evidence. Every factual bullet must cite IDs retrieved in this request. The server resolves IDs to source links and rejects unknown or unretrieved citations.

The chat response contains attributed `tool_calls` for the Researchers, plus Lead dispatch and gap review entries. The first-round dispatch intervals show whether the Researchers overlapped. There are at most two research rounds. A chat request has a 220-second deadline.

## Verify and reproduce

```sh
uv run --locked --python 3.13 python -m unittest discover -s tests -v
uv run --locked --python 3.13 python -m scripts.grade_samples
```

The first command tests conflict detection, alternatives, missing external data, parallel execution, follow-up, citation validation and the starter API contract. The second uses the real Vertex model and saves answers and timed traces in [`data/sample-runs.json`](data/sample-runs.json). For each comparison, the baseline uses the **same model, the same question, no system instructions and no tools**.

## Grader sample queries

Captured with `vertex_ai/gemini-3.5-flash-lite` at 2026-11-11T17:25:09+00:00. Times include the local HTTP handler and live model calls.

### 1. Compare conflicting pins

> On Minecraft 1.21.1 Fabric, can Iris 1.8.14 Beta 1 and Indium 1.0.35 share one Sodium version? Give both exact pins.

**Expected:** No single Sodium release satisfies both recorded pins. Iris 1.8.14 Beta 1 requires Sodium 0.8.13 (SMxNOGZ6). Indium 1.0.35 requires Sodium 0.5.11 (RncWhTxD).

**Data location:** `data/catalog.json → projects.iris.versions[bAo1Qhte].dependencies; projects.indium.versions[Z8VpxxGh].dependencies`

| Agent response | Same model without tools or system instructions |
| --- | --- |
| ## Iris 1.8.14 Beta 1 and Indium 1.0.35 cannot share a single Sodium version due to conflicting dependency requirements<br><br>- Iris 1.8.14 Beta 1 (version bAo1Qhte) depends directly on Sodium version SMxNOGZ6 (mc1.21.1-0.8.13-fabric). [1] [2]<br>- Indium 1.0.35 (version Z8VpxxGh) links to Sodium version RncWhTxD (mc1.21-0.5.11). [3] [4]<br>- Because Iris 1.8.14 Beta 1 and Indium 1.0.35 require contradictory pins for Sodium, they cannot share a single Sodium version under their current declarations. [4] [2] [3] [1]<br><br>## Limits<br>- External requirements and actual runtime behavior are outside the dataset.<br>- No launch or gameplay test was performed.<br><br>## Sources<br>1. [Iris 1.8.14-beta.1+1.21.1-fabric](https://modrinth.com/mod/iris/version/bAo1Qhte)<br>2. [Sodium mc1.21.1-0.8.13-fabric](https://modrinth.com/mod/sodium/version/SMxNOGZ6)<br>3. [Indium 1.0.35+mc1.21](https://modrinth.com/mod/indium/version/Z8VpxxGh)<br>4. [Sodium mc1.21-0.5.11](https://modrinth.com/mod/sodium/version/RncWhTxD) | **Yes**, Iris 1.8.14 Beta 1 and Indium 1.0.35 can share a single Sodium version. <br><br>Here are the exact pins required for that specific combination to work on Minecraft 1.21.1:<br><br>*   **Sodium:** `0.5.11+mc1.21` (or simply `0.5.11`)<br>*   **Iris:** `1.8.14-beta.1+mc1.21`<br>*   **Indium:** `1.0.35+mc1.21`<br><br>### Why this works:<br>Iris 1.8.14 Beta 1 was built against Sodium's `0.5.x` API series. Indium 1.0.35 is also specifically updated to support Sodium `0.5.11` on Minecraft 1.21.1, making `0.5.11` the exact version that satisfies both mods simultaneously. |

Observed: **10.25 s**, 18 trace events.

### 2. Keep Iris, fix the pack

> On Minecraft 1.21.1 Fabric, keep Iris 1.8.14 Beta 1. My other mods are Sodium 0.5.11 and Indium 1.0.35. What is the smallest change set that resolves the documented conflicts?

**Expected:** Keeping Iris fixed, replace Sodium 0.5.11 with 0.8.13 and remove Indium 1.0.35. Iris needs the newer pin; the Indium maintainer documents incompatibility with Sodium 0.6 and later, which incorporates the rendering API support. The result satisfies captured constraints, with launch testing out of scope.

**Data location:** `data/catalog.json → projects.iris.versions[bAo1Qhte]; projects.sodium.versions[SMxNOGZ6]; notes[N-INDIUM], notes[N-SODIUM]`

| Agent response | Same model without tools or system instructions |
| --- | --- |
| ## Conflict Resolution for Minecraft 1.21.1 Fabric with Iris 1.8.14 Beta 1, Sodium 0.5.11, and Indium 1.0.35<br><br>- A conflict arises because Iris 1.8.14 Beta 1 (version bAo1Qhte) requires Sodium version SMxNOGZ6, while Indium 1.0.35 (version Z8VpxxGh) strictly requires Sodium version RncWhTxD, creating contradictory dependency pins for Sodium. [1] [2] [3] [4]<br>- The smallest change set to resolve the documented conflict while keeping Iris 1.8.14 Beta 1 (version bAo1Qhte) is to update Sodium from version RncWhTxD to version SMxNOGZ6 and remove Indium version Z8VpxxGh. [1] [2] [3] [4]<br>- Sodium versions 0.6 and later include built-in Fabric Rendering API support, making Indium unnecessary and incompatible with newer Sodium releases. [5] [6]<br><br>## Limits<br>- This checks recorded metadata and selected maintainer notes. No launch or gameplay test was performed.<br>- External requirements such as Fabric API and actual runtime behavior are outside the dataset.<br><br>## Sources<br>1. [Sodium mc1.21-0.5.11](https://modrinth.com/mod/sodium/version/RncWhTxD)<br>2. [Sodium mc1.21.1-0.8.13-fabric](https://modrinth.com/mod/sodium/version/SMxNOGZ6)<br>3. [Indium 1.0.35+mc1.21](https://modrinth.com/mod/indium/version/Z8VpxxGh)<br>4. [Iris 1.8.14-beta.1+1.21.1-fabric](https://modrinth.com/mod/iris/version/bAo1Qhte)<br>5. [Sodium 0.6 Fabric Rendering API announcement](https://modrinth.com/mod/sodium/version/oZOSEhyy)<br>6. [Indium maintainer compatibility notice](https://modrinth.com/project/indium) | To resolve the documented conflicts with your current setup on Minecraft 1.21.1, the smallest change set is to **update Sodium from 0.5.11 to 0.6.0 (or newer)**. <br><br>### Why this is the smallest change set:<br>* **The Conflict:** Iris 1.8.14 Beta 1 is built for the new **Sodium 0.6.x** rendering API. Sodium 0.5.11 is incompatible with Iris 1.8.x, which is why you are experiencing a crash or conflict.<br>* **Indium:** Indium 1.0.35 is already fully compatible with Sodium 0.6.x on Minecraft 1.21.1, so it does not need to be changed or removed.<br><br>### Action required:<br>1. Remove `sodium-fabric-mc1.21.1-0.5.11.jar` from your `mods` folder.<br>2. Download and drop **Sodium 0.6.0** (or the latest 0.6.x patch for 1.21.1) into your `mods` folder. <br>3. Leave Iris 1.8.14 Beta 1 and Indium 1.0.35 as they are. |

Observed: **9.85 s**, 17 trace events.

### 3. Check Continuity

> For Minecraft 1.21.1 Fabric, does Continuity 3.0.0+1.21 require Fabric API, and can this snapshot tell me the exact Fabric API version to install?

**Expected:** Yes, Continuity declares Fabric API (project P7dR8mSH) as required. The version_id is null. The four-mod snapshot cannot name an exact Fabric API release.

**Data location:** `data/catalog.json → projects.continuity.versions[kSPJ4hQv].dependencies`

| Agent response | Same model without tools or system instructions |
| --- | --- |
| ## Continuity Dependency and Fabric API Version Status for Minecraft 1.21.1 Fabric<br><br>- Continuity version 3.0.0+1.21 declares a required dependency on the Fabric API. [1]<br>- The specific version_id for the required Fabric API dependency is null in the dataset. [1]<br><br>## Limits<br>- External requirements such as Fabric API can be reported when declared, but their versions and actual runtime behavior are outside the dataset.<br>- This checks recorded metadata and selected maintainer notes. No launch or gameplay test was performed.<br><br>## Sources<br>1. [Continuity 3.0.0+1.21](https://modrinth.com/mod/continuity/version/kSPJ4hQv) | **Yes, Continuity 3.0.0+1.21 requires the Fabric API.** <br><br>However, **this specific snapshot cannot tell you the exact Fabric API version** because Continuity’s `fabric.mod.json` file uses a range-based dependency for Fabric API rather than locking it to a single exact version. <br><br>Based on Continuity 3.0.0+1.21 for Minecraft 1.21.1, here is what you need to know:<br><br>1. **How to find the right version:** You should download the latest stable release of **Fabric API for Minecraft 1.21 / 1.21.1** (which at the time of writing is usually `0.102.0+1.21` or higher). <br>2. **Rule of thumb:** Always match the Minecraft version of the mods. Since you are playing on 1.21.1, download the Fabric API explicitly built for 1.21 (Fabric API generally maintains forward compatibility across minor `.1` updates within the same major version). <br><br>You can safely grab the latest 1.21 version of Fabric API from Modrinth or CurseForge alongside Continuity 3.0.0+1.21. |

Observed: **6.60 s**, 7 trace events.

**Clarification check:** The fresh-session query `Will it work?` returned:

> Could you please specify which mods and versions you would like to check for Minecraft 1.21.1?

It dispatched zero research tasks.

## Deploy and submit

1. Push the project root to GitHub. If the repository is private, add the course staff listed in the assignment.
2. In the course GCP project, [set up Cloud Run continuous deployment from GitHub](https://cloud.google.com/run/docs/continuous-deployment-with-cloud-build). Select the repository's main branch and the root `Dockerfile`. The image installs `uv.lock`, includes the two runtime data files and listens on Cloud Run's `PORT`.
3. Use a runtime service account with Vertex AI access and set `GOOGLE_CLOUD_PROJECT` to the course project. Set the Cloud Run request timeout to 300 seconds. A maximum of one instance is sufficient for grading and keeps follow-up chats on the same SQLite instance until it restarts. Make the service reachable to graders per the course instructions.
4. Open the deployed page, run all three example buttons and check their sources and tool traces. Put the verified service URL in `submission.json`'s `deploy_url`. Submit the **GitHub repository URL** in Canvas and keep the service running until grades are released.

The supplied `submission.json` already has the solo author's UNI and `research` path. Its deployment URL is the verified public Cloud Run service.
