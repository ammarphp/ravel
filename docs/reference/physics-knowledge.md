# Physics knowledge in the existing research graph

`ravel.workflow.physics_knowledge` retrieves located source statements, conventions,
procedures and exploratory hypotheses. The source index is an immutable ordinary
JSON input. Research-cycle history, premise revisions, hypotheses, experiments,
approval and evidence remain owned by the existing research controller. No second
research journal or experiment scheduler is introduced.

A request has `schema_version: 1`, an exact `knowledge` file pin
(`path`, `sha256`, `size`) and a query containing `text`, `tags`, `roots`, `domain`
and `max_nodes`. Literal tags or text locate candidate nodes; explicit roots and
requires/contradicts closure preserve necessary conventions and conflicting
assertions. This is deterministic retrieval, not a claim of semantic equivalence.
A restrictive node limit refuses an incomplete dependency/conflict slice.

An index has `schema_version`, `id`, `sources`, `nodes`, and `edges`. Sources carry
an exact file pin, citation, version, text/binary format and optional derived-source
parent IDs. Text evidence identifies an exact line range, excerpt SHA256 and
human locator. Original PDFs or raw HTML can be retained as binary parents of a
located text extraction. This binds their custody, not the correctness of an OCR
or extraction operation. Fact/convention/procedure nodes require located evidence;
hypothesis nodes, including an entirely exploratory index, can have no citations.

Nodes retain their statement, tags, domain, conventions, applicability, equations
(expression/unit/basis/domain), evidence and stable test obligations. Edges retain
requires, contradicts or motivates relations and explicit source-assertion,
located-source-conflict or exploratory assessment. An edge documents an assessment;
it is not an independent reviewer vote. A conflicting imported assertion remains
retrievable alongside its counter-source rather than silently disappearing.

```python
from ravel.workflow import physics_knowledge
pins = physics_knowledge.input_pins(request, base)
packet = physics_knowledge.retrieve(request, base)
# packet['premises'] matches existing research_cycle premise rows.
# Keep the full node/domain/conventions/applicability and packet digest in the
# research-cycle binding so a changed convention reopens dependent questions.
```

`source_inventory` contains the index and every declared source/derivation parent,
not just selected excerpts. `selection` retains selected IDs/reasons, the full
omitted-node census and dependency completion. `contradictions` and
`test_obligations` use stable IDs. Unmatched domain dependencies are expressly
labelled. Retrieval does not certify equations, model applicability or the truth
of a cited statement, and it never requires a hypothesis's predicted outcome to
be established first.

The existing AgentHost offers `physics-knowledge` with
`parameters: {"request_input": "<bound-input-id>"}`. Every expanded graph/source
pin must also be present in that node's explicit inputs. Source-aware retrieval
must retain its nonblind context classification. The kernel source is part of
Host identity, so cached graph output must not bypass a changed implementation.
No model, network, native process or scientific worker is invoked by this action.

A retrieved JSON packet can feed `scientific_context` as an ordinary API/example
source or `native_construction.support_sources` as located construction context.
Existing routine/reference/API/runtime obligations remain in force. A support
file pin alone is not transitive authentication of the packet's referenced files;
use `input_pins` and retain the full graph for execution custody.

The optional `check(packet, check_id, inputs, base)` executes only three named
bounded algebra checks selected by an obligation: coherent supplied-amplitude
square, ordered two-beam spin/final-state prefactor, and on-shell
angle-independent two-body width. It rebinds the entire retrieval packet before
and after its computation. Units, complete-amplitude conventions, same helicity/
colour state and threshold are explicit. The coherent contraction uses exact
Fractions of supplied binary values before binary64 reporting; the width uses
ordinary floating point without a new forward-error or calibration claim.
Nonfinite/nonrepresentable results refuse; exact zero/cancellation/threshold
remain valid. Gas collision-pair rates, arbitrary symbolic expressions, angular
integration, loops, detector efficiencies and inference are outside these checks.

The private prototype's primary FERMIACC method transfer is typed field/
interaction/topology hypotheses and an explicit full-theory/executable-benchmark
mapping. Its current bounded public-code lookup found no paper-linked repository;
no FERMIACC implementation was ported. Diagrammatica's released HEPTAPOD navigator
and theory procedures are inspected source inspiration, not executed backends.
One actual located conflict concerns an extra identical-initial-particle half
versus the PDG ordered-beam flux. The check distinguishes that observable from
final phase-space factorials. Primary papers/code remain separately attributed;
portable tests use fabricated source documents, not an ignored local corpus.

HVT summary basis/version/branching conventions, toponium signed heavy-Higgs interference,
and semi-visible-jet threshold/shower/response hypotheses are positive consuming examples. They
leave the actual source-summary, amplitude/template, dark-shower, detector,
likelihood and independent research-efficacy obligations open.

A null check names a pending obligation with no executable check. `check()` requires an explicit supported string and a selected named obligation; null/unknown identities never dispatch a width or create check evidence. Source-free hypotheses remain admissible.
