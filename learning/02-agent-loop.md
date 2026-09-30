# Phase 02 — From Chatbot to Agent (Tools + LangGraph)

**Code:** `agent/tools.py`, `agent/graph.py`, `agent/cli.py` (`do`)

## The one-paragraph explanation

A chatbot only *talks*. An **agent** *acts*: it uses **tools** (read a file,
write a file, run a command), looks at the **result**, and **decides what to
do next** — including trying again when something fails. The LLM is the brain,
tools are the hands, and the loop around them (a LangGraph graph) makes the
two an agent.

## The graph

```
 retrieve ──► plan ──► generate ──► write ──► verify ──► END (passed)
                         ▲                      │
                         └──── lookup ◄─────────┘ (failed, tries left)
                                                         │
                                         CLI shows DIFF ─► human: keep or revert?
```

LangGraph in three ideas:

| Idea | In the code | Plain English |
|---|---|---|
| **State** | `AgentState` (TypedDict) | one shared notebook every step reads and writes |
| **Node** | `retrieve_node`, `generate_node`, ... | a normal function: gets state, returns what it changed |
| **Edge** | `add_edge`, `add_conditional_edges` | "what runs next?" — conditional = a decision |

The most important function is `after_verify()`: it looks at the result and
chooses between "done" and "try again". That decision is the agent.

## Design decisions (and why)

1. **Language-agnostic verification.** `VERIFY_RULES` in `tools.py` maps a
   marker file to a checker: `pubspec.yaml → dart analyze`, `go.mod → go vet`,
   `Cargo.toml → cargo check`… New tech stack = one new row.
2. **Safety.** `safe_path()` refuses paths outside the project. The original
   file is kept in state; nothing is kept without approval.
3. **A missing checker is not bad code.** Exit code 127 ("command not found")
   stops the loop — otherwise the model "fixes" correct code three times.
4. **Errors + facts, not errors alone (the `lookup` node).** When the analyzer
   says `The getter 'logoutUrl' isn't defined`, feeding that back made the
   model invent the same name again. `lookup` searches the index for each name
   in the error and replies with facts: "`AppConfig` is defined in
   lib/config/app_config.dart" or "`logoutUrl` does NOT exist — don't use it".
   **A retry only helps if the model gets new information.**
5. **Model choice matters.** A code-specialised model (`qwen2.5-coder:7b`)
   followed "keep everything else unchanged" far better than a general 8B one.
6. **Specific tasks beat vague ones.** "Add a logout method" invents an API
   that doesn't exist; "add logout() that resets cnt and logs with AppLogger"
   works. When something is missing, the agent adds a `TODO` placeholder.

## Try it

```bash
python -m agent.cli do "Add a toJson() method that returns id, name and email" \
    --file lib/models/user.dart
```

## Check your understanding

- What if `after_verify` always returned "retry"? (Infinite loop — hence
  `MAX_ATTEMPTS`, and LangGraph's recursion limit.)
- Why is the file written to disk *before* verify?
- Why store `original` in the state instead of re-reading the file at the end?
- How would you add support for a Java/Maven project?
