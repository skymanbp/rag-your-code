# How it runs, end to end

Four diagrams. The first is the loop a user or an agent actually lives in; the
rest open the three boxes inside it that are not obvious.

Every claim here is about code in this repository, not about a plan.

## 1 · The loop

```mermaid
flowchart TD
    A["/rag-your-code:index<br/>or  rag-your-code bootstrap ."] --> B["walk · parse · embed · write"]
    B --> C{"does search<br/>actually answer?"}
    C -- "no: refused, or the wrong unit" --> D["/rag-your-code:describe<br/>an agent writes what the code is for"]
    D --> E[["rag-your-code.descriptions.json<br/>committed sidecar"]]
    E --> B
    D -.-> F["describe promote<br/>optional: into the source, as a diff"]
    F -.-> B
    C -- "yes" --> G["/rag-your-code:search<br/>a question in plain language"]
    G --> H{"is any of this<br/>EVIDENCE?"}
    H -- "yes" --> I["ranked declarations<br/>path:line · span · matched words · source"]
    H -- "no" --> J["nothing, plus a reason<br/>and what to do about it"]
    J --> D

    style D fill:#fde68a,stroke:#b45309,color:#000
    style H fill:#bfdbfe,stroke:#1d4ed8,color:#000
    style J fill:#fecaca,stroke:#b91c1c,color:#000
```

The yellow box decides whether any of this is worth having, and nothing but a
model that has read the code can do it. Measured, it takes first-place accuracy
from 0.314 to 0.443 on this repository's own ruler.

The blue box is the one most retrieval does not have. It is why the red box
exists: an answer withheld with a reason beats a confident wrong one.

## 2 · Indexing

```mermaid
flowchart LR
    R[("repository")] --> W["walk<br/>index.ignore · index.suffixes<br/>index.max_file_bytes"]
    W --> P["parse<br/>15 languages, one rule table"]
    P --> U["CodeUnit<br/>id · path · kind · qualified_name<br/>signature · start/end line · source<br/>description · calls · imports"]
    D[["descriptions sidecar"]] -.-> U
    U --> V["embed<br/>signed-feature-hash — default, offline<br/>sentence-transformers — optional extra<br/>openai-compatible — an endpoint"]
    V --> J[(".rag-your-code/index.json<br/>plus a float32 sidecar with --compact")]
    J --> S{"stale?<br/>size and mtime per file,<br/>plus a build fingerprint"}
    S -- "a file changed" --> P
    S -- "settings changed" --> W
```

A unit's `description` is the field that carries vocabulary. Generated, it is
the identifier humanised, plus the signature, plus the author's docstring — so
it introduces **no word the source did not already contain**. That is the whole
reason the yellow box in diagram 1 exists.

The build fingerprint covers only the settings that change *what is indexed*.
Changing a result limit invalidates nothing; changing the vector width or the
suffix list invalidates everything, because an index built under those is not
stale — it is an index of something else.

## 3 · Answering, or not

```mermaid
flowchart TD
    Q["a question in plain language"] --> T["tokenise<br/>identifiers, numbers,<br/>CJK as overlapping bigrams"]
    T --> POST["posting lists<br/>every unit sharing any term"]
    POST --> BM["BM25F over five weighted fields<br/>name 8 · signature 4 · description 3<br/>relations 2 · body 1"]
    POST --> VEC["cosine<br/>only a semantic embedder may<br/>add candidates — search.vector_recall"]
    BM --> RANK["ranked candidates"]
    VEC --> RANK

    T --> EV["EVIDENCE, asked separately"]
    EV --> COV["coverage >= 0.40<br/>share of the query's discriminating<br/>words present anywhere in the index"]
    EV --> CON["concentration >= 0.28<br/>share of the query's rarity landing<br/>inside a SINGLE unit"]
    COV --> GATE{"both met?"}
    CON --> GATE
    RANK --> GATE

    GATE -- "yes" --> BUD["fit the budget<br/>search.max_chars, whole blocks;<br/>the first result is always kept"]
    BUD --> OUT["context an agent can paste<br/>path:line · score · matched words · source"]
    GATE -- "no" --> WHY["one of four reasons"]
    WHY --> W1["no_query_term_in_index<br/>ask in the code's vocabulary"]
    WHY --> W2["only_ubiquitous_terms_matched<br/>add a distinctive term"]
    WHY --> W3["too_little_of_the_query_matched<br/>rephrase, or write descriptions"]
    WHY --> W4["matched_terms_are_scattered<br/>the subject is probably not here"]

    style GATE fill:#bfdbfe,stroke:#1d4ed8,color:#000
    style WHY fill:#fecaca,stroke:#b91c1c,color:#000
```

Both bars are **ratios inside the query**, never thresholds on a score. A score
threshold is tied to whatever scale the ranking currently produces, and this
project has already had one stop meaning anything the moment BM25F changed the
scale.

A word counts as discriminating only while it stays under 5% of the corpus, and
that rule is derived from the corpus rather than from a stopword list — which
is what makes it work in a language nobody anticipated, and is also where it
degrades: across a large corpus of short undocumented methods, ordinary English
words fall under 5% and start counting as evidence.

Below 200 units both bars are eased in proportion. A ten-unit index cannot hold
the vocabulary of a sentence, and refusing its own questions would be worse
than answering them.

## 4 · The surfaces

```mermaid
flowchart LR
    subgraph plugin["Claude Code plugin — about 249 always-on tokens"]
        C1["/rag-your-code:index"]
        C2["/rag-your-code:search"]
        C3["/rag-your-code:describe"]
        C4["/rag-your-code:status"]
        SK["skill: rag-your-code<br/>fires when a question<br/>is about the codebase"]
    end
    subgraph cli["rag-your-code CLI"]
        X1["bootstrap · index"]
        X2["search · annotate"]
        X3["describe status/export/import/promote"]
        X4["config list/get/set/init/path"]
        X5["agent — JSON-lines, long-lived"]
    end
    C1 --> X1
    C2 --> X2
    C3 --> X3
    C4 --> X3
    C4 --> X4
    SK --> X1
    SK --> X2
    X5 -.-> AG(["a long-running agent"])
```

The `agent` surface speaks nine actions over JSON lines: `search`, `research`,
`neighbors`, `open`, `bootstrap`, `describe_pending`, `describe_put`,
`refresh`, `stats`. One subprocess, JSON in and JSON out, for a session that
does not want to pay process startup per query.

No hooks, no MCP server, no background daemon. The commands are the
deterministic entry point; the skill is the path that fires without being
asked, and it exists because a model that has to remember a command will not
use one.

## Where the numbers behind this live

[README §6](../README.md#6--benchmark-dashboard) publishes every figure with the
fingerprint of the corpus it was taken on, and
[benchmarks/README.md](../benchmarks/README.md) lists the six commands that
produce them. Nothing in this document is a figure you cannot re-derive.
