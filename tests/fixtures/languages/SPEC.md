# What counts as a code unit

Ground rules for the non-Python parsers. These fixtures are the spec the parser
is graded against, so the eligibility rule has to be stated once, here, rather
than re-invented per language.

## The rule

> **A unit is a named declaration that owns a body span.**

"Owns a body span" means the declaration introduces a region of source that is
worth retrieving on its own — the thing an agent asking *"where is X
implemented?"* wants back. A one-line binding is not that; returning it costs a
serial number, an embedding, and a slot in the result list while answering
nothing.

## Eligible

| Construct | Why |
|---|---|
| function, method, constructor, destructor, getter/setter with a body | the canonical case |
| class, struct, interface, trait, enum, protocol, object/module with a member body | "where is this shape defined" is a real query |
| a binding whose right-hand side is *syntactically* a function literal — `=>`, `function`, `func`, `fn` | in JS/TS/Go this is the dominant way to declare a function; the binding supplies the name |
| a named function expression, even nested inside another function | it has a name and a body |

## Not eligible

| Construct | Why |
|---|---|
| fields, properties, stored constants, class attributes | no body to retrieve |
| a binding whose right-hand side is a call or a scalar (`const limiter = makeLimiter(4)`, `const MAX = 5`, `var ErrX = errors.New(...)`) | the body being named lives elsewhere; the binding is a reference |
| object/array/map literals bound to a name | a value, not a declaration of a named construct. Methods *inside* one are still units |
| bare prototypes and forward declarations (`void submit(Task);`) | the definition is the unit; emitting both duplicates the symbol |
| type aliases without a body (`using TaskFn = void (*)(void *);`, `type Loader<T> = (k: string) => Promise<T>;`) | one line, no span |
| single-line macros (`#define LOG_SCOPE(name) ...`) | no span, and expansion is not retrievable |
| `impl` blocks, `namespace`, `package` | containers, not units — their members are the units |
| computed properties **without** a body | same as fields |

Note that computed properties **with** a body (Swift `var count: Int { ... }`,
C# `public int Count { get { ... } }`) *are* eligible: they have a span.

## Why this rule and not another

The Python path already implements exactly this. `parser.py` walks the AST and
emits units only for `FunctionDef`, `AsyncFunctionDef` and `ClassDef`; a
module-level constant, a class attribute, and `f = lambda x: x` produce nothing.
Making the generic path agree is not a fresh design choice — it is the contract
the tool already ships. A cross-language index whose unit granularity depends on
the language would make serials, `--limit`, and score comparisons meaningless.

The one deliberate departure is the function-literal binding. Python's `lambda`
is a marginal one-expression form, while `const f = () => {}` is how JavaScript
and TypeScript declare most functions. Excluding it would lose the majority of
units in the two languages the audit found most broken.

## Tiers

Every expected entry is `core` or `stretch`.

- **core** — a competent scanner that only ever looks at *one line at a time*
  must find it. If the name sits on the claimed line, it is core. Nesting depth,
  indentation, and a preceding `return` do not make something stretch.
- **stretch** — genuinely needs cross-line context: the name is not on the
  declaration's first line (a C++ `template <typename T>` header, a multi-line
  declaration broken before the identifier), or the kind cannot be told apart
  from a sibling construct without knowing the enclosing scope.

`core` entries are required. `stretch` entries that the parser does not reach
are recorded as documented known limits rather than silent gaps.
