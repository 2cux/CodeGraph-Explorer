# Known Limitations

Each language supported by CodeGraph Explorer has specific limitations. All call edges are tiered as **confirmed**, **possible**, or **unresolved** — uncertainty never enters confirmed.

---

## Python (Production)

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| `dynamic getattr` / `setattr` calls | Unresolved — dynamic attribute access cannot be statically traced | Marked `unresolved`; agent should verify |
| Monkey patching at runtime | Unresolved — runtime modifications to classes/functions not captured | Marked `unresolved` |
| C extension modules | External — symbols in `.so`/`.pyd` files not indexed | Marked `external` |
| `eval()` / `exec()` usage | Unresolved — dynamic code execution not analyzed | Marked `unresolved` |
| Complex decorator chains | Possible — heavily nested decorators may produce heuristic matches | Marked `possible` if uncertain |
| LLM fallback for unparseable files | Heuristic — files with syntax errors use LLM-assisted extraction | Lower confidence; agent should verify |

---

## TypeScript & JavaScript (Beta)

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Complex type inference | Possible — `generic<T>` resolution limited | Marked `possible` for inferred types |
| Dynamic imports (`import()`) | Unresolved — runtime conditional imports not traced | Marked `unresolved` |
| Computed property access (`obj[key]`) | Unresolved — dynamic property access not resolved | Marked `unresolved` |
| `any`-typed receivers | Possible — method calls on `any` type use name-only matching | Marked `possible` |
| Callback heuristics | Possible — inline callbacks (`.then()`, `.map()`) use heuristic resolution | Marked `possible` |
| React props flow | Unresolved — parent-to-child prop data flow not statically traced | Marked `unresolved`; agent should verify |
| `eval()` not analyzed | Unresolved | Marked `unresolved` |
| Barrel export ambiguity | Possible — `export * from` re-exports with name conflicts use heuristics | Marked `possible` |

---

## Java (Beta)

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Overloaded methods | Possible — multiple signatures with same name not disambiguated | Marked `possible`; agent should verify signature |
| Interface multi-implementation | Possible — which implementation is called not forced confirmed | Marked `possible`; agent should verify |
| Dynamic proxies (`java.lang.reflect.Proxy`) | Unresolved | Marked `unresolved` |
| Reflection (`Method.invoke()`) | Unresolved — reflective calls not traced | Marked `unresolved` |
| Spring dynamic beans / `@Bean` factory methods | Possible — beans created at runtime not fully resolved | Marked `possible` |
| Spring AOP proxies | Unresolved — aspect-wrapped beans not statically visible | Marked `unresolved` |
| Annotation processing | External — compile-time annotation processors not analyzed | Marked `external` |
| Wildcard imports (`import java.util.*`) | Heuristic — resolved by name matching within known packages | Confidence reduced when ambiguous |

---

## Go (Beta)

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Interface satisfaction | Possible — which concrete type satisfies an interface not resolved | Marked `possible`; agent should verify |
| Embedded struct method promotion | Possible — methods promoted via embedding use heuristic resolution | Marked `possible` |
| `reflect` package calls | Unresolved | Marked `unresolved` |
| Generic type parameters (Go 1.18+) | Possible — generic function instantiation limited | Marked `possible` |
| cgo calls | External — C interop symbols not extracted | Marked `external` |
| Build tags / conditional compilation | Unresolved — only default build analyzed | Marked `unresolved` |
| Dynamic dispatch via function values | Possible — `var f func() = someFunc` pattern | Marked `possible` |
| Unknown receiver methods | Possible — method calls where receiver type is unresolved | Marked `possible` |

---

## C# (Beta)

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Extension methods | Possible — extension method resolution uses heuristic | Marked `possible` |
| `dynamic` keyword | Unresolved — runtime binding not statically analyzable | Marked `unresolved` |
| Reflection (`System.Reflection`) | Unresolved | Marked `unresolved` |
| Source generators | Unresolved — compile-time generated code not visible | Marked `unresolved` |
| Partial classes across files | Possible — partial class members may be missed if in unscanned files | Marked `possible` |
| LINQ expression trees | Possible — lambda expressions in LINQ chains use heuristics | Marked `possible` |
| Overloaded methods | Possible — multiple overloads not disambiguated | Marked `possible` |
| Full Roslyn semantic analysis | Not available — regex-based extraction only | Agent should verify complex type hierarchies |
| `async`/`await` state machine | Possible — compiler-generated state machine methods not extracted | May miss indirect calls through async continuations |

---

## General Limitations (All Languages)

| Limitation | Impact |
|------------|--------|
| Static analysis only | Runtime behavior, dynamic dispatch, and conditional execution paths not captured |
| External packages | Third-party library symbols not deeply indexed — marked `external` |
| Cross-language calls | No edges between different languages (e.g., Python calling C via FFI) |
| Generated code | Code generated at build time (protobuf, gRPC stubs, OpenAPI clients) not indexed unless output files are present |
| Minified/obfuscated code | Production bundles (`.min.js`) produce low-quality extraction |
| Large files | Files > 1MB may be skipped to maintain indexing performance |
| Syntax errors | Files with parse errors are skipped or use LLM fallback (Python only) |

---

## Understanding Edge Confidence Tiers

| Tier | Meaning | Agent Should... |
|------|---------|-----------------|
| **confirmed** | Static evidence supports this relationship (confidence ≥ 0.80) | Trust and use directly |
| **possible** | Heuristic or name-only match (confidence 0.40–0.79) | Verify before acting on it |
| **unresolved** | Cannot determine target (dynamic, external, or ambiguous) | Read the code directly |
| **external** | Target is in a third-party library | Use Context7 or docs for the library |
