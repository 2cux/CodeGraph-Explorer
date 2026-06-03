# Language Support

CodeGraph Explorer supports **6 languages** at varying maturity levels. All call edges are tiered as **confirmed**, **possible**, or **unresolved** — uncertainty never enters confirmed.

## Support Tiers

| Tier | Meaning | Confidence | Agent Guidance |
|------|---------|------------|----------------|
| 🟢 **Production** | Full confidence for agent use in production codebases | High — static evidence supports relationships | Trust and use directly |
| 🟡 **Beta** | Functional with known limitations | Medium — some edges tiered as possible/unresolved | Verify possible/unresolved edges before acting |
| ⚪ **Planned** | Not yet implemented | — | — |

## Language Status

| Language | Status | Extensions | Parser | Symbols | Imports | Calls | Frameworks |
|----------|--------|------------|--------|---------|---------|-------|------------|
| **Python** | 🟢 Production | `.py`, `.pyi` | AST (`ast` stdlib) | Full | Full | Intra-file + imported | FastAPI, Flask, Django |
| **TypeScript** | 🟡 Beta | `.ts`, `.tsx` | tree-sitter | Full | Named/default/namespace/barrel | Intra-file + imported | Express, Next.js, NestJS, React |
| **JavaScript** | 🟡 Beta | `.js`, `.jsx`, `.mjs`, `.cjs` | tree-sitter | Full | require/module.exports | Intra-file + imported | Express, Next.js |
| **Java** | 🟡 Beta | `.java` | tree-sitter | Full | Single/static/wildcard | Intra-file + package-local | Spring Boot |
| **Go** | 🟡 Beta | `.go` | Regex-based | Full | Package import | Intra-package + cross-package | Gin, Hertz |
| **C#** | 🟡 Beta | `.cs` | Regex-based | Full | using/using alias | Intra-namespace + cross-namespace | ASP.NET Core |

## Edge Confidence by Language

| Language | Confirmed Edges | Possible Edges | Unresolved Edges | External |
|----------|----------------|----------------|------------------|----------|
| Python | AST-resolved calls, imports | Decorator chains, LLM-fallback | `getattr`/`setattr`, `eval`/`exec` | C extensions |
| TypeScript | Direct imports, type-annotated calls | Generic inference, barrel re-exports | Dynamic imports, `obj[key]`, `any` receivers | npm packages |
| JavaScript | Direct requires, module.exports | Callback heuristics | Dynamic imports, computed properties | npm packages |
| Java | Direct imports, annotation DI | Overloaded methods, interface impls | Reflection, dynamic proxies, AOP | Maven/JDK libs |
| Go | Package imports, direct calls | Interface satisfaction, embedded methods | `reflect` calls, cgo, build tags | Go stdlib |
| C# | using imports, attribute routes | Extension methods, partial classes | `dynamic`, reflection, source generators | NuGet packages |

## Framework Support

| Framework | Language | Status | Supported Signals |
|-----------|----------|--------|-------------------|
| **FastAPI** | Python | 🟢 Production | Route decorators, dependency injection, path parameters |
| **Flask** | Python | 🟢 Production | Route decorators, view functions |
| **Django** | Python | 🟡 Beta | View heuristics, URL patterns |
| **Express** | TypeScript/JS | 🟡 Beta | Route handlers (`app.get/post/use`), middleware chains |
| **Next.js** | TypeScript/JS | 🟡 Beta | File-based routes (`page.tsx`, `route.ts`), API routes |
| **NestJS** | TypeScript/JS | 🟡 Beta | Controller decorators, `@Injectable` DI resolution |
| **React** | TypeScript/JS | 🟡 Beta | Component identification, hook detection |
| **Spring Boot** | Java | 🟡 Beta | `@RestController`, `@Service`, `@Repository`, `@Autowired` DI |
| **Gin** | Go | 🟡 Beta | Router groups, route handlers, middleware chains |
| **Hertz** | Go | 🟡 Beta | Router groups, route handlers, middleware chains |
| **ASP.NET Core** | C# | 🟡 Beta | `[ApiController]`, `[Route]`, `MapGet`/`MapPost`, constructor DI, `MapGroup` |

> **Route-to-handler** confirmed edges are separated from possible/unresolved. Uncertain relationships never enter confirmed.

## Known Limitations

For detailed per-language limitations, see **[KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md)**.

### General (All Languages)

- **Static analysis only** — runtime behavior, dynamic dispatch, and conditional execution paths are not captured
- **External packages** — third-party library symbols are marked `external`, not deeply indexed
- **Cross-language calls** — no edges between different languages (e.g., Python calling C via FFI)
- **Generated code** — build-time generated code (protobuf, gRPC stubs, OpenAPI clients) not indexed unless output files are present
- **Large files** — files > 1MB may be skipped to maintain indexing performance

### Beta Language Limitations

- **TypeScript/JavaScript**: Dynamic property access, callback heuristics, `any`-typed receivers, and React props flow are limited
- **Java**: Overloaded methods, interface multi-implementation, dynamic proxies, and Spring AOP proxies are not fully resolved
- **Go**: Interface satisfaction, embedded struct promotion, and reflect calls are limited
- **C#**: Extension methods, `dynamic` keyword, reflection, and source generators are not fully resolved. Regex-based extraction only (no Roslyn semantic analysis)

## Roadmap

Planned improvements:

1. TypeScript / JavaScript → production quality
2. Java → production quality
3. Go → production quality
4. C# → production quality
5. More framework route mapping (Ruby on Rails, Laravel, Fiber, Echo)
6. Cross-language call graph edges
7. Larger multi-language benchmark suite
8. Workspace-level indexing (monorepo support)
