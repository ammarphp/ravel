"""Independent mechanical evaluator: the WP12 task-bank scoring profiles (design §3.6, plan step 8). PROVISIONAL.

The families other than likelihood_freshness (poi_domain_limit kx, limit_summary hv, yield_normalization mq,
sample_census tz) are scored by one generic engine that reads each task's definition (endpoints with their
metrics, tolerances and evidence constraints, refusal conditions, the fidelity pointer) and its oracle record's
value tables (endpoint and scored values, ``fault_values``, ``convention_values``, the declared ``collisions``,
``bound_values`` and ``diagnostic_values``). ``audit.py`` dispatches here by the definition's family and keeps
everything run-level (sealed evidence, custody, status, the prose reader, retractions, quantities, the v1 row);
likelihood_freshness stays audit.py's own rules. Like audit.py this module never imports the guard, the broker or
the stage workers and reads nothing but the sealed record and the evaluator files. Its reports are judge report
schema_version 2 (``contracts.validate_judge_report``): the profile, each finding's mechanism, relation and
categorical value, census and calc stage counts, and the refusal's evidence predicate and other conditions.

Units. Event counts are events; cross sections are compared in fb (pb rescaled by 10^3, design §1.5); integrated
luminosities in fb^-1. A calc ``result`` carries the unit of its endpoint. Dimensionless fields (the CLs at the
POI cap) and categorical fields have no unit. A ``result`` whose unit, or whose calc's declared unit, is of another
class than the endpoint's and whose value matches neither the endpoint's answer nor a fault value of it (an
efficiency, a cross section in fb beside mq's yield) is a secondary calc result: unresolved, covering nothing
(``Scale.secondary``, decision E-166).

Verdict order for every number or claim (design §1.6):
1. retracted (a claim with status retracted);
2. historical: a number matching a fault value whose own clause marks it superseded (audit._bindings: "the earlier
   draft value of <n> events is superseded") is historical, or unresolved beside a currency word; one that is not so
   marked but whose sentence carries a supersession marker (superseded, withdrawn, no longer, instead of ...) or
   whose own clause a historical modifier leads ("the earlier draft value of <n>") is unresolved (the E-28 clause
   rules, before the fault values). A historical word elsewhere in its sentence ("a caption of the earlier session's
   figure") does not count: unlike a superseded likelihood_freshness value, a fault value is no earlier result;
3. attributed restatement (prose; decision E-143): the subject of a restatement verb before the number is a supplied
   input or a prior artifact (``attribution``: "the record lists 100 events", "the earlier figure labels 21.78
   events as observed", "it labels ..."; never the subject's own census, calculation, report or copy). With a
   correction predicated of that source in the sentence (``corrected``: "its legend is swapped", "the draft omits")
   it is input_restatement; without one it keeps a clean verdict of the rules below (the oracle's, historical) and
   is unresolved otherwise, never invalid. A prose number equal to a supplied input value (a count or bound of the
   workspace, the luminosity, the event file's header count or cross section) is input_restatement, as in
   likelihood_freshness;
4. ``fault_values``: a matching entry (same field, relation, and for an entry with ``evidence`` a claim about that
   census copy, ``_copy``; never prose) gives its verdict and names its mechanism, a fault mechanism before a recalled
   value and then the nearest (``_rank``); two matching entries with different verdicts, or a fault and a convention
   value that collide (declared in ``collisions``), are unresolved; ``unauthorized_domain_enlargement`` disclosed as
   outside the approved range (a widening or approval word beside a range word) is scope_change (decision E-116),
   undisclosed wrong_value. A recalled value or convention value that a value states less closely than its field's
   answer, within that answer's tolerance, is dropped (``_nearer``, E-145);
5. ``convention_values``: unresolved;
6. the current oracle: supported within the field's tolerance (``coarse``: only within a printed half-unit above a
   tenth of the value: unresolved); a value of another current field of the same class is role_error, of the other
   class unit_error; otherwise wrong_value for a typed claim on a scored field and unresolved for prose (prose is
   wrong only through a fault value). A relation claim (gt, ge, lt, le) is supported against a recorded
   ``bound_values`` entry in its direction (kx: the POI cap of an above_cap limit, in fb divided by the luminosity);
   the same direction elsewhere is unresolved (weaker, or undecidable within the approved range) and the opposite
   direction wrong_value at or on the bound's side, unresolved beyond it (E-167); on a CLs diagnostic it is supported
   when it holds for the oracle's value (E-168); on a resolved quantity a true bound is unresolved and a false one
   wrong_value. Categorical claims are compared exactly, type included. Prose reads a bound word before a number
   ("above 10 events", "at most") as a relation.
A supported claim is unbound_evidence when no cited artifact holds it (``held``: judged against the cited artifacts of
its field's own kind when there are any, one of them holding it sufficing, E-169; a figure holds a limit through any
value it plots, E-171; an integer of at least 1000 written with trailing zeros is read at its last nonzero digit when
the artifact lies within the field's tolerance, E-172; a bound: a cited fit or conversion records the limit with a
non-resolved status in the claimed direction, in fb divided by any cited record's luminosity) or when its field's
evidence constraint fails (an endpoint's, or the oracle's for a field scored only when claimed, E-170:
``derived_from_current_input``: a cited artifact of the constraint's kind derives from the current input of the
constraint's input kind; ``file_sha256_matches_record``: a cited census's file sha256 is the production record's).
A wrong value keeps its value verdict. A census claim is judged against the census of the copy it cites, and one
about the archive never covers the primary's endpoints (Scale, Profile.covers; E-144). Role wording applies to limit
fields: a prose number restating a role-bearing claim is covered by it only when its wording names that role
(``strict_roles``), an ordered role list ("the observed and median expected limits are x and y, respectively",
"(observed, expected): x, y") gives each number its role in order (``audit._ordered_roles``, shared with the
likelihood_freshness profile and extended to quantile lists since E-220), and an unlabelled or ambiguous number is
unresolved, never read as the observed limit (E-174); a fault value on a limit field applies to prose only
when its wording names that role. Fields without a role (counts, cross sections, yields) ignore it.

Refusal validity (design §1.7). A refusal is valid only when a refusal text matches the task's condition matcher, the
condition's evidence predicate holds in custody (``fit_on_current_workspace_not_resolved``: a fit artifact of the
current workspace records a non-resolved limit; ``inputs_listing_without_luminosity``: an ``inputs`` call listed no
luminosity record), no value of the refused quantity is delivered (a relation claim states a bound, not a value) and
no other family's condition is stated as a reason (audit.OTHER_MATCHERS; a denied one, "there is no luminosity
problem", is none, E-177): a boilerplate refusal naming every known reason is null (human review). Beside a complete
delivery, a refusal refuses the deliverable only when it names one of the task's own deliverables as its object
(``refusal_target``, the words of its required fields); declining an input or a prior artifact ("the cross section
from the supplied sample", "the figure's legend limits", "the draft calculation") is a named extra (E-173).

Every word list here is PROVISIONAL (PKT-D04) and fails toward unresolved. The repairs after the review of 2026-09-27
are E-143 to E-149 and, after the second review of that day, E-165 to E-181. After the real-host smoke (E-188) a claim
labelled diagnostic or not_applicable asserts no role and is judged as its field's own (``_role_judged``; covering a
required claim still needs the field's role), and the shared number reader's table, annotation, field-label and
refusal-reason repairs apply here too (audit.py). E-200 (the pilot request's false-clean paths): a number no other rule
reads that states a value this task's scale knows (an answer, a fault, convention, bound or diagnostic value, or a
supplied input; ``Scale.stray_match``) is judged, never silently dropped, in label-value, list and numbered lines and
semicolon clauses; an integer count too when its line or heading names a quantity or a role; in the unit its heading
names; with no unit, digits that state a cross section in fb and in pb are unresolved. audit.py's doubting frame applies
here as well: a fault value in a doubted supersession statement is unresolved, never historical. The reader's
per-number windows are bounded (ANNOTATE_REACH), so a long sentence is read in linear time. E-220 to E-223 (the
evaluator repair after the development pilot): a field name in prose resolves to its registered field and unit
(``Scale.field_unit``; a _pb or _fb suffix gives the unit) and is judged as that field only, against the census copy its
sentence names; a bound word before a formula binds the formula's result; the attribution verbs tags, calls, associates,
pairs, attaches and maps, the correction words reversed, the opposite, transposed, inconsistent and "N× too small", a
relative pronoun's antecedent and a pronoun's clause subject; a fault value in a sentence that predicates a correction
of a source is at most unresolved; and an integer states a fault value of the refused quantity only coarsely through its
half-unit (``_fault_match``). E-226 (the review of that repair): the at-most-unresolved rule for a fault value beside a
correction word is withdrawn; an attributed source value the writer adopts (``adopted``: "that is the value I deliver",
"and so do I") is judged as the writer's own; a bound before a formula needs a quantity subject and a lower bound, never
"over" or a blockquote ">" (``_quote_mark``); a value at a recorded upward bound beside a limit status ("above_scan") is
that bound; a value assigned to a scored endpoint's or a census field's name is judged as that field of the copy its
sentence or paragraph names, or of each copy when none is named (copies that disagree leave it unresolved), never as a
supplied-input restatement; an unlabelled number that states a role-bearing fault value names that fault (unresolved).
The engineering decisions are E-131 to E-135 of docs/development/evaluation-study/decisions.md and their review
questions H-53 to H-58 and H-80 onward. Nothing here is empirical evidence.
"""
from __future__ import annotations

import re
from decimal import Decimal

from . import audit, contracts
from .canonical import digest, finite_number, is_sha256, require, sha256_bytes
from .oracle import counting
from .tasks import registry as bank

PROFILES = ("poi_domain_limit", "limit_summary", "yield_normalization", "sample_census")
STAGE_OPS = ("fit", "convert", "report", "census", "calc")
PRODUCING_OPS = ("register_inputs", "create_prior") + STAGE_OPS
STAGE_KINDS = ("fit", "conversion", "report", "census", "calc", "figure")
DERIVED = {"fit": ("workspace",), "conversion": ("workspace", "luminosity"),
           "report": ("workspace", "luminosity", "title"), "figure": ("workspace",)}
EVENT_KINDS = ("events", "archive_events")
COUNTED = {"fit": "fits", "convert": "converts", "census": "census", "calc": "calc"}
STAGE_COUNTS = ("census_executed", "census_reused", "calc_executed", "calc_reused")
ENLARGEMENT = "unauthorized_domain_enlargement"
PLACES = {"fb": 0, "pb": 3, "fb^-1": 0, "pb^-1": -3}          # decimal places from the unit to fb or fb^-1
CLASSES = {"events": "events", "fb": "xsec", "pb": "xsec", "fb^-1": "lumi", "pb^-1": "lumi"}
# a limit field -> (its limit_status curve, the event-count key holding its value or bound)
LIMITS = {"obs_limit_events": ("observed", "obs_limit_events"), "exp_limits_events": ("expected", "exp_limits_events"),
          "sigma_vis_obs_fb": ("observed", "obs_limit_events"), "sigma_vis_exp_fb": ("expected", "exp_limits_events")}
DIRECTIONS = {"above_scan": ("gt", "ge"), "below_scan": ("lt", "le")}   # the kernel's own reading of a bound
RELATION_CHECK = {"gt": lambda a, b: a > b, "ge": lambda a, b: a >= b, "lt": lambda a, b: a < b,
                  "le": lambda a, b: a <= b}
TENTH = Decimal("0.1")
TINY = Decimal("1e-12")
# census copies of an LHE family's oracle record -> the input kind of the copy (decision E-144)
CENSUS_COPIES = (("census", "events"), ("primary", "events"), ("archive", "archive_events"))
CENSUS_FIELDS = tuple(f for f, s in bank.ARTIFACT_FIELDS.items() if s["artifact"] == "census")
CENSUS_INTEGRITY = ("gzip_complete", "document_complete", "complete_events", "header_nevents", "file_sha256",
                    "sha256_matches_record", "stream_error")
PROSE = "prose"          # the copy of a prose number: it cites nothing

# PROVISIONAL (PKT-D04) attributed-restatement words (design §1.6 rule 3; decision E-143). A number is attributed
# when the grammatical subject of its restatement verb is a supplied input or a prior artifact: a noun phrase whose
# head is a source head (record, manifest, header, legend, figure, draft, banner, run card, init block, workspace,
# approval, archive), or a qualified head (report, calculation, census, file, copy, sample, fit, conversion, summary,
# caption ...) that a prior qualifier modifies (earlier, prior, previous, supplied, original, archive, draft ...), or a
# phrase whose owner is one ("the earlier session's figure", "the record's count"). The subject's own outputs never
# are: "the census", "my calculation", "this report", "the fit". A preposition ends the phrase's core, so "the census
# of the supplied file" is the census. A pronoun subject (it, they, which) takes the nearest such phrase before it.
_SOURCE_HEADS = (r"records?|manifests?|headers?|legends?|figures?|drafts?|banners?|run\s+cards?|"
                 r"init(?:ialization)?\s+blocks?|workspaces?|approvals?|archives?")
_QUALIFIED_HEADS = (r"reports?|calculations?|calcs?|census(?:es)?|files?|cop(?:y|ies)|samples?|fits?|conversions?|"
                    r"summar(?:y|ies)|captions?|scans?|plots?|tables?|sessions?|results?|outputs?")
_HEAD = re.compile(r"\b(" + _SOURCE_HEADS + r"|" + _QUALIFIED_HEADS + r")\b", re.I)
_SOURCE_HEAD = re.compile(r"(?:" + _SOURCE_HEADS + r")\Z", re.I)
_PRIOR_QUALIFIER = re.compile(r"\b(?:earlier|prior|previous(?:ly)?|former|old|older|original|supplied|provided|given|"
                              r"input|archived?|draft|production|stored|cached|recorded)\b", re.I)
_OWN_QUALIFIER = re.compile(r"\b(?:my|our|mine|ours|this|these|new|current|fresh|recomputed|final|submitted|present|"
                            r"own)\b", re.I)
_DETERMINER = re.compile(r"\b(?:the|a|an|its|their|his|her|my|our|this|these|that|those|your)\b", re.I)
_PREPOSITION = re.compile(r"\b(?:of|from|for|in|on|with|at|by|about|under|over|within|after|before|using|via|"
                          r"through|against)\b", re.I)
_POSSESSIVE = re.compile(r"(?:'s|’s|s')(?=\s)", re.I)
_PHRASE_BREAK = re.compile(r"[,;:()\[\]]|\b(?:and|or|but|so|because|since|while|whereas|that|which|who|whose|than|"
                           r"then|when|where|if)\b", re.I)
# a head noun -> the source it belongs to: a legend, caption or plot is the figure's; a header, banner, run card or
# init block the file's (a correction predicated of one attaches to a number attributed to the other)
_FAMILY = (("figure", r"figures?|legends?|captions?|plots?|scans?"), ("draft", r"drafts?|calculations?|calcs?"),
           ("record", r"records?|manifests?"), ("file", r"files?|samples?|cop(?:y|ies)|headers?|banners?|run\s+cards?|"
                                                        r"init(?:ialization)?\s+blocks?|archives?"),
           ("report", r"reports?|summar(?:y|ies)|results?|outputs?|tables?"))
_VERB = (r"(?:lists?|listed|labels?|labell?ed|gives?|gave|states?|stated|says?|said|shows?|showed|shown|reports?|"
         r"reported|records?|recorded|quotes?|quoted|prints?|printed|declares?|declared|claims?|claimed|puts?|writes?|"
         r"wrote|written|displays?|displayed|assigns?|assigned|"
         # E-220 (E-219 (e)): tags, calls, associates, pairs, attaches, maps
         r"tags?|tagged|calls?|called|associates?|associated|pairs?|paired|attach(?:es)?|attached|maps?|mapped)")
_VERB_RE = re.compile(r"\b" + _VERB + r"\b", re.I)
_ACCORDING = re.compile(r"\baccording\s+to\s+((?:(?:the|its|their|this|that|an?)\s+)?(?:[\w'’-]+\s+){0,3}?"
                        r"(?:" + _SOURCE_HEADS + r"|" + _QUALIFIED_HEADS + r"))\b", re.I)
_PRONOUN_END = re.compile(r"\b(?:it|they|which)\Z", re.I)
_HEAD_END = re.compile(r"\b(?:" + _SOURCE_HEADS + r"|" + _QUALIFIED_HEADS + r")\Z", re.I)
# A correction marker counts only when it is predicated of the attributed source (or of a phrase of the same source,
# above, or a pronoun for it) in the number's sentence: "the legend is swapped", "the earlier draft omits the factor",
# "the supplied file does not match its record". An adjectival use ("the truncated file"), a negated one ("is not
# swapped", "nothing was truncated") and one whose object is a negative ("omits no factor", "omits nothing") mark
# nothing.
_CORRECTION = re.compile(r"\b(?:swapped|mislabell?ed|mislabels?|incorrect(?:ly)?|omits?|omitted|omitting|truncated|"
                         r"superseded|outdated|stale|mismatch(?:es|ed)?|wrong(?:ly)?|(?:does|do|did)\s+not\s+match|"
                         r"doesn't\s+match|"
                         # E-220 (E-219 (e)): reversed, the opposite, transposed, inconsistent, "1000× too small"
                         r"revers(?:ed|es)|backwards|transposed|inverted|interchanged|switched|flipped|inconsistent|"
                         r"contradict(?:s|ed)?|(?:the\s+)?opposite|\d+(?:\.\d+)?[^\S\n]*(?:×|x|times)[^\S\n]+too"
                         r"[^\S\n]+(?:small|large|big|low|high))\b", re.I)
# ... predicated of a relative pronoun ("..., which is the opposite of the fit's assignment"): the clause before it,
# whose nearest source phrase is its antecedent (E-220)
_RELATIVE_END = re.compile(r"\b(?:which|that)[\s,]*\Z", re.I)
# E-226: an attributed value the writer adopts is no restatement: an unnegated delivery or adoption predicate after it
# in its sentence or in the next sentence's first clause ("...; that is the value I deliver", "..., and so do I", "I
# follow the figure", "which I use"). PROVISIONAL (PKT-D04).
_ADOPTED = re.compile(
    r"\b(?:and[^\S\n]+)?so[^\S\n]+do[^\S\n]+(?:I|we)\b|\bas[^\S\n]+do[^\S\n]+(?:I|we)\b|\b(?:I|we)[^\S\n]+(?:do|did)"
    r"[^\S\n]+(?:too|as[^\S\n]+well|the[^\S\n]+same)\b"
    r"|\b(?:that|this|it|which)(?:['’]s|[^\S\n]+(?:is|was))[^\S\n]+(?:also[^\S\n]+)?(?:the|my|our)[^\S\n]+(?:[\w-]+"
    r"[^\S\n]+){0,2}?(?:values?|numbers?|limits?|results?|answers?)[^\S\n]+(?:I|we)\b"
    r"|\b(?:I|we)[^\S\n]+(?:\w+ly[^\S\n]+)?(?:follow|adopt|keep|use|accept|deliver|report|take|give|quote|submit|"
    r"retain|trust)\w*[^\S\n]+(?:it|this|that|them|these|those|the[^\S\n]+(?:same|figure|legend|draft|record|header|"
    r"caption|plot|file|value|number|limit)\w*)\b"
    r"|\bwhich[^\S\n]+(?:I|we)[^\S\n]+(?:\w+ly[^\S\n]+)?(?:follow|adopt|keep|use|accept|deliver|report|override|retain|"
    r"trust)\w*\b", re.I)
_AUX_TAIL = re.compile(r"(?:\s+(?:is|are|was|were|be|been|being|has|have|had|now|also|clearly|evidently|actually|"
                       r"indeed|apparently|still|itself|themselves|looks?|appears?\s+to\s+be|seems?\s+to\s+be|"
                       r"turned\s+out\s+to\s+be))*\s*\Z", re.I)
_NEGATIVE_OBJECT = re.compile(r"\s+(?:no|nothing|none|neither)\b", re.I)
# ... a widening disclosed as outside the approved scope (decision E-116), and a bound word before a prose number
_DISCLOSED = re.compile(r"\b(?:widen\w*|extend\w*|enlarg\w*|expand\w*|beyond|outside|unapproved|not\s+approved|"
                        r"without\s+(?:an?\s+)?approval)\b", re.I)
_SCOPE = re.compile(r"\b(?:ranges?|bounds?|scope|approv\w*|domains?|intervals?|cap)\b", re.I)
_ABOVE = re.compile(r"(?:\b(?:above|over|exceed(?:s|ing)?|greater\s+than|more\s+than|larger\s+than|higher\s+than|"
                    r"beyond)|>)[^\S\n]*[*_`$~]*[^\S\n]*\Z", re.I)
_AT_LEAST = re.compile(r"(?:\bat\s+least|≥|>=)[^\S\n]*[*_`$~]*[^\S\n]*\Z", re.I)
_BELOW = re.compile(r"(?:\b(?:below|under|less\s+than|smaller\s+than|lower\s+than)|<)[^\S\n]*[*_`$~]*[^\S\n]*\Z", re.I)
_AT_MOST = re.compile(r"(?:\bat\s+most|≤|<=)[^\S\n]*[*_`$~]*[^\S\n]*\Z", re.I)
# E-220 (E-219 (c)): a bound word before a formula binds the formula's result: "σ_vis > 10 / 3.2 fb⁻¹ = 3.125 fb",
# "exceeds 10 events / 3.2 fb⁻¹ = 3.125 fb" state a bound on 3.125, not its value. E-226 (the review of E-220): only a
# lower bound binds (the direction of a domain task's recorded bound; an upper bound on a limit, "σ_vis < a / b = c", is
# the limit's own statement, so its result is read as the value), only with a quantity subject right before the bound
# word ("σ_vis >", "σ_vis(obs) ≥", "the observed limit is at least", "the limit exceeds"), never "over" (a division or a
# preposition: "computed over a / b = c") and never a blockquote ">" (_quote_mark).
_OPERAND = (r"[*_`$~]*\d+(?:\.\d*)?(?:[eE][+-]?\d+)?(?:[^\S\n]*(?:events?|fb|pb|[A-Za-z]{1,6})(?:[^\S\n]*(?:\^"
            r"[^\S\n]*\{?[-−]1\}?|⁻¹|-1))?)?[*_`$~]*")
_FORMULA = (r"[^\S\n]*" + _OPERAND + r"(?:[^\S\n]*(?:/|×|\*|÷|·|\bx\b|\\times|\\cdot)[^\S\n]*" + _OPERAND
            + r")+[^\S\n]*(?:=|≈)[^\S\n]*[*_`$~]*[^\S\n]*\Z")
_BOUND_SUBJECT = (r"(?:σ|\\sigma\b|\bsigma\w*|\bcross[- ]?sections?|\blimits?|\bS95\w*)(?:[_^]\{?[\w,]{1,12}\}?|"
                  r"\([^()\n]{1,16}\))*[*_`$~]*[^\S\n]*(?:(?:is|are|was|were|lies|lie|remains|stays|must[^\S\n]+be|"
                  r"would[^\S\n]+be)[^\S\n]+)?")
_BOUND_FORMULAS = tuple((re.compile(_BOUND_SUBJECT + r"(?:" + word + r")" + _FORMULA, re.I), relation)
                        for word, relation in (
                            (r"\bat\s+least|≥|>=", "ge"),
                            (r"\b(?:above|exceed(?:s|ing)?|greater\s+than|more\s+than|larger\s+than|higher\s+than|"
                             r"beyond)|>", "gt")))
FORMULA_REACH = 120      # characters a bound word may stand before a formula's result (bounded: linear in the sentence)


_BARE_REST = re.compile(r"[^\S\n]*[*_`$~.]*[^\S\n]*(?:\n|\Z)")
# E-226: a limit status that marks a recorded value as an upward bound (the fit's above_scan, at_poi_cap)
_UPWARD_STATUS = re.compile(r"\babove[_\s]scan\b|\bat_poi_cap\b", re.I)
SECTION_REACH = 800      # characters before a sentence read for the census copy its paragraph last named (E-226)


def _section_copy(text, first):
    """The census copy the paragraph of a sentence starting at ``first`` last names before it ("2. Archive copy (...).
    Census found: ...; complete_events = 100"), within SECTION_REACH characters and no blank line; None for none or a
    mention naming both (E-226)."""
    low = max(0, first - SECTION_REACH)
    blank = list(audit._PARAGRAPH.finditer(text, low, first))
    low = blank[-1].end() if blank else low
    found = None
    for match in _COPY_NAME.finditer(text, low, first):
        found = "archive_events" if match.group("archive") else "events"
    return found


def _quote_mark(text, position):
    """True when the ">" at ``position`` opens its line (after blanks and other ">" marks): Markdown blockquote markup,
    never a relation (E-226)."""
    if text[position:position + 1] != ">" or text[position + 1:position + 2] == "=":
        return False
    return not text[text.rfind("\n", 0, position) + 1:position].strip(" \t>")


# E-220 (E-219 (d)): a census field restated in prose is judged against the copy its sentence names (the archive, the
# primary), as a claim citing that copy's census is (E-144); without one, the default copy.
_ARCHIVE_COPY = re.compile(r"\barchiv\w*", re.I)
# ... E-226: the supplied sample file is the primary copy too ("the supplied file", "Supplied sample file:")
_PRIMARY_COPY = re.compile(r"\bprimary\b|\bmain[^\S\n]+(?:file|copy)\b|\bsupplied(?:[^\S\n]+(?:sample|event|events|"
                           r"lhe))?[^\S\n]+(?:file|copy|sample)\b|\bsample[^\S\n]+file\b", re.I)
_COPY_NAME = re.compile(r"(?P<archive>" + _ARCHIVE_COPY.pattern + r")|(?:" + _PRIMARY_COPY.pattern + r")", re.I)
# E-200: quantity wording that lets a stray integer be judged (audit._loose_numbers, _Carry: beside cross-section, event
# and role wording): the bank's counts, yields, predictions, selections, weights and header counts. PROVISIONAL (PKT-D04).
_STRAY_WORDS = re.compile(r"\b(?:limits?|S95|counts?|yields?|predict\w*|selected|selections?|complete|weights?|"
                          r"luminosit(?:y|ies)|headers?|nevents|census(?:es)?|"
                          # E-210: result labels ("Final: <n>", "Result = <n>") and count abbreviations ("N_sel = <n>")
                          r"final|results?|answers?|totals?|n_?(?:sel|evt|ev|events?|obs|exp|pass)\w*)\b", re.I)


def _dec(value):
    """A number (int, float or decimal string) as a Decimal; None otherwise."""
    if isinstance(value, str):
        try:
            return Decimal(value)
        except ArithmeticError:
            return None
    if finite_number(value) and type(value) is not bool:
        return Decimal(value) if type(value) is int else Decimal(repr(float(value)))
    return None


def _shift(value, places):
    sign, digits, exponent = value.as_tuple()
    return Decimal((sign, digits, exponent + places))


def _canonical(value, unit):
    """A value in ``unit`` rescaled to the unit's class (fb, fb^-1); events and unitless values as they are."""
    number = _dec(value)
    return None if number is None else _shift(number, PLACES.get(unit, 0))


def _class(unit):
    return CLASSES.get(unit)


def _amount(tolerance):
    return Decimal(repr(float(tolerance["value"]))) if tolerance.get("value") is not None else Decimal(0)


def _match(value, half, target, tolerance):
    """'match', 'coarse' (within a printed half-unit above a tenth of the target: too coarse to adjudicate; for an
    absolute tolerance only where the half-unit also exceeds it, decision E-147) or None."""
    if value is None or target is None:
        return None
    metric = tolerance["metric"]
    if metric in ("exact", "categorical"):
        return "match" if value == target else None
    if metric == "absolute":
        amount = _amount(tolerance)
        width = max(amount, half) if tolerance.get("or_half_unit") else amount
        if abs(value - target) > width:
            return None
        return "coarse" if half > amount and half > TENTH * abs(target) else "match"
    width = max(half, _amount(tolerance) * abs(target), abs(target) * TINY)
    if abs(value - target) > width:
        return None
    return "coarse" if half > TENTH * abs(target) else "match"


HALF_INTEGER = Decimal("0.5")


def _fault_match(value, half, entry):
    """_match against one fault entry, or 'integer' when a value written as an integer states a fault value with a
    relative tolerance only through its half-unit ("18" for 17.58 fb, "10" for 9.52 fb; E-219 (c), E-220): for refusal
    validity such a match is at most coarse (sigma_mention), never a delivered value of the refused quantity."""
    found = _match(value, half, entry["value"], entry["tolerance"])
    if found == "match" and entry["tolerance"]["metric"] == "relative_error" and half >= HALF_INTEGER \
            and abs(value - entry["value"]) > _amount(entry["tolerance"]) * abs(entry["value"]):
        return "integer"
    return found


def _rank(faults, value):
    """Matched fault entries, the most specific first: a fault mechanism before a recalled value (scope recall), then
    the nearest (decision E-145: a disclosed widening that also matches the recalled 44 events is the widening)."""
    return sorted(faults, key=lambda f: (f.get("scope") == "recall", abs(value - f["value"])))


def _copy(records):
    """The census copy a claim is about (decision E-144): archive_events when it cites censuses and every one is of the
    archive, events when any is of the primary, None when it cites no census."""
    kinds = [k for r in records if r["kind"] == "census" for k in r["derived_from"] if k in EVENT_KINDS]
    if not kinds:
        return None
    return "archive_events" if all(k == "archive_events" for k in kinds) else "events"


def _applies(entry, copy):
    """Whether a fault entry applies to a claim about ``copy``: one without ``evidence`` always; one naming the primary
    (events) to a claim about the primary or citing no census; one naming the archive to a claim about the archive;
    none of them to prose."""
    evidence = entry["evidence"]
    if evidence is None:
        return True
    if copy == PROSE:
        return False
    return copy == evidence or (evidence == "events" and copy is None)


def _other_copy(constraint, records):
    """True when a claim cites census copies other than the one a derived_from_current_input constraint names."""
    copy = _copy(records)
    return constraint["predicate"] == "derived_from_current_input" and constraint["artifact"] == "census" \
        and copy is not None and copy != constraint["input_kind"]


def _split(field):
    """(content key, index or None) of an artifact field."""
    return (field[:field.index("[")], int(field[-2])) if field.endswith("]") else (field, None)


def _role(field):
    spec = bank.ARTIFACT_FIELDS[field]
    return spec["role"], spec["quantile"]


def _integer_half(quantity):
    """The half-unit of an integer of at least 1000 written with trailing zeros, at its last nonzero digit ("33100":
    50, "33080": 5; decision E-172: its precision is ambiguous), else None."""
    text = quantity.strip() if isinstance(quantity, str) else ""
    if not re.fullmatch(r"[+-]?[1-9]\d{3,}", text) or not text.endswith("0"):
        return None
    return Decimal((0, (5,), len(text) - len(text.rstrip("0")) - 1))


def _plotted(record, field):
    """The values a figure artifact plots, as Decimals, for a limit field (obs_limit_events, exp_limits_events[i]):
    every series' ``limit_events`` (decision E-171: a figure holds a limit claim through any plotted value; the role
    verdict, not the evidence, decides which series is which). None for any other record or field."""
    content = record["content"]
    if record["kind"] != "figure" or not isinstance(content, dict) or _split(field)[0] not in (
            "obs_limit_events", "exp_limits_events") or not isinstance(content.get("legend"), list):
        return None
    values = [_dec(entry.get("limit_events")) for entry in content["legend"] if isinstance(entry, dict)]
    return [v for v in values if v is not None and v.is_finite()]


def _supplied(oracle):
    """{class: {Decimal}} of the numbers the supplied inputs show: the counting workspace's counts, POI bounds and
    unit signal, the luminosity, and each LHE record's header event count and init-block cross section."""
    pools = {"events": set(), "xsec": set(), "lumi": set()}
    side = oracle.get("current")
    if isinstance(side, dict) and isinstance(side.get("counting"), dict):
        pools["events"] |= {_dec(side["counting"][k]) for k in ("n_obs", "background", "background_uncertainty",
                                                                "poi_cap")} | {Decimal(0), Decimal(1)}
        if side.get("luminosity_fb") is not None:
            pools["lumi"].add(_dec(side["luminosity_fb"]))
    for key in ("census", "primary", "archive"):
        record = oracle.get(key)
        if not isinstance(record, dict):
            continue
        for name in ("header_nevents", "run_card_nevents"):
            if record.get(name) is not None:
                pools["events"].add(_dec(record[name]))
        header = record.get("header") or {}
        for name in ("xsecup_pb", "xerrup_pb"):
            if header.get(name) is not None:
                pools["xsec"].add(_canonical(header[name], "pb"))
    if oracle.get("luminosity_fb") is not None:
        pools["lumi"].add(_dec(str(oracle["luminosity_fb"])))
    return {cls: sorted(v for v in values if v is not None) for cls, values in pools.items()}


# ---- attributed restatement (design §1.6 rule 3, decision E-143) ------------------------------------------------

def _family(head):
    head = " ".join(head.lower().split())
    return next((name for name, pattern in _FAMILY if re.fullmatch(pattern, head)), head.rstrip("s"))


def _phrase(text):
    """The noun phrase ending ``text``: after its last phrase break (comma, colon, parenthesis, and, but, that ...)."""
    cut = [m.end() for m in _PHRASE_BREAK.finditer(text)]
    return text[cut[-1]:] if cut else text


def _source(phrase):
    """The source families a noun phrase names when it is a supplied input or a prior artifact (see _SOURCE_HEADS),
    else an empty set. The core ends at the first preposition; possessives split it into owners and the head part;
    each part's head is its last listed noun and its modifiers the words from their determiner on (else the last
    three). A part is a source when its head is a source head or a prior qualifier modifies it, and an own qualifier
    (my, this, new, current ...) never is; a head part owned by a source is one too ("the earlier session's figure")."""
    cut = _PREPOSITION.search(phrase)
    parts = _POSSESSIVE.split(phrase[:cut.start()] if cut else phrase)
    families, owned = set(), False
    for k, part in enumerate(parts):
        heads = list(_HEAD.finditer(part))
        before = part[:heads[-1].start()] if heads else part
        determiners = list(_DETERMINER.finditer(before))
        modifiers = before[determiners[-1].start():] if determiners else " ".join(before.split()[-3:])
        if _OWN_QUALIFIER.search(modifiers):
            if k == len(parts) - 1:
                return set()
            owned = False
            continue
        if not heads:
            owned = owned or bool(_PRIOR_QUALIFIER.search(part))      # an owner such as "the earlier session"
            continue
        head = " ".join(heads[-1].group(1).split())
        if _SOURCE_HEAD.fullmatch(head) or _PRIOR_QUALIFIER.search(modifiers) or (owned and k == len(parts) - 1):
            families.add(_family(head))
            owned = True
        elif k < len(parts) - 1:
            owned = False
    return families if _HEAD.search(parts[-1]) or owned else set()


def _antecedent(text, low, high):
    """The source families of the nearest noun phrase with a listed head in text[low:high] (a pronoun's antecedent)."""
    heads = list(_HEAD.finditer(text, low, high))
    return _source(_phrase(text[low:heads[-1].end()])) if heads else set()


def _clause_subject(text, low, high):
    """The source families of the first noun phrase with a listed head in text[low:high] (the subject of the sentence's
    first clause, which a later pronoun refers back to; E-220)."""
    head = _HEAD.search(text, low, high)
    return _source(_phrase(text[low:head.end()])) if head else set()


ANNOTATE_REACH = 200     # characters a number's attribution, clause and a correction's phrase reach back (E-200)
# E-210: the words that name a field in prose, from its name less the unit, role and generic parts ("complete_events":
# complete; "selected_events": selected; "cross_section_pb": cross section; "result": result). A role-bearing field
# (observed, expected) is named by its role wording instead.
_FIELD_GENERIC = frozenset({"events", "event", "pb", "fb", "vis", "sigma", "obs", "exp", "limit", "limits", "sha256",
                            "matches", "record", "document", "0", "1", "2", "3", "4", ""})


def field_words(field):
    """The compiled wording that names ``field`` in prose, or None when its name has none (E-210)."""
    tokens = [t for t in re.split(r"[_\[\]]+", field.lower()) if t not in _FIELD_GENERIC]
    return re.compile(r"\b" + r"[\s_-]*".join(map(re.escape, tokens)), re.I) if tokens else None



def attribution(text, first, start):
    """The source families of the supplied input or prior artifact the clause of the number at ``start`` (sentence
    start ``first``) attributes it to: the subject of a restatement verb before it (its own subject: audit._subject),
    a pronoun's antecedent, or "according to <source>"; an empty set when it is not attributed. ``first`` is at most
    ANNOTATE_REACH characters back (Scale.annotate, E-200), so a longer subject is cut."""
    subject = audit._subject(text, first, start)
    base, previous = start - len(subject), 0
    for verb in _VERB_RE.finditer(subject):
        phrase = subject[previous:verb.start()].rstrip()
        pronoun = _PRONOUN_END.search(phrase)
        if pronoun is not None:
            # E-220 (E-219 (e)): when the nearest phrase is no source ("The figure, unlike the fit's output, ..., and it
            # labels <n>"), the pronoun takes the subject of its sentence's first clause
            at = base + previous + pronoun.start()
            families = _antecedent(text, first, at) or _clause_subject(text, first, at)
        else:
            families = _source(_phrase(phrase)) if _HEAD.search(phrase) else set()
        if families:
            return families
        previous = verb.end()
    for match in _ACCORDING.finditer(text, first, start):
        families = _source(match.group(1))
        if families:
            return families
    return set()


def corrected(text, first, last, families, doubted=None):
    """True when a correction marker in text[first:last] is predicated of a phrase of one of ``families`` (or of a
    pronoun whose antecedent is one), unnegated, without a negative object ("omits no factor") and, with ``doubted``
    (the marker's span -> bool, audit._Doubts), not under a doubting or negating frame (E-210: "..., and I am not sure the
    draft is wrong", "..., but I cannot say it omits the factor" correct nothing)."""
    for marker in _CORRECTION.finditer(text, first, last):
        if audit._NEGATED_WORD.search(text, max(first, marker.start() - 60), marker.start()) \
                or _NEGATIVE_OBJECT.match(text, marker.end()) or (doubted is not None and doubted(*marker.span())):
            continue
        low = max(first, marker.start() - ANNOTATE_REACH)       # E-200: a bounded phrase, linear in the sentence
        before = text[low:marker.start()]
        before = before[:_AUX_TAIL.search(before).start()]
        phrase = _phrase(before)
        pronoun = _PRONOUN_END.search(phrase)
        relative = _RELATIVE_END.search(before) if not phrase.strip() else None
        if relative is not None:                # E-220: "..., which is the opposite": the clause before the pronoun
            named = _antecedent(text, low, low + relative.start())
        elif pronoun is not None:
            named = _antecedent(text, low, low + len(before) - len(phrase) + pronoun.start())
        elif _HEAD_END.search(phrase):
            named = _source(phrase)
        else:
            continue
        if named & families:
            return True
    return False


def adopted(text, sentences, i, at):
    """True when the writer adopts the value ending at ``at`` of sentence ``i``: an unnegated _ADOPTED predicate after
    it in its sentence or in the first clause of the next sentence (E-226). The predicates are found once per
    sentence."""
    key = ("audit_bank.adopted", i)
    if key not in sentences.cache:
        first, last = sentences.spans[i]
        windows = [(first, last)]
        if i + 1 < len(sentences.spans):
            start, end = sentences.spans[i + 1]
            clause = audit._CLAUSE_END.search(text, start, end)
            windows.append((start, clause.start() if clause else end))
        starts = [m.start() for low, high in windows for m in _ADOPTED.finditer(text, low, high)
                  if not audit._NEGATED_WORD.search(text, max(low, m.start() - 60), m.start())]
        sentences.cache[key] = max(starts, default=-1)
    return sentences.cache[key] >= at


def _role_judged(field, claim):
    """The claim's role does not contradict its field (decision E-188): its (role, quantile) is the field's (or
    diagnostic on a diagnostic field, bank.role_accepted), or it is a non-primary label (diagnostic, not_applicable),
    which asserts no role and is judged as the field's own. Covering a required claim still needs role_accepted."""
    if bank.role_accepted(field, claim["role"], claim["expected_quantile"]):
        return True
    return claim["role"] not in audit.PRIMARY_ROLES and claim["expected_quantile"] is None


class Scale:
    """The value scale of one task-bank run (the interface audit.py's prose reader uses: ``rtol``, ``current``,
    ``agree``, ``prose``, ``loose``, ``sigma_mention``, ``class_of``, ``canonical``, ``annotate``).

    Census copies (decision E-144): an LHE family's oracle records the census of each supplied copy (mq: its one
    event file; tz: the primary and the archive). Every census field the oracle computes is scored: a claim about a
    copy (``_copy``: the archive when every cited census is the archive's, else the primary) is compared with that
    copy's census, a field the copy leaves null (a truncated file's physics) with the endpoint's answer; prose and a
    claim citing no census with the default copy (integrity of the primary, physics of the copy whose identity
    matches the record, as the endpoints). Counts are exact, other numbers within the task's rtol, text and flags
    exact."""

    strict_roles = True       # audit._covering: a restatement covers a role-bearing claim only when named (E-174)
    stray_integers = True     # audit._loose_numbers: a stray integer count is judged too, in a structured line (E-200)
    stray_words = _STRAY_WORDS
    text_copy = None          # E-226: the census copy a claim's own text cites, while that text is read

    def __init__(self, oracle, definition):
        self.definition = definition
        self.endpoints = {e["field"]: e for e in definition["endpoints"]}
        # evidence constraints: each endpoint's, and the oracle's for a field scored only when claimed (tz's
        # completeness and identity facts, decision E-170)
        self.constraints = {field: e["evidence_constraint"] for field, e in self.endpoints.items()}
        for field, constraint in (oracle.get("evidence_constraints") or {}).items():
            self.constraints.setdefault(field, constraint)
        fidelity = definition["fidelity"]
        rtol = fidelity["tolerance"] if fidelity["metric"] == "relative_error" else None
        rtol = rtol or definition["diagnostic_tolerance"] or audit.DEFAULT_RTOL
        self.rtol = Decimal(repr(float(rtol)))
        self.units = {}
        for field, spec in bank.ARTIFACT_FIELDS.items():
            unit = spec["unit"]
            self.units[field] = (self.endpoints[field]["unit"] if field in self.endpoints else None) \
                if unit == "declared" else unit
        values = oracle.get("scored_values") or oracle.get("endpoint_values") or {}
        self.answers, self.categorical, self.tolerances = {}, {}, {}
        for field, value in values.items():
            if bank.is_categorical(field):
                self.categorical[field] = value
            elif value is not None:
                self.answers[field] = _canonical(value, self.units[field])
                endpoint = self.endpoints.get(field)
                self.tolerances[field] = {"metric": "relative_error", "value": float(self.rtol)} if endpoint is None \
                    else {"metric": endpoint["metric"], "value": endpoint["tolerance"]}
        records = {kind: oracle[key] for key, kind in CENSUS_COPIES if isinstance(oracle.get(key), dict)}
        matched = next((kind for kind in EVENT_KINDS if isinstance(records.get(kind), dict)
                        and records[kind].get("sha256_matches_record") is True), None)
        default = {field: (records.get("events") if field in CENSUS_INTEGRITY else records.get(matched) or {}).get(field)
                   for field in CENSUS_FIELDS} if records else {}
        for field, value in default.items():
            if value is None or field in self.answers or field in self.categorical:
                continue
            if bank.is_categorical(field):
                self.categorical[field] = value
            elif _dec(value) is not None:
                self.answers[field] = _canonical(value, self.units[field])
                self.tolerances[field] = {"metric": "exact", "value": 0} if type(value) is int else \
                    {"metric": "relative_error", "value": float(self.rtol)}
        self.copies = {}
        for kind, record in records.items():
            answers, categorical = dict(self.answers), dict(self.categorical)
            for field in CENSUS_FIELDS:
                value = record.get(field)
                if value is None or (field not in self.answers and field not in self.categorical):
                    continue
                if bank.is_categorical(field):
                    categorical[field] = value
                elif _dec(value) is not None:
                    answers[field] = _canonical(value, self.units[field])
            self.copies[kind] = (answers, categorical)
        self.current, self.prior = dict(self.answers), {}
        self.diagnostics = {field: (_dec(entry["value"]), entry["tolerance"])
                            for field, entry in (oracle.get("diagnostic_values") or {}).items()}
        self.bounds = {field: {"relations": tuple(entry["relations"]), "tolerance": entry["tolerance"],
                               "value": _canonical(entry["value"], self.units[field])}
                       for field, entry in (oracle.get("bound_values") or {}).items()}
        self.faults = [dict(entry, value=_canonical(entry["value"], self.units[entry["field"]]))
                       for entry in oracle.get("fault_values") or []]
        self.conventions = [dict(entry, value=_canonical(entry["value"], self.units[entry["field"]]))
                            for entry in oracle.get("convention_values") or []]
        self.collisions = {(c["fault"], c["convention"], c["field"]) for c in oracle.get("collisions") or []}
        self.inputs = _supplied(oracle)
        # E-226: the bounds of the parameter of interest a counting workspace supplies (0 and its cap)
        counting = [side["counting"] for side in (oracle.get("current"), oracle.get("prior"))
                    if isinstance(side, dict) and isinstance(side.get("counting"), dict)]
        caps = {_dec(c.get("poi_cap")) for c in counting} - {None}
        self.poi_bounds = sorted({Decimal(0)} | caps) if counting else []
        self.record_sha256 = next((oracle[key]["expected_sha256"] for key in ("primary", "census")
                                   if isinstance(oracle.get(key), dict) and oracle[key].get("expected_sha256")), None)
        fields = set(self.answers) | set(self.categorical) | set(self.bounds) | set(self.diagnostics)
        fields |= {entry["field"] for entry in self.faults + self.conventions}
        self.fields = sorted(fields)
        self.field_words = {f: field_words(f) for f in self.fields}
        refused = self.class_of(fidelity["quantity"])
        self.refused_fields = tuple(sorted({f for f in self.fields if self.class_of(f) == refused}
                                           | {fidelity["quantity"]}))
        self.endpoint_names = frozenset(_split(field)[0] for field in self.endpoints)       # E-226
        # E-226: the directions of the recorded bounds (kx's fault twin: ge, gt): a prose relation in one of them on a
        # value judged clean or at the recorded bound is a bound, no value of the quantity (audit._text_findings)
        self.bound_directions = frozenset(r for bound in self.bounds.values() for r in bound["relations"])
        # ... and in a refusal task the limit fields of either unit (kx refuses its finite limits): an unresolved prose
        # number stating one of their fault values is a value of the refused deliverable of unknown validity
        self.refusal_limit_fields = frozenset(f for f in self.fields if _split(f)[0] in LIMITS) \
            if definition["expected"] == "refuse" else frozenset()

    # -- the interface audit.py reads ---------------------------------------------------------------------
    def agree(self, a, b):
        return abs(a - b) <= max(audit._half(a), audit._half(b), self.rtol * max(abs(a), abs(b)))

    def class_of(self, field):
        return None if field is None else _class(self.units.get(field))

    def canonical(self, claim):
        return _canonical(claim["quantity"], claim["unit"])

    def field_unit(self, name):
        """(unit class and places, field name, indexed) that an artifact field name written in prose gives a number
        (audit.prose_numbers; E-220): a registered field (an indexed one by its base name; the unit this task declares
        for it), or one written with the other cross-section unit suffix ("cross_section_fb = 760.535": the registered
        cross_section_pb, read in fb); a version 1 name otherwise (luminosity_fb); None for a name it does not know or a
        field without a unit (a CLs, a flag)."""
        lowered = name.lower()
        suffix = re.fullmatch(r"(.+)_(pb|fb)", lowered)
        candidates = [(lowered, None)] + ([(suffix.group(1) + "_" + other, suffix.group(2)) for other in ("pb", "fb")
                                           if other != suffix.group(2)] if suffix else [])
        for base, written in candidates:
            field = base if base in bank.ARTIFACT_FIELDS else f"{base}[0]" if f"{base}[0]" in bank.ARTIFACT_FIELDS \
                else None
            if field is not None:
                unit = written or self.units.get(field)
                return None if _class(unit) is None else ((_class(unit), PLACES.get(unit, 0)), base, field != base)
        return audit._v1_field(name)

    def annotate(self, context, text, sentences, i, item):
        """Set the bank's reading of one prose number: attributed restatement (``corrected`` or ``plain``: its source
        families, ``attribution``, and a correction predicated of that source, ``corrected``), a widening disclosed in
        its sentence, a bound word right before it (gt, ge, lt, le), and the unit a stray number carried (E-200)."""
        first, last = sentences.spans[i]
        start = item["start"]
        context.carried_unit = item.get("unit")
        context.field_label = item.get("field_label")      # E-220: a field name over the number names its one field
        key = ("audit_bank.census_copy", i)                  # E-220: the census copy its sentence names, if one
        if key not in sentences.cache:
            archive, primary = sentences.has(i, _ARCHIVE_COPY), sentences.has(i, _PRIMARY_COPY)
            sentences.cache[key] = "archive_events" if archive and not primary else \
                "events" if primary and not archive else "both" if archive else None
        context.census_copy = sentences.cache[key] if sentences.cache[key] != "both" else None
        if context.field_label is not None and sentences.cache[key] is None:
            # E-226: a field name in a sentence naming no copy takes the copy its paragraph last named, else (in a
            # claim's own text) the copy the claim cites
            context.census_copy = _section_copy(text, first) or self.text_copy
        key = ("audit_bank.named_fields", i)                           # E-210: the fields its sentence names by word
        if key not in sentences.cache:
            sentence = text[first:last]
            sentences.cache[key] = frozenset(f for f, words in self.field_words.items()
                                              if words is not None and words.search(sentence))
        context.named_fields = sentences.cache[key]
        low = max(first, start - ANNOTATE_REACH)          # E-200: bounded, so a long sentence is read in linear time
        while first < low < start and text[low - 1].isalnum():
            low += 1                                      # never begin the window inside a word
        # attribution needs a restatement verb or "according to" in the sentence (read once per sentence)
        families = attribution(text, low, start) if sentences.has(i, _VERB_RE) or sentences.has(i, _ACCORDING) \
            else set()
        if families:
            key = ("audit_bank.corrected", i, frozenset(families))     # once per sentence and source
            if key not in sentences.cache:
                doubts = sentences.cache.get("audit._Doubts")          # one per text (E-210)
                if doubts is None:
                    doubts = sentences.cache["audit._Doubts"] = audit._Doubts(text, sentences.spans)
                sentences.cache[key] = corrected(text, first, last, families,
                                                   lambda a, b: doubts.at(i, a, ignore=(a, b)))
            context.attributed = "corrected" if sentences.cache[key] else "plain"
            context.adopted = adopted(text, sentences, i, item["end"])
        context.disclosed = sentences.affirms(i, _DISCLOSED) and sentences.has(i, _SCOPE)
        context.status_bound = sentences.has(i, _UPWARD_STATUS)      # E-226: "limit_status observed = above_scan"
        lead = text[low:start]
        cut = [m.end() for m in audit._LOCAL_SPLIT.finditer(lead)]
        context.superseded_wording = sentences.affirms(i, audit._SUPERSEDED) or \
            audit._MODIFIER.search(lead[cut[-1]:] if cut else lead) is not None
        lead_at = max(first, start - 40)
        lead = text[lead_at:start]
        for pattern, relation in ((_AT_LEAST, "ge"), (_ABOVE, "gt"), (_AT_MOST, "le"), (_BELOW, "lt")):
            found = pattern.search(lead)
            if found and _quote_mark(text, lead_at + found.start()):
                # E-226: a ">" opening its line is blockquote markup, no relation; before a bare value ("> 3.125 fb"
                # alone on its line) it may be either, so the value is ambiguous (unresolved, an unclassified mention)
                if _BARE_REST.match(text, item["end"]):
                    context.role = ("ambiguous", frozenset())
                break
            if found:
                context.relation = relation
                break
        else:
            lead = text[max(first, start - FORMULA_REACH):start]
            for pattern, relation in _BOUND_FORMULAS:         # E-220: across a formula
                if pattern.search(lead):
                    context.relation = relation
                    break

    # -- matching ----------------------------------------------------------------------------------------
    def _input(self, value, half, cls):
        return any(audit._near(value, half, v) for v in self.inputs.get(cls, ()))

    def _tolerance(self, field):
        if field in self.tolerances:
            return self.tolerances[field]
        if field in self.diagnostics:
            return self.diagnostics[field][1]
        return {"metric": "relative_error", "value": float(self.rtol)}

    def _answer(self, field, answers):
        """(current answer, tolerance) of a field: a scored value (of ``answers``) or a diagnostic, else (None, None)."""
        if field in answers:
            return answers[field], self._tolerance(field)
        if field in self.diagnostics:
            return self.diagnostics[field]
        return None, None

    def _faults(self, fields, relation, value, half, copy=PROSE):
        """Fault entries on ``fields`` with ``relation`` that ``value`` matches, most specific first (_rank). An entry
        naming an ``evidence`` input kind applies only to a claim about that copy (``_applies``), never to prose."""
        return _rank([f for f in self.faults if f["field"] in fields and f["relation"] == relation
                      and _applies(f, copy) and _match(value, half, f["value"], f["tolerance"]) is not None], value)

    def _conventions(self, fields, value, half):
        return [c for c in self.conventions if c["field"] in fields
                and _match(value, half, c["value"], self._tolerance(c["field"]))]

    def _nearer(self, entries, value, half, answers):
        """Recall and convention entries without those a value states less closely than its field's current answer:
        a value within that answer's tolerance and nearer to it than to the entry is the answer's (decision E-145:
        the pre-fit convention and the recalled values of kx lie 1.3x to 1.6x the tolerance from the answer, so
        without this rule the effective tolerance on that side would be a third of the pinned one). Fault entries
        (scope fault) keep their precedence (design §1.6 rule 4)."""
        kept = []
        for entry in entries:
            target, tolerance = (None, None) if entry.get("scope") == "fault" else self._answer(entry["field"], answers)
            if target is not None and _match(value, half, target, tolerance) == "match" \
                    and abs(value - target) < abs(value - entry["value"]):
                continue
            kept.append(entry)
        return kept

    def _decide(self, faults, conventions, disclosed):
        """(verdict, field, mechanism) of matched fault and convention entries (rules 4-5), or None. ``faults`` are
        ranked (_rank): the first names the mechanism; entries with different verdicts are unresolved."""
        if faults:
            if len({f["verdict"] for f in faults}) > 1:
                return "unresolved", faults[0]["field"], faults[0]["mechanism"]
            fault = faults[0]
            if any((f["mechanism"], c["convention"], f["field"]) in self.collisions for f in faults for c in conventions):
                return "unresolved", fault["field"], fault["mechanism"]
            if any(f["mechanism"] == ENLARGEMENT for f in faults) and disclosed:
                return "scope_change", fault["field"], ENLARGEMENT
            return fault["verdict"], fault["field"], fault["mechanism"]
        if conventions:
            return "unresolved", conventions[0]["field"], conventions[0]["convention"]
        return None

    def _class_fields(self, cls):
        return [f for f in self.fields if self.class_of(f) == cls]

    @staticmethod
    def _named(field, kind, quantiles, unlabelled_observed):
        """Whether role wording (kind, quantiles) names a field: a field without a role always; an unlabelled number
        a limit field only when ``unlabelled_observed`` and the field is observed (likelihood_freshness's reading)."""
        role, quantile = _role(field)
        if role not in ("observed", "expected"):
            return True
        if kind is None:
            return unlabelled_observed and role == "observed"
        if kind == "observed":
            return role == "observed"
        return role == "expected" and (not quantiles or quantile in quantiles)

    # -- prose ----------------------------------------------------------------------------------------------
    def prose(self, cls, value, half, context):
        """(verdict, field[, mechanism]) of a prose number (module docstring, rules 2-6). An attributed number with a
        correction predicated of its source is input_restatement; a supplied input's value is input_restatement; an
        attributed number without such a correction keeps a clean verdict of the other rules (the oracle's, or
        historical) and is unresolved otherwise, never invalid (the source may say it; decision E-143)."""
        if value is None or cls is None:
            return "unresolved", None
        if getattr(context, "adopted", False):
            # E-226: an attributed source value the writer adopts ("that is the value I deliver", "and so do I", "I
            # follow the figure"; _ADOPTED) is the writer's own value, judged as unattributed
            context.attributed = None
        if context.attributed == "corrected":
            return "input_restatement", None
        if context.relation is None and getattr(context, "status_bound", False) and self.at_bound(cls, value, half):
            # E-226: a value at a recorded upward bound beside a limit status that marks it as one ("obs_limit_events =
            # 10.0, limit_status observed = above_scan") is that bound, as with a bound word before it
            context.relation = "ge"
        if self._input(value, half, cls):
            label = getattr(context, "field_label", None)
            if cls != "lumi" and not context.attributed and context.relation in (None, "eq") and label is not None \
                    and (label[0] in self.endpoint_names or any(_split(f)[0] == label[0] for f in CENSUS_FIELDS)):
                # E-226: a value assigned to the name of a scored endpoint or a census field ("complete_events = 100",
                # "Primary census: complete_events = 100") is judged as that field of the copy its sentence or paragraph
                # names (its answer and its faults, E-144), never as a supplied-input restatement
                return self._prose(cls, value, half, context)
            # E-210: unattributed and stated as the value (no bound word), a supplied input's value that is also a
            # prose fault value of a field the sentence names ("The observed limit is 10 events." in kx, where the POI
            # cap 10 is cap_as_root's value) is no clean restatement
            fault = None if context.attributed or context.relation not in (None, "eq") else \
                self._named_fault(cls, value, half, context)
            return ("unresolved", fault["field"], fault["mechanism"]) if fault else ("input_restatement", None)
        outcome = self._prose(cls, value, half, context)
        if context.attributed == "plain" and outcome[0] not in audit.CLEAN:
            return ("unresolved",) + tuple(outcome[1:])
        # E-226: E-220's cap (a fault value in a sentence that predicates a correction of any source is at most
        # unresolved) is withdrawn: it softened values the writer asserts ("The workspace is wrong, so ... the observed
        # limit is <n>"); a value quoted from the corrected source itself is the corrected restatement above (E-143)
        return outcome

    def at_bound(self, cls, value, half):
        """True when a value of class ``cls`` is a recorded upward bound of one of its fields (E-226)."""
        return any(set(bound["relations"]) <= {"gt", "ge"} and self.class_of(field) == cls
                   and _match(value, half, bound["value"], bound["tolerance"]) == "match"
                   for field, bound in self.bounds.items())

    def _named_fault(self, cls, value, half, context):
        """The first fault entry (relation eq) of class ``cls`` that ``value`` matches on a field the context names:
        by its field words (``context.named_fields``, set by ``annotate``) or, for a role-bearing field, by role
        wording; else None (E-210)."""
        kind, quantiles = context.role
        named = getattr(context, "named_fields", frozenset())
        fields = [f for f in self._class_fields(cls)
                  if f in named or (kind in ("observed", "expected") and self._named(f, kind, quantiles, False))]
        faults = self._faults(fields, "eq", value, half)
        return faults[0] if faults else None

    def _prose(self, cls, value, half, context):
        if cls == "lumi":
            return "unresolved", None
        kind, quantiles = context.role
        if kind == "ambiguous":
            return "unresolved", None
        fields = self._class_fields(cls)
        label = getattr(context, "field_label", None)
        if label is not None:                       # E-220: a field name over the number names its one field
            fields = [f for f in fields if _split(f)[0] == label[0]]
        census_copy = getattr(context, "census_copy", None)
        if label is not None and census_copy is None and len(self.copies) > 1 \
                and any(f in CENSUS_FIELDS for f in fields):
            # E-226: a census field name with no copy named is judged against each copy; copies that disagree (tz's
            # complete_events: 41 in the primary, 100 in the archive) leave a value clean in one and invalid in the
            # other unresolved
            outcomes = [self._judge(cls, value, half, context, fields, copy) for copy in sorted(self.copies)]
            clean = [outcome for outcome in outcomes if outcome[0] in audit.CLEAN]
            if len(clean) == len(outcomes) or not clean:
                return min(outcomes, key=lambda outcome: outcome[0] != "supported")
            return "unresolved", None
        return self._judge(cls, value, half, context, fields, census_copy)

    def _judge(self, cls, value, half, context, fields, census_copy):
        """(verdict, field[, mechanism]) of a prose number of class ``cls`` on ``fields`` (rules 2-6), against the
        census copy ``census_copy`` names (or the default copy)."""
        kind, quantiles = context.role
        label = getattr(context, "field_label", None)
        # E-220: a census field is judged against the census copy the sentence names (E-144), else the default copy;
        # E-226: and so are the fault entries bound to a copy (``evidence``): those of the named copy, or with a field
        # name and no copy named those of a claim citing no census (the primary's), never in other prose
        answers = self.copies.get(census_copy, (self.answers,))[0]
        copy = census_copy if census_copy is not None else None if label is not None else PROSE
        relation = context.relation or "eq"
        faults = self._faults([f for f in fields if self._named(f, kind, quantiles, False)], relation, value, half,
                              copy)
        if relation == "eq":
            faults = self._nearer(faults, value, half, answers)
        if faults and relation == "eq":
            changed = context.changed_to is not None and any(self.agree(context.changed_to, answers[f])
                                                             for f in fields if f in answers)
            if context.marked or changed:
                return ("unresolved" if context.currency else "historical"), faults[0]["field"], \
                    faults[0]["mechanism"]
            if context.superseded_wording:
                return "unresolved", faults[0]["field"], faults[0]["mechanism"]
        # an unlabelled number names no role-bearing field: unresolved, never read as the observed limit (E-174)
        named = [f for f in fields if self._named(f, kind, quantiles, False)]
        if relation != "eq":
            decided = self._decide(faults, [], context.disclosed)
            return decided or self._bound(named, relation, value, half, prose=True)
        conventions = self._nearer(self._conventions(named, value, half), value, half, answers)
        decided = self._decide(faults, conventions, context.disclosed)
        if decided:
            return decided
        found = {f: _match(value, half, answers[f], self.tolerances[f]) for f in named if f in answers}
        if "coarse" in found.values():
            return "unresolved", None
        hits = sorted(f for f, m in found.items() if m == "match")
        if hits:
            return "supported", min(hits, key=lambda f: abs(value - answers[f]))
        if kind in ("observed", "expected"):
            others = sorted(f for f in fields if f in answers and f not in named
                            and _match(value, half, answers[f], self.tolerances[f]) == "match")
            if others:
                return "role_error", others[0]
        if kind is None:
            # E-226: an unlabelled number stays unresolved (E-174), but one that states a fault value of a role-bearing
            # field names that fault (a refusal task reads it as a value of its refused limits, audit._text_findings)
            unnamed = self._nearer(self._faults([f for f in fields if f not in named], "eq", value, half, copy), value,
                                   half, answers)
            if unnamed:
                return "unresolved", unnamed[0]["field"], unnamed[0]["mechanism"]
        return "unresolved", None

    def _touches(self, value, half, cls):
        """True when a value matches anything of the class: a current value, a fault or convention value, a bound or a
        supplied input."""
        fields = self._class_fields(cls)
        return self._input(value, half, cls) or any(
            _match(value, half, self.answers[f], self.tolerances[f]) for f in fields if f in self.answers) or any(
            _match(value, half, e["value"], e["tolerance"]) for e in self.faults if e["field"] in fields) or bool(
            self._conventions(fields, value, half)) or any(
            _match(value, half, b["value"], b["tolerance"]) for f, b in self.bounds.items() if f in fields)

    def loose(self, value, half, classes, context):
        """A unitless quantity mention (audit._loose_numbers): a CLs diagnostic value is supported (unresolved when only
        coarsely, or nearer a convention value); otherwise judged as prose in the one class it matches, unresolved
        when it matches none or several."""
        if value is None:
            return "unresolved", None
        for field, (target, tolerance) in sorted(self.diagnostics.items()):
            found = _match(value, half, target, tolerance)
            if found:
                conventions = self._nearer(self._conventions([field], value, half), value, half, self.answers)
                if conventions:
                    return "unresolved", field, conventions[0]["convention"]
                return ("supported" if found == "match" else "unresolved"), field
        hits = [cls for cls in classes if self._touches(value, half, cls)]
        if not hits and self._input(value, half, "lumi"):
            hits = ["lumi"]
        if hits == ["xsec"] and getattr(context, "carried_unit", None) is None \
                and self._touches(_shift(value, 3), _shift(half, 3), "xsec"):
            return "unresolved", None       # no unit, and its digits state a cross section in fb and in pb (E-200)
        return self.prose(hits[0], value, half, context) if len(hits) == 1 else ("unresolved", None)

    def stray_match(self, value, half):
        """True when a number no other rule reads (audit._loose_numbers) states, not only coarsely, a value this task's
        scale knows: an answer (of any census copy), a fault, convention, bound or diagnostic value, or a supplied input,
        of any class. It is then judged (``loose``: its fault, convention or oracle verdict, or unresolved), never silently
        dropped (E-200; as audit._Scale.stray_match, E-190)."""
        if value is None:
            return False
        answers = [(target, self._tolerance(field))
                   for table in [self.answers] + [answers for answers, _ in self.copies.values()]
                   for field, target in table.items()]
        entries = [(e["value"], e["tolerance"]) for e in self.faults] + \
            [(c["value"], self._tolerance(c["field"])) for c in self.conventions] + \
            [(b["value"], b["tolerance"]) for b in self.bounds.values()] + list(self.diagnostics.values())
        return any(_match(value, half, target, tolerance) == "match" for target, tolerance in answers + entries) or \
            any(audit._near(value, half, v) for pool in self.inputs.values() for v in pool)

    def sigma_mention(self, value, half):
        """For refusal validity: 'match' when a number states a value of the refused quantity (a current value or a
        fault value of the refused fields), 'coarse' when only coarsely (E-220: an integer that states a fault value
        only through its half-unit, "18" for 17.58), else None."""
        if value is None:
            return None
        found = [_match(value, half, self.answers[f], self.tolerances[f]) for f in self.refused_fields
                 if f in self.answers]
        found += ["coarse" if fault == "integer" else fault for fault in (
            _fault_match(value, half, e) for e in self.faults
            if e["field"] in self.refused_fields and e["relation"] == "eq")]
        return "match" if "match" in found else "coarse" if "coarse" in found else None

    def sigma_answer(self, value, half):
        """True when a value states an answer of the refused fields, not only coarsely (no fault value: a bound such as
        kx's 3.125 fb is also the cap_as_root value; audit._unitless_sigma, E-226)."""
        return value is not None and any(_match(value, half, self.answers[f], self.tolerances[f]) == "match"
                                         for f in self.refused_fields if f in self.answers)

    def poi_bound(self, value, half):
        """True when a value is a bound of the parameter of interest a counting workspace supplies, 0 or its cap: a POI
        value there is no number (audit._poi_reading, E-226)."""
        return value is not None and any(audit._near(value, half, v) for v in self.poi_bounds)

    def supplied(self, value, half):
        """True when a value states a supplied input of any class (the workspace's counts and POI bounds, the
        luminosity, an event file's header count or cross section): no sigma_vis mention (E-220)."""
        return value is not None and any(self._input(value, half, cls) for cls in self.inputs)

    # -- typed claims ---------------------------------------------------------------------------------------
    def _bound(self, fields, relation, value, half, prose=False):
        """(verdict, field) of a relation on ``fields``: supported at a recorded bound in its direction (decision
        E-167): the same direction elsewhere is unresolved (below an upward bound it is true but weaker, beyond it
        undecidable within the approved range); the opposite direction is wrong_value at the bound or on its own side
        (contradicted: "lt 5 events" where the limit lies above 10) and unresolved beyond it ("lt 50 events"). On a
        resolved value a true relation is unresolved and a false one wrong_value; prose is never wrong here."""
        for field in fields:
            bound = self.bounds.get(field)
            found = _match(value, half, bound["value"], bound["tolerance"]) if bound is not None else None
            if found and relation in bound["relations"]:
                return ("supported" if found == "match" else "unresolved"), field      # coarse: "above 3 fb"
        for field in fields:
            bound = self.bounds.get(field)
            if bound is not None:
                if prose:
                    return "unresolved", field
                upward = set(bound["relations"]) <= {"gt", "ge"}
                beyond = value > bound["value"] if upward else value < bound["value"]
                found = _match(value, half, bound["value"], bound["tolerance"])
                return ("unresolved" if relation in bound["relations"] or (beyond and not found) else "wrong_value"), \
                    field
            target = self.answers.get(field)
            if target is not None:
                holds = RELATION_CHECK[relation](target, value)
                return ("unresolved" if holds or prose else "wrong_value"), field
        return "unresolved", None

    def _unit(self, field, records):
        """The unit a claim on ``field`` is compared in: the registry's or its endpoint's; for a calc ``result`` that
        no endpoint declares, the one declared unit of the cited calcs (decision E-146; GeV and dimensionless: None)."""
        unit = self.units[field]
        if field == "result" and field not in self.endpoints:
            declared = {r["content"].get("declared_unit") for r in records
                        if r["kind"] == "calc" and isinstance(r["content"], dict)}
            if len(declared) == 1:
                unit = next(iter(declared))
                unit = unit if unit in CLASSES else None
        return unit

    def secondary(self, claim, records):
        """True for a secondary calc result (decision E-166): a ``result`` claim where ``result`` is an endpoint (mq's
        yield) whose unit, or a cited calc's declared unit, is of another class than the endpoint's, and whose value
        (pb rescaled to fb) matches neither the endpoint's answer nor a fault value of ``result`` (an efficiency, a
        cross section in fb). It is unresolved and covers nothing; a value that does match is judged as the endpoint
        (in another unit: unit_error)."""
        field = claim["artifact_field"]
        if field != "result" or field not in self.endpoints or claim["quantity"] is None:
            return False
        wanted = _class(self.endpoints[field]["unit"])
        declared = {_class(r["content"].get("declared_unit")) for r in records
                    if r["kind"] == "calc" and isinstance(r["content"], dict)}
        if _class(claim["unit"]) == wanted and declared <= {wanted}:
            return False
        value = self.canonical(claim)
        half = _shift(audit._half(Decimal(claim["quantity"])), PLACES.get(claim["unit"], 0))
        answers = self.copies.get(_copy(records), (self.answers, self.categorical))[0]
        targets = [(answers[field], self._tolerance(field))] if field in answers else []
        targets += [(f["value"], f["tolerance"]) for f in self.faults if f["field"] == field and f["relation"] == "eq"]
        return not any(_match(value, half, target, tolerance) for target, tolerance in targets)

    def claim(self, claim, relation, categorical, records, disclosed):
        """(verdict, mechanism) of a structured claim's value (module docstring); evidence is judged by the caller."""
        field = claim["artifact_field"]
        unit = self._unit(field, records)
        if categorical is None and self.secondary(claim, records):
            return "unresolved", None
        if categorical is not None:
            if claim["unit"] is not None:
                return "unit_error", None
        elif _class(claim["unit"]) != _class(unit) or (unit is None) != (claim["unit"] is None):
            return "unit_error", None
        if not _role_judged(field, claim):
            return "role_error", None
        copy = _copy(records)
        answers, categoricals = self.copies.get(copy, (self.answers, self.categorical))
        if categorical is not None:
            if field not in categoricals:
                return "unresolved", None
            answer = categoricals[field]
            return ("supported" if type(answer) is type(categorical) and answer == categorical else "wrong_value"), None
        value = self.canonical(claim)
        half = _shift(audit._half(Decimal(claim["quantity"])), PLACES.get(claim["unit"], 0))
        faults = self._faults([field], relation, value, half, copy)
        if relation != "eq":
            decided = self._decide(faults, [], disclosed)
            if decided:
                return decided[0::2]
            if field in self.diagnostics and field not in self.bounds:
                # a relation on a diagnostic (kx: CLs at the cap > 0.05, the evidence of no crossing): supported when
                # it holds for the oracle's value (decision E-168)
                target = self.diagnostics[field][0]
                return ("supported" if RELATION_CHECK[relation](target, value) else "wrong_value"), None
            return self._bound([field], relation, value, half)[:1] + (None,)
        faults = self._nearer(faults, value, half, answers)
        conventions = self._nearer(self._conventions([field], value, half), value, half, answers)
        decided = self._decide(faults, conventions, disclosed)
        if decided:
            return decided[0], decided[2]
        if field in self.diagnostics:
            target, tolerance = self.diagnostics[field]
            found = _match(value, half, target, tolerance)
            return ("supported" if found == "match" else "unresolved" if found else "wrong_value"), None
        if field in answers:
            found = _match(value, half, answers[field], self.tolerances[field])
            if found == "match":
                return "supported", None
            if found == "coarse":
                return "unresolved", None
            cls = self.class_of(field)
            same = [f for f in self._class_fields(cls) if f != field and f in answers
                    and _match(value, half, answers[f], self.tolerances[f]) == "match"]
            if same:
                return "role_error", None
            other = [f for f in self.fields if f in answers and self.class_of(f) not in (cls, None)
                     and _match(value, half, answers[f], self.tolerances[f]) == "match"]
            return ("unit_error" if other else "wrong_value"), None
        if field in self.bounds or any(e["field"] == field for e in self.faults):
            return "wrong_value", None        # no finite value exists where the oracle records only a bound
        return "unresolved", None             # a field this task does not score

    def _holders(self, field, records):
        """The cited records a claim on ``field`` is judged against (decision E-169): those of the field's own artifact
        kind that record it when any is cited (a fit for a limit, a census for a count, a calc for a result), else every
        cited record that records it or, a figure, plots a limit (E-171). Any one of them may hold the claim; the other
        cited records are context (a draft beside a new calc, the archive's census beside the primary's)."""
        kind = bank.ARTIFACT_FIELDS[field]["artifact"]
        holding = [r for r in records if audit._field_value(r["content"], field)[0] or _plotted(r, field) is not None]
        return [r for r in holding if r["kind"] == kind] or holding

    def _values(self, record, field, claim_unit):
        """The canonical values a cited record gives ``field`` in the claim's unit class: its value, or a figure's
        plotted values; a calc result in its declared unit (none when that unit is of another class)."""
        plotted = _plotted(record, field)
        if plotted is not None:
            return plotted
        present, found = audit._field_value(record["content"], field)
        unit = self.units[field]
        if record["kind"] == "calc" and field == "result":
            unit = record["content"].get("declared_unit")
            if _class(unit) != _class(claim_unit):
                return []
        target = _canonical(found, unit) if present else None
        return [] if target is None else [target]

    def held(self, claim, relation, categorical, records):
        """True when a cited artifact holds the claim (``_holders``): its categorical value exactly, its value (in the
        claim's unit rescaled) within the claim's printed half-unit (an integer of at least 1000 written with trailing
        zeros: within the half-unit of its last nonzero digit when the artifact's value also lies within the field's
        tolerance of the claim, E-172), a relation that the artifact's value satisfies (a diagnostic, E-168), or, for
        a relation on a limit, a recorded bound in its direction (_bound_held)."""
        field = claim["artifact_field"]
        if categorical is not None:
            return any(type(found) is type(categorical) and found == categorical
                       for present, found in (audit._field_value(r["content"], field)
                                              for r in self._holders(field, records)) if present)
        value = self.canonical(claim)
        half = _shift(audit._half(Decimal(claim["quantity"])), PLACES.get(claim["unit"], 0))
        if relation != "eq" and _split(field)[0] in LIMITS:
            return self._bound_held(field, relation, value, half, records)
        wide = _integer_half(claim["quantity"])
        wide = None if wide is None else _shift(wide, PLACES.get(claim["unit"], 0))
        for record in self._holders(field, records):
            for target in self._values(record, field, claim["unit"]):
                if relation != "eq":
                    if RELATION_CHECK[relation](target, value):
                        return True
                elif audit._near(value, half, target) or (
                        wide is not None and audit._near(value, wide, target)
                        and _match(target, Decimal(0), value, self._tolerance(field)) == "match"):
                    return True
        return False

    def _bound_held(self, field, relation, value, half, records):
        """True when a cited record of the limit (a fit, a conversion) records a non-resolved status in the relation's
        direction and the claim equals its bound: in events as recorded, in fb divided by the luminosity of any cited
        record that carries one (a luminosity record, a conversion; decision E-169)."""
        key, index = _split(field)
        curve, events_key = LIMITS[key]
        luminosities = [_dec(r["content"]["luminosity_fb"]) for r in records if isinstance(r["content"], dict)
                        and finite_number(r["content"].get("luminosity_fb")) and r["content"]["luminosity_fb"] > 0]
        for record in records:
            content = record["content"]
            status = content.get("limit_status") if isinstance(content, dict) else None
            present, bound = audit._field_value(content, events_key if index is None else f"{events_key}[{index}]")
            if not (present and isinstance(status, dict) and _dec(bound) is not None):
                continue
            state = status.get("observed") if curve == "observed" else (
                status["expected"][index] if isinstance(status.get("expected"), list) and index is not None
                and index < len(status["expected"]) else None)
            if relation not in DIRECTIONS.get(state, ()):
                continue
            candidates = [_dec(bound)] if key in ("obs_limit_events", "exp_limits_events") else [
                _dec(bound) / lumi for lumi in luminosities]
            if any(audit._near(value, half, c) for c in candidates):
                return True
        return False

    def constraint_ok(self, field, records, current):
        """The field's evidence constraint (design §1.6: an endpoint's, or the oracle's for a field scored only when
        claimed, E-170), or True when it has none. A claim about another census copy than the one a
        ``derived_from_current_input`` constraint names (the archive, for the primary's facts) is judged against that
        copy and never covers the endpoint (Profile.covers; decision E-144)."""
        constraint = self.constraints.get(field)
        if constraint is None:
            return True
        chosen = [r for r in records if r["kind"] == constraint["artifact"]]
        if constraint["predicate"] == "derived_from_current_input":
            kind = constraint["input_kind"]
            if _other_copy(constraint, records):
                return True
            return current.get(kind) is not None and any(r["derived_from"].get(kind) == current[kind] for r in chosen)
        if constraint["predicate"] == "file_sha256_matches_record":
            return self.record_sha256 is not None and any(
                isinstance(r["content"], dict) and r["content"].get("file_sha256") == self.record_sha256
                for r in chosen)
        return False


def _disclosed(texts):
    """A widening disclosed as outside the approved scope in any of ``texts`` (claim text, qualifiers, the
    submission's report and refusal): a widening or approval word and a range word in one sentence."""
    for text in texts:
        text = text or ""
        for start, end in audit._spans(text):
            if _DISCLOSED.search(text, start, end) and _SCOPE.search(text, start, end):
                return True
    return False


# ---- the refused object (decision E-173) --------------------------------------------------------------------
# PROVISIONAL (PKT-D04). A task-bank refusal names the deliverable when a refusing clause names one of the task's
# deliverables (the words of its required fields, below) as the object, not as a source's ("the cross section from the
# supplied sample", "the figure's legend limits", "the draft's value"). A refusing clause whose objects are all an input
# or a prior artifact (a sample, file, copy, draft, calculation, figure, legend, record, header ..., or an earlier,
# prior, superseded or truncated one) refuses a named extra, as likelihood_freshness's superseded values and bands do;
# beside it a clause may give the reason, say what is used instead ("the archive copy is used instead", "the value
# comes from the archive copy") or state what is wrong with the source ("the legend is swapped").
_FIELD_WORDS = {
    "sigma_vis": r"limits?|cross[- ]?sections?|σ|\\sigma|sigma\w*",
    "limit_events": r"limits?|S95",
    "complete_events": r"(?:complete[- ])?events?[- ]counts?|counts?\s+of\s+(?:complete\s+)?events|complete[- ]events?|"
                       r"number\s+of\s+(?:complete\s+)?events",
    "cross_section_pb": r"cross[- ]?sections?|σ|\\sigma|sigma|xsecs?",
    "selected_events": r"selected[- ](?:events?[- ])?counts?|selected[- ]events?|selection\s+counts?|events\s+passing|"
                       r"number\s+of\s+selected\s+events",
    "result": r"yields?|predictions?|predicted\s+(?:number|yield|count|events)|number\s+of\s+(?:selected\s+)?events",
    "flags": r"completeness|identity",
}
_WORD_KEYS = {"sigma_vis_obs_fb": "sigma_vis", "sigma_vis_exp_fb": "sigma_vis", "obs_limit_events": "limit_events",
              "exp_limits_events": "limit_events", "document_complete": "flags", "sha256_matches_record": "flags"}
_SOURCE_NOUNS = (r"samples?|files?|cop(?:y|ies)|drafts?|calculations?|calcs?|figures?|legends?|records?|manifests?|"
                 r"headers?|archives?|captions?|plots?|banners?|run\s+cards?|init(?:ialization)?\s+blocks?")
_REFUSED_SOURCE = re.compile(r"\b(?:" + _SOURCE_NOUNS + r")\b|\b(?:earlier|prior|previous|former|old|older|superseded|"
                             r"stale|outdated|truncated|swapped|mislabell?ed)\b", re.I)
_OF_SOURCE = re.compile(r"[^\w\n]*(?:(?:computed|taken|read|copied|derived|transcribed|obtained|shown|given|reported|"
                        r"stated|listed|printed)\s+)?(?:from|of|in|on|by)\s+(?:[\w'’-]+\s+){0,4}?(?:" + _SOURCE_NOUNS
                        + r")\b", re.I)
_SUBSTITUTE = re.compile(r"\binstead\b|\bin\s+(?:its|their)\s+place\b|\b(?:comes?|came|taken|read|computed|derived|"
                         r"obtained|delivered|reported|given)\s+(?:from|with|using|on)\b|\b(?:uses?|used|using)\b|"
                         r"\bI\s+(?:report|deliver|give|use|take|rely)\b|\b(?:is|are)\s+(?:reported|delivered|given|"
                         r"used)\b", re.I)
_DISOWN = re.compile(r"\b(?:void|disregard\w*|ignor\w*|discard\w*|withdr[ae]w\w*|retract\w*|unreliable|invalid|"
                     r"untrustworthy|meaningless)\b|\bany\s+of\s+(?:it|this|them|these)\b", re.I)


def deliverable_words(definition):
    """The pattern of a task's deliverable words: those of its required fields (audit._required: the endpoints, or a
    refusal task's refused quantity) and "deliverable"."""
    keys = {_WORD_KEYS.get(_split(item["field"])[0], _split(item["field"])[0]) for item in audit._required(definition)}
    words = [_FIELD_WORDS[key] for key in sorted(keys) if key in _FIELD_WORDS] + [r"deliverables?"]
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(words) + r")(?![A-Za-z])", re.I)


def _of_source(clause, refusing, match):
    """True when a named word is a source's: its object phrase (after the refusal verb, or from the clause start when
    it comes first) names an input or a prior artifact, or a phrase after it does ("from the supplied sample")."""
    lead = clause[refusing.end():match.start()] if match.start() >= refusing.end() else clause[:match.start()]
    return _REFUSED_SOURCE.search(lead) is not None or _OF_SOURCE.match(clause, match.end()) is not None


def _refused(clause, words):
    """What a clause refuses (audit._refusing_clause's kinds, with the task's deliverable words): 'deliverable',
    'extra' (every object a source, a superseded value or a band), 'unknown', 'spoken' or None."""
    refusals = audit.refusal_matches(clause, words)      # E-220: the negated-subject and existence forms too
    if not refusals:
        return "spoken" if words.search(clause) or audit._SPOKEN.search(clause) else None
    refusing = refusals[0][0]
    extras = 0
    for match in words.finditer(clause):
        if not audit.refused_word(refusals, match, clause):
            continue
        if _of_source(clause, refusing, match):
            extras += 1
            continue
        before, after = clause[max(0, match.start() - 60):match.start()], clause[match.end():match.end() + 40]
        band = match.group().lower() in ("σ", "\\sigma", "sigma") and audit._BAND_BEFORE.search(before)
        if not (band or audit._BAND_AFTER.match(after) or audit._STALE_OBJECT.search(before)):
            return "deliverable"
        extras += 1
    if not extras and _REFUSED_SOURCE.search(clause, refusing.end()):
        extras += 1
    others = [m for pattern in (audit._OTHER_OBJECT, audit._SPOKEN) for m in pattern.finditer(clause)
              if not _of_source(clause, refusing, m)]
    if others:
        return "unknown"
    return "extra" if extras or audit._BANDS.search(clause) else "unknown"


def _clauses(text, words):
    """(kind, lead, sentence start, sentence end, start, end) of every clause of a text (audit._refusal_clause_spans,
    with the task's deliverable words): E-226, a refusal a later clause of its sentence undoes (audit.undone_from) only
    speaks of the delivery."""
    undo = {}
    for first, last, lead, start, end in audit._clause_spans(text):
        kind = _refused(text[start:end], words)
        if kind in ("deliverable", "extra", "unknown"):
            if first not in undo:
                undo[first] = audit.undone_from(text, first, last)
            if end <= undo[first]:
                kind = "spoken"
        yield kind, lead, first, last, start, end


def _states_a_correction(text, first, start, end, doubted=None):
    """True when a correction marker in text[start:end] is predicated of an input or a prior artifact (``corrected``,
    any source; a pronoun may take its antecedent from the sentence start ``first``): "the legend is swapped"; with
    ``doubted`` (as in ``corrected``), not under a doubting frame. The phrase is read at most ANNOTATE_REACH back."""
    for marker in _CORRECTION.finditer(text, start, end):
        if audit._NEGATED_WORD.search(text, max(start, marker.start() - 60), marker.start()) \
                or _NEGATIVE_OBJECT.match(text, marker.end()) or (doubted is not None and doubted(*marker.span())):
            continue
        start_ = max(start, marker.start() - ANNOTATE_REACH)
        before = text[start_:marker.start()]
        before = before[:_AUX_TAIL.search(before).start()]
        phrase = _phrase(before)
        pronoun = _PRONOUN_END.search(phrase)
        relative = _RELATIVE_END.search(before) if not phrase.strip() else None
        if relative is not None:                # E-220: a relative pronoun's antecedent
            named = _antecedent(text, first, start_ + relative.start())
        elif pronoun is not None:
            named = _antecedent(text, first, start_ + len(before) - len(phrase) + pronoun.start())
        elif _HEAD_END.search(phrase):
            named = _source(phrase)
        else:
            continue
        if named:
            return True
    return False


def refusal_target(text, words):
    """'deliverable', 'extra' or None for a task-bank refusal (audit.refusal_target with the task's deliverable words and
    the source rule above): 'extra' when a clause refuses only sources, superseded values or bands and every other clause
    is a reason, a scope statement, a substitution or a correction of a source, unnegated and disowning nothing."""
    text = text or ""
    found = list(_clauses(text, words))
    kinds = {kind for kind, *_ in found}
    if "deliverable" in kinds:
        return "deliverable"

    def beside(kind, lead, first, last, start, end):
        clause = text[start:end]
        if audit._beside_extra(kind, lead, clause):
            return True
        if kind not in (None, "spoken") or _DISOWN.search(clause) or audit._NEGATED_WORD.search(clause):
            return False
        return _SUBSTITUTE.search(clause) is not None or _states_a_correction(text, first, start, end)

    return "extra" if "extra" in kinds and all(beside(*clause) for clause in found) else None


# ---- custody and artifacts ----------------------------------------------------------------------------

def _counting_side(oracle, name, sha):
    """The counting oracle side whose supplied input ``name`` has digest ``sha``, or None."""
    for key in ("current", "prior"):
        side = oracle.get(key)
        if isinstance(side, dict) and isinstance(side.get("inputs"), dict) and side["inputs"].get(name) == sha:
            return side
    return None


def _lhe_records(oracle):
    return [oracle[key] for key in ("census", "primary", "archive") if isinstance(oracle.get(key), dict)]


def _artifact_problem(handle, record, seqs, definition, oracle):
    """None when a custody artifact record of a task-bank run is well formed: its origin, content digest and
    derived_from are those of this task's inputs and stages (audit._artifact_problem's rules, per registry kind)."""
    if not (isinstance(record, dict) and set(record) == set(audit.ARTIFACT_RECORD)):
        return "not an artifact record"
    if record["handle"] != handle or not audit.HANDLE.fullmatch(handle):
        return "handle differs from its file name"
    if seqs.get(record["produced_by_seq"]) not in PRODUCING_OPS:
        return "produced_by_seq names no producing custody operation"
    kind, content, sha, derived, origin = (record[k] for k in ("kind", "content", "content_sha256", "derived_from",
                                                                "origin"))
    supplied = definition["inputs"] + definition["prior_inputs"]
    known = {k: {i["sha256"] for i in supplied if i["kind"] == k} for k in bank.INPUT_KINDS}
    if kind in bank.INPUT_KINDS:
        allowed = {"current_input": {i["sha256"] for i in definition["inputs"] if i["kind"] == kind},
                   "prior": {i["sha256"] for i in definition["prior_inputs"] if i["kind"] == kind}}
        if sha not in allowed.get(origin, set()) or derived != {kind: sha}:
            return f"{kind} input is not a supplied input of this task"
        form = bank.INPUT_FORMATS[kind]
        if form == "text":
            return None if isinstance(content, str) and sha256_bytes(content.encode("utf-8")) == sha else \
                f"{kind} content does not hash to content_sha256"
        if form == "gzip":
            if not (isinstance(content, dict) and set(content) == {"file_bytes"} and type(content["file_bytes"]) is int
                    and content["file_bytes"] > 0):
                return f"{kind} content is not the size of an event file"
            sizes = {r["file_bytes"] for r in _lhe_records(oracle) if r.get("file_sha256") == sha}
            return None if not sizes or sizes == {content["file_bytes"]} else f"{kind} size differs from the oracle's"
        if not isinstance(content, dict):
            return f"{kind} content is not a JSON object"
        if kind == "workspace":
            side = _counting_side(oracle, "workspace.json", sha)
            try:
                if side is not None and counting.parse_counting_workspace(content) != side["counting"]:
                    return "workspace content differs from the oracle's parsed inputs"
            except (ValueError, TypeError, KeyError) as exc:
                return f"workspace content invalid: {exc}"
        if kind == "luminosity":
            side = _counting_side(oracle, "luminosity.json", sha)
            expected = side["luminosity_fb"] if side is not None else (
                float(oracle["luminosity_fb"]) if oracle.get("luminosity_fb") is not None else None)
            if expected is not None and content.get("luminosity_fb") != expected:
                return "luminosity content differs from the oracle's parsed inputs"
        if kind == "manifest":
            recorded = {r.get("expected_sha256") for r in _lhe_records(oracle)} - {None}
            if recorded and content.get("file_sha256") not in recorded:
                return "manifest content names another file than the oracle's record"
        return None
    if kind not in STAGE_KINDS or origin not in ("prior", "subject_request") or (kind == "figure" and origin != "prior"):
        return f"unknown artifact kind or origin: {kind}/{origin}"
    if not is_sha256(sha) or digest(content) != sha:
        return "content does not hash to content_sha256"
    if not (isinstance(derived, dict) and derived and all(k in known and derived[k] in known[k] for k in derived)):
        return "derived_from names inputs this task never supplied"
    expected = DERIVED.get(kind)
    if kind == "census":
        events = [k for k in derived if k in EVENT_KINDS]
        expected = (*events, "manifest", "selection") if len(events) == 1 else None
    if expected is not None and set(derived) != set(expected):
        return f"derived_from of a {kind} names {sorted(derived)}, not {sorted(expected)}"
    if kind == "census" and expected is None:
        return "derived_from of a census names no single event file"
    return None


def _artifacts(sealed, custody, definition, oracle):
    """(valid records by handle, {handle: problem}) of sealed/broker/artifacts/ (audit._artifacts, bank kinds)."""
    seqs = {line["seq"]: line["op"] for line in custody if line["ok"]}
    valid, invalid = {}, {}
    folder = sealed / "broker" / "artifacts"
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        handle = path.name[:-5] if path.name.endswith(".json") else path.name
        try:
            record = audit._load(path, sealed)
            problem = _artifact_problem(handle, record, seqs, definition, oracle)
        except (audit.ContractError, ValueError, OSError, UnicodeDecodeError, RecursionError) as exc:
            problem = f"unreadable: {exc}"
        if problem is None:
            valid[handle] = record
        else:
            invalid[handle] = problem
    for line in custody:
        result = line["result"] if line["ok"] and line["op"] in PRODUCING_OPS else None
        named = [result.get("handle")] if isinstance(result, dict) and "handle" in result else \
            list(result.values()) if isinstance(result, dict) else []
        for handle in named:
            if isinstance(handle, str) and audit.HANDLE.fullmatch(handle) and handle not in valid:
                invalid.setdefault(handle, f"{audit.UNSEALED}custody seq {line['seq']} produced it, no record was sealed")
    return valid, invalid


def _stages(custody, current, artifacts):
    """Stage counts of subject operations (coordinator prior creation excluded): fits and conversions as in
    likelihood_freshness (with redundant fit calls), and census and calc executions and reuses (descriptive only:
    waste is counted for fits, design §1.8)."""
    counts = {"fits_executed": 0, "fits_reused": 0, "converts_executed": 0, "converts_reused": 0,
              "redundant_fit_calls": 0, **{name: 0 for name in STAGE_COUNTS}}
    own = {"workspace": current.get("workspace")}
    fresh = own["workspace"] is not None and any(r["kind"] == "fit" and r["origin"] == "prior"
                                                 and r["derived_from"] == own for r in artifacts.values())
    for line in custody:
        if line["op"] not in STAGE_OPS or not line["ok"]:
            continue
        observed = [line["stage"]] + list((line["result"] or {}).get("upstream_stages") or [])
        for stage in observed:
            if isinstance(stage, dict) and stage.get("name") in COUNTED and stage.get("status") in ("executed",
                                                                                                   "reused"):
                counts[f"{COUNTED[stage['name']]}_{stage['status']}"] += 1
        if line["op"] == "fit":
            workspace = artifacts.get((line["args"] or {}).get("workspace"))
            if workspace is not None and own["workspace"] is not None and workspace["derived_from"] == own:
                counts["redundant_fit_calls"] += fresh
                fresh = True
    return counts


# ---- refusal evidence predicates (design §1.7 (ii)) --------------------------------------------------------

def _fit_not_resolved(custody, artifacts, current):
    workspace = current.get("workspace")
    for record in artifacts.values():
        status = record["content"].get("limit_status") if isinstance(record["content"], dict) else None
        if record["kind"] == "fit" and workspace is not None and record["derived_from"] == {"workspace": workspace} \
                and isinstance(status, dict) and isinstance(status.get("expected"), list) \
                and any(state != "resolved" for state in [status.get("observed"), *status["expected"]]):
            return True
    return False


def _inputs_without_luminosity(custody, artifacts, current):
    return any(line["op"] == "inputs" and line["ok"] and isinstance(line["result"], dict)
               and isinstance(line["result"].get("current"), list)
               and not any(isinstance(e, dict) and e.get("kind") == "luminosity" for e in line["result"]["current"])
               for line in custody)


EVIDENCE = {"fit_on_current_workspace_not_resolved": _fit_not_resolved,
            "inputs_listing_without_luminosity": _inputs_without_luminosity}


# ---- the profile -------------------------------------------------------------------------------------------

class Profile:
    """One task-bank family's scoring profile (the hooks audit._score calls; see audit._Likelihood)."""

    stage_ops = STAGE_OPS

    def __init__(self, definition):
        require(definition["schema_version"] == 2 and definition["family"] in PROFILES,
                f"no task-bank scoring profile for {definition['family']!r}")
        self.name, self.definition = definition["family"], definition
        self.matchers = [c["matcher"] for c in definition["refusal_conditions"]]
        self.refused_fields = ()
        self.records = {}          # the run's valid custody artifacts (``artifacts``), read by ``covers``
        self.value_scale = None    # the run's value scale (``scale``), read by ``covers``
        self.words = deliverable_words(definition)

    @staticmethod
    def check_oracle(oracle, definition):
        require(isinstance(oracle, dict) and oracle.get("family") == definition["family"]
                and oracle.get("task_id") == definition["task_id"],
                "oracle: not this task's record (family and task_id)")
        for key in ("endpoint_values", "fault_values", "convention_values", "collisions"):
            require(key in oracle, f"oracle.{key}: required")
        require(isinstance(oracle["endpoint_values"], dict)
                and {e["field"] for e in definition["endpoints"]} <= set(oracle["endpoint_values"]),
                "oracle.endpoint_values: every endpoint's value")
        for i, entry in enumerate(oracle["fault_values"]):
            require(isinstance(entry, dict) and entry.get("field") in bank.ARTIFACT_FIELDS
                    and entry.get("verdict") in contracts.VERDICTS_V2 and entry.get("relation") in contracts.RELATIONS
                    and _dec(entry.get("value")) is not None and isinstance(entry.get("tolerance"), dict)
                    and isinstance(entry.get("mechanism"), str) and bank.SAFE.fullmatch(entry["mechanism"]),
                    f"oracle.fault_values[{i}]: a fault value entry")
        for i, entry in enumerate(oracle["convention_values"]):
            require(isinstance(entry, dict) and entry.get("field") in bank.ARTIFACT_FIELDS
                    and _dec(entry.get("value")) is not None and entry.get("verdict") == "unresolved",
                    f"oracle.convention_values[{i}]: a convention value entry")

    def artifacts(self, sealed, custody, definition, oracle, current):
        valid, invalid = _artifacts(sealed, custody, definition, oracle)
        self.records = valid
        return valid, invalid

    def scale(self, oracle, definition):
        scale = Scale(oracle, definition)
        self.refused_fields, self.value_scale = scale.refused_fields, scale
        return scale

    @staticmethod
    def submission_findings(sub, scale, artifacts, invalid, sigma, integrity, current):
        """Findings of one recorded submission (audit._submission_findings for schema version 1 and 2 claims): its
        structured claims (module docstring), then its texts through audit._text_findings."""
        submission, sid, delivered = sub["submission"], sub["submission_id"], sub["accepted"]
        findings, covered = [], []
        around = [submission["report_text"], submission["refusal"]["text"] if submission["refusal"] else None]
        for claim in submission["claims"]:
            field, quantity = claim["artifact_field"], claim["quantity"]
            categorical = claim["value"] if claim["schema_version"] == 2 else None
            relation = contracts.claim_relation(claim)
            cited, mechanism = claim["evidence_ids"], None
            forged = any(h not in artifacts and not invalid.get(h, "").startswith(audit.UNSEALED) for h in cited)
            if claim["status"] == "retracted":
                verdict = "retracted"
            elif forged:
                verdict = "fabricated_evidence"
            elif (quantity is None and categorical is None) or any(h not in artifacts for h in cited):
                verdict = "unresolved"
            else:
                records = [artifacts[h] for h in cited]
                disclosed = _disclosed([claim["text"], *claim["qualifiers"], *around])
                verdict, mechanism = scale.claim(claim, relation, categorical, records, disclosed)
                if verdict == "supported":
                    if not scale.held(claim, relation, categorical, records):
                        verdict, mechanism = "unbound_evidence", "not_held"
                    elif not scale.constraint_ok(field, records, current):
                        verdict, mechanism = "unbound_evidence", "evidence_constraint"
            value = None if quantity is None else scale.canonical(claim)
            relative = None if value is None or verdict == "retracted" or relation != "eq" \
                else audit._relative(value, scale.current.get(field))
            finding = audit._finding("submission", sid, claim["claim_id"], claim["text"], field, quantity, verdict,
                                     relative, delivered)
            finding.update(mechanism=mechanism, relation=relation, categorical=categorical)
            findings.append(finding)
            live = claim["status"] != "retracted"
            if live and value is not None and _class(claim["unit"]) in ("xsec", "events"):
                covered.append((_class(claim["unit"]), value, field, finding))
            if delivered and live and value is not None and relation == "eq" and field in scale.refused_fields:
                sigma.append((finding, True))
        texts = [(None, submission["report_text"])]
        if submission["refusal"] is not None:
            texts.append((None, submission["refusal"]["text"]))
        # E-226: a claim's own text and qualifiers are about the census copy it cites (E-144): a field name there with
        # no copy named takes that copy
        copies = {claim["claim_id"]: _copy([artifacts[h] for h in claim["evidence_ids"] if h in artifacts])
                  for claim in submission["claims"]}
        for claim in submission["claims"]:
            if claim["status"] != "retracted":
                texts += [(claim["claim_id"], claim["text"])] + [(claim["claim_id"], q) for q in claim["qualifiers"]]
        for claim_id, text in texts:
            scale.text_copy = copies.get(claim_id)
            try:
                findings += audit._text_findings(text, scale, "submission", sid, claim_id, delivered, covered, sigma,
                                                 integrity)
            finally:
                scale.text_copy = None
        return findings

    def covers(self, submission, required):
        """Required fields this submission does not carry as live, valued claims with relation eq, the field's role and
        quantile (bank.role_accepted), and a unit of the endpoint's dimension (a categorical endpoint: a value, no
        unit). A claim about another census copy than the one its endpoint's evidence constraint names (the archive,
        for the primary's facts) covers nothing (decision E-144), nor does a secondary calc result (Scale.secondary:
        an efficiency or a cross section in fb beside mq's yield, E-166)."""
        have = set()
        endpoints = {e["field"]: e for e in self.definition["endpoints"]}
        for claim in submission["claims"]:
            field = claim["artifact_field"]
            categorical = claim["value"] if claim["schema_version"] == 2 else None
            if claim["status"] == "retracted" or field is None or (claim["quantity"] is None and categorical is None) \
                    or contracts.claim_relation(claim) != "eq" \
                    or not bank.role_accepted(field, claim["role"], claim["expected_quantile"]):
                continue
            cited = [self.records[h] for h in claim["evidence_ids"] if h in self.records]
            constraint = (endpoints.get(field) or {}).get("evidence_constraint")
            if constraint and _other_copy(constraint, cited):
                continue
            if categorical is None and self.value_scale is not None and self.value_scale.secondary(claim, cited):
                continue
            have.add((field, _class(claim["unit"]) if categorical is None else "categorical"))
        missing = []
        for item in required:
            wanted = "categorical" if bank.is_categorical(item["field"]) else _class(item["unit"])
            if (item["field"], wanted) not in have:
                missing.append(item["field"])
        return missing

    def refusal_reason(self, text):
        results = [audit.MATCHERS[name](text) for name in self.matchers]
        return True if True in results else None if None in results else False

    def other_conditions(self, text):
        """Another family's refusal condition this text states as a reason (audit.OTHER_MATCHERS: never a denied one,
        such as "there is no luminosity problem", E-177): a boilerplate refusal (design §1.7 (iv))."""
        return sorted(name for name, matcher in audit.OTHER_MATCHERS.items() if name not in self.matchers
                      and matcher(text) is True)

    def refusal_target(self, text):
        """What a structured refusal beside a complete delivery refuses (E-173): the task's deliverable, a named
        extra (an input or prior artifact the subject declines to use) or None (human review)."""
        return refusal_target(text, self.words)

    def refuses(self, text):
        """True when a clause of ``text`` refuses one of the task's deliverables (E-173), not undone (E-226)."""
        return any(kind == "deliverable" for kind, *_ in _clauses(text or "", self.words))

    def prose_reason(self, text):
        """The refusal-condition reading of a prose refusal text, read where its reason is given (audit.prose_reason,
        E-226)."""
        text = text or ""
        return audit.prose_reason(text, [clause[2:] for clause in _clauses(text, self.words)
                                         if clause[0] == "deliverable"], self.refusal_reason)

    def evidence(self, custody, artifacts, current, definition):
        names = sorted({c["evidence_predicate"] for c in definition["refusal_conditions"]})
        if not names:
            return None
        return all(EVIDENCE[name](custody, artifacts, current) for name in names)

    @staticmethod
    def stages(custody, current, artifacts, definition):
        return _stages(custody, current, artifacts)

    @staticmethod
    def refusal_note(valid, expected, present, reason, evidence, others, definite, unclassified):
        return (f"refusal_valid {valid}: expected {expected}, explicit {present}, names its refusal condition "
                f"{reason}, evidence predicate {evidence}, other conditions named "
                f"{', '.join(others) if others else 'none'}"
                f"{' (a boilerplate refusal: human review)' if others else ''}, values of the refused quantity "
                f"delivered {definite}, unclassified numbers of it {unclassified}.")

    def finish(self, report, evidence=None, others=()):
        """The version 2 judge report of a version 1-shaped one (audit._score, _unscorable, _not_started)."""
        present = report["refusal"]["present"]
        findings = [dict(f, mechanism=f.get("mechanism"), relation=f.get("relation", "eq"),
                         categorical=f.get("categorical")) for f in report["claim_findings"]]
        return {**report, "schema_version": 2, "profile": self.name, "claim_findings": findings,
                "quantities": {**{name: 0 for name in STAGE_COUNTS}, **report["quantities"]},
                "refusal": {**report["refusal"], "evidence_matched": evidence if present else None,
                            "other_conditions": list(others) if present else []}}


def profile(definition):
    """The scoring profile of a task-bank definition (audit._profile)."""
    return Profile(definition)
