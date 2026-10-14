"""Readings (§2.5.1) and obligation censuses for request-plan tests, built with exact spans.

Each case is a request a deterministic reader plus a host could read into these records. The
readings are hand-built fixtures for the plan stream; they are not the reader's output.
"""
import hashlib

from ravel.workflow import task_completion

AUTHOR = {'actor': 'deterministic-reader', 'host': None, 'model': None, 'invocation_id': None,
          'fresh_context': None, 'record': None}


class Reading:
    def __init__(self, prompt):
        self.prompt = prompt
        self.doc = {'schema_version': 1, 'kind': 'request-reading',
                    'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                    'reader': {'module': 'ravel.workflow.request_reading', 'source_sha256': '0' * 64},
                    'authors': [dict(AUTHOR)], 'witness': [], 'facts': [], 'constraints': [], 'deliverables': [],
                    'ambiguities': [], 'boundaries': [], 'dismissed': []}
        self.obligations = list(task_completion.initial_requirements(prompt)['obligations'])

    def span(self, text, nth=0):
        start = -1
        for _ in range(nth + 1):
            start = self.prompt.index(text, start + 1)
        return {'start': start, 'end': start + len(text), 'text': text}

    def fact(self, type_, value, text=None, *, authority='user_quoted', critical=False):
        fid = f'F{len(self.doc["facts"]) + 1}'
        evidence, witness = [], None
        if text is not None:
            evidence = [self.span(text)]
            witness = f'W{len(self.doc["witness"]) + 1}'
            self.doc['witness'].append({'id': witness, 'type': type_, 'value': value, 'span': evidence[0]})
        self.doc['facts'].append({'id': fid, 'type': type_, 'value': value, 'evidence': evidence,
                                  'authority': authority, 'witness': witness, 'physics_critical': critical})
        return fid

    def dismiss(self, type_, text, reason, note='not a physics value of this request'):
        wid = f'W{len(self.doc["witness"]) + 1}'
        self.doc['witness'].append({'id': wid, 'type': type_, 'value': {}, 'span': self.span(text)})
        self.doc['dismissed'].append({'witness': wid, 'reason': reason, 'note': note})
        return wid

    def constraint(self, type_, value, text):
        kid = f'K{len(self.doc["constraints"]) + 1}'
        self.doc['constraints'].append({'id': kid, 'type': type_, 'value': value, 'evidence': [self.span(text)]})
        return kid

    def obligation(self, kind, text, **criteria):
        oid = f'O{len(self.obligations)}'
        self.obligations.append({'id': oid, 'kind': kind, 'statement': text, 'criteria': criteria or {'text': text},
                                 'evidence': [self.span(text)]})
        return oid

    def deliverable(self, kind, claim_kind, obligation_ids, **require):
        did = f'D{len(self.doc["deliverables"]) + 1}'
        self.doc['deliverables'].append({'id': did, 'obligation_ids': list(obligation_ids),
                                         'artifact': {'kind': kind, 'require': require}, 'claim_kind': claim_kind})
        return did

    def ambiguity(self, issue, text=None, *, critical=False, blocks=(), readings=('a', 'b')):
        aid = f'A{len(self.doc["ambiguities"]) + 1}'
        self.doc['ambiguities'].append({
            'id': aid, 'evidence': [self.span(text)] if text else [], 'issue': issue,
            'readings': [{'id': r, 'value': {'reading': r}, 'authority': 'agent_inference', 'source': None}
                         for r in readings],
            'default': None, 'observable_impact': True, 'reversible': True, 'physics_critical': critical,
            'blocks': list(blocks), 'status': 'open', 'resolution': None})
        return aid

    def boundary(self, cls, obligation_ids, text, statement, would):
        bid = f'B{len(self.doc["boundaries"]) + 1}'
        self.doc['boundaries'].append({'id': bid, 'class': cls, 'obligation_ids': list(obligation_ids),
                                       'statement': statement, 'would_make_possible': would,
                                       'evidence': [self.span(text)]})
        return bid

    def contract(self):
        return {'prompt': self.prompt, 'task_requirements': {
            'schema_version': 1, 'prompt_sha256': self.doc['prompt_sha256'], 'obligations': self.obligations,
            'assignments': [], 'amendments': [], 'parent_acceptance_scope': task_completion.PARENT_ACCEPTANCE_SCOPE}}


def muon_collider_self_coupling():
    r = Reading('What would a 10 TeV muon collider tell us about the Higgs self-coupling?')
    r.fact('collider', {'beams': 'mu+ mu-'}, 'muon collider')
    r.fact('collision_energy', {'value': 10000, 'unit': 'GeV'}, '10 TeV', critical=True)
    o = r.obligation('quantity', 'Higgs self-coupling')
    r.deliverable('inference', 'estimate', [o], level='expected')
    r.ambiguity('integrated luminosity: a requester value or one cited from a located projection', critical=True,
                blocks=[o])
    r.ambiguity('detector treatment: parton level or a muon-collider card')
    return r


def displaced_dimuon_background():
    r = Reading('Estimate the irreducible background to a displaced dimuon dark-photon search at LHCb.')
    r.fact('experiment', {'name': 'LHCb'}, 'LHCb')
    r.fact('signature', {'final_state': 'displaced dimuon'}, 'displaced dimuon')
    o1 = r.obligation('quantity', 'irreducible background')
    o2 = r.obligation('method', 'Estimate the irreducible background', estimate='data-driven')
    r.deliverable('table', 'finding', [o1])
    r.deliverable('binned_values', 'prediction', [o1], event_level='particle')
    r.boundary('inaccessible_input', [o2], 'Estimate the irreducible background',
               'a data-driven estimate needs experiment data for the relevant stream',
               'supplied data or published background templates')
    r.ambiguity('which SM processes count as irreducible', 'irreducible', critical=True, blocks=[o1])
    return r


def spin_correlation_agreement():
    r = Reading('Compare the ATLAS and CMS ttbar spin-correlation measurements and tell me if they agree.')
    r.fact('measurement', {'locator': 'ATLAS ttbar spin-correlation measurement'}, 'ATLAS')
    r.fact('measurement', {'locator': 'CMS ttbar spin-correlation measurement'}, 'CMS')
    o = r.obligation('deliverable', 'tell me if they agree')
    r.deliverable('table', 'agreement', [o])
    r.ambiguity('inter-experiment correlation of systematic uncertainties', critical=True, blocks=[o])
    return r


def tagger_method_study():
    r = Reading('Train a graph network to tag boosted Higgs to bb and compare with ParticleNet.')
    r.fact('method', {'name': 'graph network'}, 'graph network')
    r.fact('baseline', {'name': 'ParticleNet'}, 'ParticleNet')
    o1 = r.obligation('method', 'Train a graph network')
    o2 = r.obligation('quality', 'compare with ParticleNet')
    r.deliverable('table', 'method_performance', [o1, o2])
    r.ambiguity('the dataset', blocks=[o1])
    return r


def w_mass_triplet():
    r = Reading('Is there a consistent explanation of the W mass anomaly with a scalar triplet?')
    r.fact('measurement', {'locator': 'W boson mass measurements'}, 'W mass')
    r.fact('model', {'name': 'scalar triplet'}, 'scalar triplet')
    o = r.obligation('quantity', 'consistent explanation')
    r.deliverable('inference', 'estimate', [o])
    r.ambiguity('triplet hypercharge Y = 0 or Y = 1', critical=True, blocks=[o])
    return r


def binned_yield_template():
    prompt = ('Run autonomously: predict the binned signal yields of a wino-bino model at m = 550, 200 GeV in the '
              'three-lepton signal regions at 13 TeV with 35.9 fb-1, with Pythia shower and Delphes detector '
              'simulation, and fill the supplied template yields.yaml. Do not use HEPData values.')
    r = Reading(prompt)
    r.fact('parameter_point', {'masses': [550, 200], 'unit': 'GeV'}, 'm = 550, 200 GeV', critical=True)
    r.fact('collision_energy', {'value': 13000, 'unit': 'GeV'}, '13 TeV', critical=True)
    r.fact('luminosity', {'value': 35.9, 'unit': 'fb-1'}, '35.9 fb-1', critical=True)
    r.dismiss('number', 'three', 'context_only')
    k1 = r.constraint('requested_stage', {'stage': 'shower'}, 'Pythia shower')
    k2 = r.constraint('requested_stage', {'stage': 'detector'}, 'Delphes detector simulation')
    r.constraint('template', {'locator': 'yields.yaml'}, 'fill the supplied template yields.yaml')
    r.constraint('source_restriction', {'kind': 'no-value-extraction', 'classes': ['hepdata']}, 'Do not use HEPData values')
    r.constraint('delegation', {'authority_granted': False}, 'Run autonomously')
    o1 = r.obligation('deliverable', 'predict the binned signal yields')
    r.obligation('method', 'Pythia shower', constraint=k1)
    r.obligation('method', 'Delphes detector simulation', constraint=k2)
    o4 = r.obligation('deliverable', 'fill the supplied template yields.yaml')
    r.deliverable('table', 'prediction', [o1, o4], event_level='detector')
    r.ambiguity('cross-section convention: order and charge states', critical=True, blocks=[o1])
    return r


def prescribed_significance_contour():
    prompt = ('For a Z prime with kinetic mixing at 8 TeV and 20 fb-1, find the contour Sig = 2(sqrt(S+B) - sqrt(B)) = 2 '
              'in the mass-coupling plane for M = 2, 2.5 and 3 TeV, assuming an acceptance of 60%.')
    r = Reading(prompt)
    r.fact('collision_energy', {'value': 8000, 'unit': 'GeV'}, '8 TeV', critical=True)
    r.fact('luminosity', {'value': 20, 'unit': 'fb-1'}, '20 fb-1', critical=True)
    r.fact('parameter_range', {'name': 'M', 'unit': 'TeV', 'values': [2, 2.5, 3]}, 'M = 2, 2.5 and 3 TeV', critical=True)
    r.fact('efficiency', {'artifact': 'scalar', 'require': {'quantity': 'acceptance', 'value': 0.6}},
           'acceptance of 60%', critical=True)
    r.constraint('prescribed_statistic', {'verbatim': 'Sig = 2(sqrt(S+B) - sqrt(B)) = 2'}, 'Sig = 2(sqrt(S+B) - sqrt(B)) = 2')
    o = r.obligation('deliverable', 'find the contour')
    r.deliverable('inference', 'exclusion', [o], level='expected')
    r.ambiguity('background source', critical=True, blocks=[o])
    return r


def scoped_generation():
    r = Reading('Generate 10000 pp > tt~ events at 13 TeV with MadGraph and shower them with Pythia.')
    r.fact('process', {'process': 'p p > t t~'}, 'pp > tt~', critical=True)
    r.fact('collision_energy', {'value': 13000, 'unit': 'GeV'}, '13 TeV', critical=True)
    r.fact('events', {'value': 10000}, '10000')
    r.constraint('requested_stage', {'stage': 'generation'}, 'Generate')
    r.constraint('requested_stage', {'stage': 'shower'}, 'shower them')
    r.constraint('requested_tool', {'tool': 'MadGraph'}, 'MadGraph')
    o = r.obligation('deliverable', 'Generate 10000 pp > tt~ events')
    r.deliverable('event_sample', 'prediction', [o])
    return r


def preserved_recast(scan=False):
    prompt = 'Recast analysis-routine-X for a 1 TeV stop decaying to a top and a 100 GeV neutralino.'
    if scan:
        prompt = 'Recast analysis-routine-X for stops from 500 to 1500 GeV in 100 GeV steps with a 100 GeV neutralino.'
    r = Reading(prompt)
    r.fact('analysis', {'locator': 'analysis-routine-X'}, 'analysis-routine-X')
    if scan:
        r.fact('parameter_range', {'name': 'm_stop', 'unit': 'GeV', 'values': list(range(500, 1600, 100))},
               '500 to 1500 GeV in 100 GeV steps', critical=True)
    o = r.obligation('deliverable', 'Recast analysis-routine-X')
    r.deliverable('inference', 'exclusion', [o])
    return r


def stated_counts():
    r = Reading('We see 7 events on an expected background of 2.1 +- 0.4. What is the 95% CL upper limit on the signal?')
    r.fact('observed_counts', {'artifact': 'table', 'require': {'observed': True, 'counts': 7, 'background': 2.1}},
           '7 events', critical=True)
    r.dismiss('number', '95', 'duplicate', 'the confidence level is recorded with the claim')
    o = r.obligation('deliverable', '95% CL upper limit on the signal')
    r.deliverable('inference', 'exclusion', [o])
    return r


def private_data():
    r = Reading('Use ATLAS internal Run-3 data to measure the Higgs width.')
    o = r.obligation('quantity', 'measure the Higgs width')
    r.boundary('inaccessible_input', [o], 'ATLAS internal Run-3 data', 'the requested data are private',
               'a public dataset or published measurement')
    return r


def content_free():
    r = Reading('Please make the supplied situation useful.')
    r.boundary('no_scientific_object', ['original-request'], 'Please make the supplied situation useful.',
               'nothing actionable remains', 'a scientific question or a supplied artifact with a requested result')
    return r


def requested_generator():
    prompt = ('Reproduce the measured ttbar charge asymmetry with fresh Powheg+Pythia samples and a Rivet routine, '
              'and compare with the published figure.')
    r = Reading(prompt)
    r.constraint('requested_tool', {'tool': 'Powheg'}, 'Powheg')
    r.constraint('requested_stage', {'stage': 'generation'}, 'fresh Powheg+Pythia samples')
    r.constraint('requested_stage', {'stage': 'analysis'}, 'Rivet routine')
    o1 = r.obligation('deliverable', 'Reproduce the measured ttbar charge asymmetry')
    o2 = r.obligation('quality', 'compare with the published figure')
    r.deliverable('binned_values', 'prediction', [o1, o2], event_level='particle',
                  comparison={'target': 'published_figure', 'locator': 'published charge-asymmetry figure'})
    return r


def literature_overlay():
    r = Reading('Plot the spin-independent cross section of a Higgs-portal scalar against mass, overlaid with LZ, '
                'XENONnT and PandaX-4T limits.')
    for name in ('LZ', 'XENONnT', 'PandaX-4T'):
        r.fact('record', {'locator': name + ' spin-independent limit'}, name)
    o = r.obligation('deliverable', 'overlaid with LZ, XENONnT and PandaX-4T limits')
    r.deliverable('figure', 'finding', [o])
    return r


def stated_arithmetic():
    r = Reading('How many events are expected for a cross section of 2 fb and 140 fb-1?')
    r.fact('literal_calculation', {'expression': '2 fb * 140 fb-1'}, '2 fb and 140 fb-1')
    o = r.obligation('quantity', 'How many events are expected')
    r.deliverable('scalar', 'calculation', [o])
    return r


def located_formula():
    r = Reading('Evaluate the tree-level unitarity bound of a 2HDM over tan beta from 1 to 10.')
    r.fact('parameter_range', {'name': 'tan_beta', 'unit': '', 'values': []}, 'tan beta from 1 to 10', critical=True)
    o = r.obligation('quantity', 'tree-level unitarity bound')
    r.deliverable('binned_values', 'calculation', [o])
    r.ambiguity('the scan step of tan beta', 'from 1 to 10', critical=True, blocks=[o])
    return r


def supplied_events_search():
    prompt = 'Using the attached signal.root and background.root Delphes files, set a 95% CLs limit on the signal strength.'
    r = Reading(prompt)
    r.fact('supplied_file', {'artifact': 'event_sample', 'locator': 'signal.root',
                             'require': {'format': 'delphes-root', 'level': 'detector'}}, 'signal.root', authority='supplied')
    r.fact('supplied_file', {'artifact': 'event_sample', 'locator': 'background.root',
                             'require': {'format': 'delphes-root', 'level': 'detector'}}, 'background.root',
           authority='supplied')
    o = r.obligation('deliverable', 'set a 95% CLs limit on the signal strength')
    r.deliverable('inference', 'exclusion', [o], level='expected')
    return r


def written_note():
    r = Reading('Write a four-page note on the results of runs alpha and beta.')
    r.fact('run', {'artifact': 'document', 'locator': 'runs alpha and beta'}, 'runs alpha and beta', authority='supplied')
    o = r.obligation('deliverable', 'Write a four-page note')
    r.deliverable('document', 'document', [o])
    return r


def no_deliverable_question():
    r = Reading('Does the Landau-Yang theorem forbid a broad spin-1 Z prime from decaying to two photons?')
    r.fact('theorem', {'name': 'Landau-Yang'}, 'Landau-Yang theorem')
    return r


CASES = {
    'muon-collider-self-coupling': muon_collider_self_coupling,
    'displaced-dimuon-background': displaced_dimuon_background,
    'spin-correlation-agreement': spin_correlation_agreement,
    'tagger-method-study': tagger_method_study,
    'w-mass-triplet': w_mass_triplet,
    'binned-yield-template': binned_yield_template,
    'prescribed-significance-contour': prescribed_significance_contour,
    'scoped-generation': scoped_generation,
    'preserved-recast': preserved_recast,
    'preserved-recast-scan': lambda: preserved_recast(scan=True),
    'stated-counts': stated_counts,
    'private-data': private_data,
    'content-free': content_free,
    'requested-generator': requested_generator,
    'literature-overlay': literature_overlay,
    'stated-arithmetic': stated_arithmetic,
    'located-formula': located_formula,
    'supplied-events-search': supplied_events_search,
    'written-note': written_note,
    'no-deliverable-question': no_deliverable_question,
}


def catalogue(locator):
    """A stand-in analysis catalogue: one preserved routine."""
    return locator == 'analysis-routine-X'
