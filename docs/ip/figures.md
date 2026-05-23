# Draft Figures

These are private draft figures for later patent drafting. They use Mermaid so
they can be rendered into drawings later.

## Figure 1: Resolve-Before-Context Pipeline

```mermaid
flowchart TD
    A["Directive-bearing context source"] --> B["Renderer"]
    B --> C["Directive registry"]
    C --> D["Resolver dispatch"]
    D --> E["Local commands, files, services, memory"]
    E --> F["Schema validation and trust gates"]
    F --> G["Redaction"]
    G --> H["Resolved assistant context artifact"]
    H --> I["AI assistant session starts with live facts"]
```

Narrative: A source document containing directives is resolved before an
assistant receives it. The assistant receives a completed context artifact
rather than instructions to discover state.

## Figure 2: Directive Registry Metadata

```mermaid
flowchart LR
    A["DirectiveSpec"] --> B["Renderer dispatch"]
    A --> C["LSP completion and hover"]
    A --> D["Doctor checks"]
    A --> E["Static graph metadata"]
    A --> F["Prefetch eligibility"]
    A --> G["Output schema validation"]
    A --> H["Trust reporting"]
```

Narrative: A single directive specification defines callable behavior, argument
surface, safety flags, cacheability, and schema constraints. The same metadata
is reused across runtime and tooling surfaces.

## Figure 3: Static Graph and Trust-Gated Prefetch

```mermaid
flowchart TD
    A["Context source"] --> B["Static directive graph"]
    B --> C["Graph nodes with directive metadata and resources"]
    C --> D["Rule match or adaptive candidate selection"]
    D --> E{"Eligible?"}
    E -- "No: mutating, unsafe, uncacheable, or no cache semantics" --> F["Skip with structured reason"]
    E -- "Yes" --> G["Resolve candidate directive"]
    G --> H["Validate output schema"]
    H --> I["Write session, TTL, or persistent cache"]
    I --> J["Later render reads warmed value"]
```

Narrative: Prefetch execution is based on a static representation of the context
source and registry-driven safety metadata. The system warms only authorized
cache entries.

## Figure 4: Cited Synthesis Gate

```mermaid
flowchart TD
    A["Source files"] --> B["Line-numbered source bundle"]
    B --> C["Model drafter"]
    C --> D["JSON claims with source id, line range, quote"]
    D --> E{"Quote appears in cited line window?"}
    E -- "No" --> F["Drop claim or conflict"]
    E -- "Yes" --> G["Accept grounded claim"]
    G --> H["Redact output"]
    H --> I["Cited synthesis result"]
```

Narrative: The model is not treated as an authority. Generated claims survive
only if the cited quote exists in the cited source lines.

## Figure 5: Workspace Memory and Federation

```mermaid
flowchart TD
    A["Checkpoints"] --> C["Mneme update"]
    B["Pythia recommendation logs"] --> C
    C --> D["Workspace-hashed narrative memory"]
    D --> E["Local @memory directive"]
    D --> F["Federation manifest subscription"]
    F --> G["Alias-scoped federated narrative digest"]
    G --> H["Resolved context artifact"]
```

Narrative: Per-workspace memory is generated from checkpoints and recommendation
logs, then optionally exposed to other workspaces through narrative-only
subscriptions.

## Figure 6: Trust Boundary Surfaces

```mermaid
flowchart LR
    A["Resolver output"] --> B["Redaction"]
    C["Model prompt"] --> B
    D["HTTP response"] --> B
    E["Pythia log"] --> B
    B --> F["Trust boundary crossed"]
    G["Permission profile"] --> A
    G --> C
    G --> D
    H["Audit log"] --> F
```

Narrative: Permission profiles, redaction, and audit logging operate at the
boundaries where local data may leave the resolver and enter assistant-visible
or externally visible surfaces.
