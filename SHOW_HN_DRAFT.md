Title: Show HN: Perseus – Live Context Engine for AI Assistants

Body:
I built Perseus because I was tired of my AI assistants starting every session cold. Before any useful work could begin, they'd spend valuable turns asking me about my environment, what services were running, or where I left off. Static context files would rot almost immediately. Perseus fixes this.

Perseus is a pre-processor that resolves live environment state—like running Docker containers, file system changes, or the last checkpoint of a task—*before* it ever reaches your AI assistant's context window. Instead of instructions to go find facts, your assistant receives verified facts, eliminating the cold-start problem and making every session productive from the first turn.

It's written in Python 3.10+, has only one runtime dependency (`pyyaml`), and is MIT licensed. It’s designed to be assistant-agnostic, working with Claude Code, Cursor, Codex, Hermes Agent, Rovo Dev, or any markdown-reading agent.

**Key features:**
- **Live Context Resolution:** Dynamically injects up-to-date environment facts.
- **Session Recovery (Waypoints):** Preserves execution state across interruptions.
- **Multi-Agent Coordination:** Enables atomic task claiming and shared state via flat files.
- **Extensibility (Hephaestus):** Supports custom plugins, macros, and render pipeline hooks.
- **Tiered Context:** Optimizes token usage by providing relevant context on demand.
- **Performance:** 1,190x faster cold-to-warm render (578.7s to 0.486s) in real-world benchmarks.
- **Reliability:** Passes 14/14 hard gate tests, including swarm chaos and adversarial scenarios.
- **Token Efficiency:** 93% token reduction with 0ms P99 latency overhead.

Perseus is named for the Greek hero who used a mirror-shield to slay Medusa without meeting her gaze directly. The chaotic development environment is Medusa. The mirror is resolved context: you see the situation clearly without being paralyzed by it.

Perseus v1.0.0. All major development tasks complete. The mirror is ready.

GitHub: https://github.com/tcconnally/perseus
Website: https://perseus.observer