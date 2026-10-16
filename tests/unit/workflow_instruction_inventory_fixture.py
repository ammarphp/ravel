"""Exact operational document population; original73 and prior84 retained in order; final109 exact."""
ORIGINAL_73 = ('.claude/skills/physicist-intake/SKILL.md', 'docs/cli.md', 'docs/installation.md', 'docs/reference/agentrivet-source.md', 'docs/reference/analysis-admission.md', 'docs/reference/background-model-construction.md', 'docs/reference/detector-response-moments.md', 'docs/reference/domain-adapters.md', 'docs/reference/environment.md', 'docs/reference/failure-modes.md', 'docs/reference/hs3-likelihood.md', 'docs/reference/initialized-settings-qualification.md', 'docs/reference/dataset-query-quantities.md', 'docs/reference/joint-statistical-models.md', 'docs/reference/limitations.md', 'docs/reference/model-sources.md', 'docs/reference/native-categorical.md', 'docs/reference/native-portability.md', 'docs/reference/native-saved-fit.md', 'docs/reference/parametric-exponential-construction.md', 'docs/reference/parametric-power-construction.md', 'docs/reference/prepared-runtime.md', 'docs/reference/quantities-and-measurements.md', 'docs/reference/rivet-particle-component.md', 'docs/reference/rivet-shape-components.md', 'docs/reference/routine-build.md', 'docs/reference/scientific-results.md', 'docs/reference/scope.md', 'docs/reference/statistical-construction.md', 'docs/reference/svj-study-recipes.md', 'docs/workflow/README.md', 'docs/workflow/checklists/check-ins.md', 'docs/workflow/checklists/choosing-routine.md', 'docs/workflow/checklists/complex-analysis.md', 'docs/workflow/checklists/data-acquisition.md', 'docs/workflow/checklists/detector-fidelity.md', 'docs/workflow/checklists/exclusion-model.md', 'docs/workflow/checklists/figure-contract.md', 'docs/workflow/checklists/generation-settings.md', 'docs/workflow/checklists/judgment-protocols.md', 'docs/workflow/checklists/merging.md', 'docs/workflow/checklists/model-cards.md', 'docs/workflow/checklists/physics-traps.md', 'docs/workflow/checklists/plot-criteria.md', 'docs/workflow/checklists/plot-guidelines.md', 'docs/workflow/checklists/plot-naming.md', 'docs/workflow/checklists/reproduction-closure.md', 'docs/workflow/checklists/troubleshooting.md', 'docs/workflow/checklists/validation.md', 'docs/workflow/checklists/verification-ladder.md', 'docs/workflow/checklists/verification-panel.md', 'docs/workflow/reference/effmap-folding.md', 'docs/workflow/reference/example-rivet-ewk-path.md', 'docs/workflow/reference/failed-stage-review.md', 'docs/workflow/reference/initialized-settings-retained.md', 'docs/workflow/reference/native-pipeline.md', 'docs/workflow/reference/pdf-variations.md', 'docs/workflow/reference/physics-review.md', 'docs/workflow/reference/science-review.md', 'docs/workflow/reference/scientific-studies.md', 'docs/workflow/reference/scoped-workflows.md', 'docs/workflow/reference/workspace-combination-study.md', 'docs/workflow/start.md', 'docs/workflow/steps/01-environment.md', 'docs/workflow/steps/02-inputs.md', 'docs/workflow/steps/03-generate.md', 'docs/workflow/steps/04-analyze.md', 'docs/workflow/steps/05-visualize.md', 'docs/workflow/steps/06-acquire-data.md', 'docs/workflow/steps/07-exclude.md', 'docs/workflow/steps/08-scan.md', 'docs/workflow/steps/09-verify.md', 'environment/README.md')
PRIOR_84 = ('.claude/skills/physicist-intake/SKILL.md', 'docs/cli.md', 'docs/installation.md', 'docs/reference/agentrivet-source.md', 'docs/reference/analysis-admission.md', 'docs/reference/background-model-construction.md', 'docs/reference/detector-response-moments.md', 'docs/reference/domain-adapters.md', 'docs/reference/environment.md', 'docs/reference/parameter-space-sampling.md', 'docs/reference/failure-modes.md', 'docs/reference/hs3-likelihood.md', 'docs/reference/initialized-settings-qualification.md', 'docs/reference/dataset-query-quantities.md', 'docs/reference/site-workflows.md', 'docs/reference/intake-and-challenges.md', 'docs/reference/symbolic-evaluation.md', 'docs/reference/tree-array-export.md', 'docs/reference/source-graph-diagnostics-calibration.md', 'docs/reference/research-progress-and-indexed-meta-review.md', 'docs/physics/cosmic-evolution.md', 'docs/reference/contur-companion.md', 'docs/reference/joint-statistical-models.md', 'docs/reference/limitations.md', 'docs/reference/model-sources.md', 'docs/reference/native-categorical.md', 'docs/reference/native-portability.md', 'docs/reference/native-saved-fit.md', 'docs/reference/parametric-exponential-construction.md', 'docs/reference/parametric-power-construction.md', 'docs/reference/prepared-runtime.md', 'docs/reference/quantities-and-measurements.md', 'docs/reference/rivet-particle-component.md', 'docs/reference/rivet-shape-components.md', 'docs/reference/routine-build.md', 'docs/reference/scientific-results.md', 'docs/reference/scope.md', 'docs/reference/statistical-construction.md', 'docs/reference/svj-study-recipes.md', 'docs/workflow/README.md', 'docs/workflow/checklists/check-ins.md', 'docs/workflow/checklists/choosing-routine.md', 'docs/workflow/checklists/complex-analysis.md', 'docs/workflow/checklists/data-acquisition.md', 'docs/workflow/checklists/detector-fidelity.md', 'docs/workflow/checklists/exclusion-model.md', 'docs/workflow/checklists/figure-contract.md', 'docs/workflow/checklists/generation-settings.md', 'docs/workflow/checklists/judgment-protocols.md', 'docs/workflow/checklists/merging.md', 'docs/workflow/checklists/model-cards.md', 'docs/workflow/checklists/physics-traps.md', 'docs/workflow/checklists/plot-criteria.md', 'docs/workflow/checklists/plot-guidelines.md', 'docs/workflow/checklists/plot-naming.md', 'docs/workflow/checklists/reproduction-closure.md', 'docs/workflow/checklists/troubleshooting.md', 'docs/workflow/checklists/validation.md', 'docs/workflow/checklists/verification-ladder.md', 'docs/workflow/checklists/verification-panel.md', 'docs/workflow/reference/effmap-folding.md', 'docs/workflow/reference/example-rivet-ewk-path.md', 'docs/workflow/reference/failed-stage-review.md', 'docs/workflow/reference/initialized-settings-retained.md', 'docs/workflow/reference/native-pipeline.md', 'docs/workflow/reference/pdf-variations.md', 'docs/workflow/reference/physics-review.md', 'docs/workflow/reference/science-review.md', 'docs/workflow/reference/scientific-studies.md', 'docs/workflow/reference/scoped-workflows.md', 'docs/workflow/reference/workspace-combination-study.md', 'docs/workflow/start.md', 'docs/workflow/steps/01-environment.md', 'docs/workflow/steps/02-inputs.md', 'docs/workflow/steps/03-generate.md', 'docs/workflow/steps/04-analyze.md', 'docs/workflow/steps/05-visualize.md', 'docs/workflow/steps/06-acquire-data.md', 'docs/workflow/steps/07-exclude.md', 'docs/workflow/steps/08-scan.md', 'docs/workflow/steps/09-verify.md', 'environment/README.md', 'docs/workflow/reference/scientific-context-continuation.md', 'docs/workflow/reference/sfitter-source-context.md')
FINAL_INVENTORY = ('.claude/skills/physicist-intake/SKILL.md', 'docs/cli.md', 'docs/installation.md', 'docs/reference/agentrivet-source.md', 'docs/reference/analysis-admission.md', 'docs/reference/background-model-construction.md', 'docs/reference/detector-response-moments.md', 'docs/reference/domain-adapters.md', 'docs/reference/environment.md', 'docs/reference/parameter-space-sampling.md', 'docs/reference/failure-modes.md', 'docs/reference/hs3-likelihood.md', 'docs/reference/initialized-settings-qualification.md', 'docs/reference/dataset-query-quantities.md', 'docs/reference/columnar-analysis.md', 'docs/reference/authored-analysis.md', 'docs/reference/site-workflows.md', 'docs/reference/intake-and-challenges.md', 'docs/reference/symbolic-evaluation.md', 'docs/reference/tree-array-export.md', 'docs/reference/source-graph-diagnostics-calibration.md', 'docs/reference/research-progress-and-indexed-meta-review.md', 'docs/physics/cosmic-evolution.md', 'docs/reference/contur-companion.md', 'docs/reference/joint-statistical-models.md', 'docs/reference/limitations.md', 'docs/reference/model-sources.md', 'docs/reference/native-categorical.md', 'docs/reference/native-portability.md', 'docs/reference/native-saved-fit.md', 'docs/reference/parametric-exponential-construction.md', 'docs/reference/parametric-power-construction.md', 'docs/reference/prepared-runtime.md', 'docs/reference/quantities-and-measurements.md', 'docs/reference/rivet-particle-component.md', 'docs/reference/rivet-shape-components.md', 'docs/reference/routine-build.md', 'docs/reference/scientific-results.md', 'docs/reference/scope.md', 'docs/reference/statistical-construction.md', 'docs/reference/svj-study-recipes.md', 'docs/workflow/README.md', 'docs/workflow/checklists/check-ins.md', 'docs/workflow/checklists/choosing-routine.md', 'docs/workflow/checklists/complex-analysis.md', 'docs/workflow/checklists/data-acquisition.md', 'docs/workflow/checklists/detector-fidelity.md', 'docs/workflow/checklists/exclusion-model.md', 'docs/workflow/checklists/figure-contract.md', 'docs/workflow/checklists/generation-settings.md', 'docs/workflow/checklists/judgment-protocols.md', 'docs/workflow/checklists/merging.md', 'docs/workflow/checklists/model-cards.md', 'docs/workflow/checklists/physics-traps.md', 'docs/workflow/checklists/plot-criteria.md', 'docs/workflow/checklists/plot-guidelines.md', 'docs/workflow/checklists/plot-naming.md', 'docs/workflow/checklists/reproduction-closure.md', 'docs/workflow/checklists/troubleshooting.md', 'docs/workflow/checklists/validation.md', 'docs/workflow/checklists/verification-ladder.md', 'docs/workflow/checklists/verification-panel.md', 'docs/workflow/reference/effmap-folding.md', 'docs/workflow/reference/example-rivet-ewk-path.md', 'docs/workflow/reference/failed-stage-review.md', 'docs/workflow/reference/initialized-settings-retained.md', 'docs/workflow/reference/native-pipeline.md', 'docs/workflow/reference/pdf-variations.md', 'docs/workflow/reference/physics-review.md', 'docs/workflow/reference/science-review.md', 'docs/workflow/reference/scientific-studies.md', 'docs/workflow/reference/scoped-workflows.md', 'docs/workflow/reference/workspace-combination-study.md', 'docs/workflow/start.md', 'docs/workflow/steps/01-environment.md', 'docs/workflow/steps/02-inputs.md', 'docs/workflow/steps/03-generate.md', 'docs/workflow/steps/04-analyze.md', 'docs/workflow/steps/05-visualize.md', 'docs/workflow/steps/06-acquire-data.md', 'docs/workflow/steps/07-exclude.md', 'docs/workflow/steps/08-scan.md', 'docs/workflow/steps/09-verify.md', 'environment/README.md', 'docs/workflow/reference/scientific-context-continuation.md', 'docs/workflow/reference/sfitter-source-context.md', 'docs/reference/agentrivet-construction.md', 'docs/reference/amplitude-reweighting.md', 'docs/reference/manuscript-method-transfer.md', 'docs/reference/manuscript-production.md', 'docs/reference/staged-manuscript-authoring.md', 'docs/reference/model-bound-diagrams.md', 'docs/workflow/reference/research-orchestration.md', 'docs/workflow/reference/data-read-outcomes.md', 'docs/workflow/reference/literature-context.md', 'docs/workflow/reference/literature-discovery.md', 'docs/workflow/reference/sn-jnl-publication.md', 'docs/workflow/reference/task-completion.md', 'docs/workflow/reference/result-templates.md', 'docs/reference/figures-and-comparison.md', 'docs/reference/inference-engines.md', 'docs/reference/execution-backends.md', 'docs/reference/challenge-operations.md', 'docs/reference/models-and-normalization.md', 'docs/reference/event-production.md')
PRIOR_105 = FINAL_INVENTORY
FINAL_INVENTORY += ('docs/reference/tool-status.md',)
PRIOR_106 = FINAL_INVENTORY
FINAL_INVENTORY += ('docs/reference/statistics-core.md',)

PRIOR_107 = FINAL_INVENTORY
_roles_at = FINAL_INVENTORY.index('docs/reference/challenge-operations.md')
FINAL_INVENTORY = FINAL_INVENTORY[:_roles_at] + ('docs/reference/roles.md',) + FINAL_INVENTORY[_roles_at:]
FINAL_INVENTORY += ('docs/workflow/checklists/independent-numerics.md',)
FINAL_INVENTORY += ('docs/workflow/reference/width-input-materialization.md', 'docs/reference/mass-width-grid-recipes.md',
                    'docs/reference/cross-section-conventions.md')
_named_at = FINAL_INVENTORY.index('docs/workflow/reference/native-pipeline.md') + 1
FINAL_INVENTORY = FINAL_INVENTORY[:_named_at] + ('docs/workflow/reference/named-scans.md',) + FINAL_INVENTORY[_named_at:]
_delivery_at = FINAL_INVENTORY.index('docs/reference/analysis-admission.md') + 1
FINAL_INVENTORY = FINAL_INVENTORY[:_delivery_at] + ('docs/reference/deliver-workspace.md',) + FINAL_INVENTORY[_delivery_at:]
FINAL_INVENTORY += ('docs/workflow/reference/provider-policy.md',)
FINAL_INVENTORY += ('docs/workflow/checklists/conformance.md',)
FINAL_INVENTORY += ('docs/workflow/reference/supplied-document-builds.md',)
FINAL_INVENTORY += ('docs/workflow/steps/eft-conventions.md',)
_batch_at = FINAL_INVENTORY.index('docs/reference/execution-backends.md') + 1
FINAL_INVENTORY = FINAL_INVENTORY[:_batch_at] + ('docs/reference/batch-allocations.md',) + FINAL_INVENTORY[_batch_at:]
FINAL_INVENTORY = ('docs/reference/host-enforcement.md', 'docs/workflow/hooks.md') + FINAL_INVENTORY


def assert_inventory(actual):
    assert tuple(actual) == FINAL_INVENTORY
    assert tuple(x for x in actual if x in set(PRIOR_84)) == PRIOR_84
    assert len(FINAL_INVENTORY) == 121 == len(set(FINAL_INVENTORY))
    assert tuple(x for x in actual if x in set(PRIOR_105)) == PRIOR_105
    assert tuple(x for x in actual if x in set(PRIOR_106)) == PRIOR_106
    assert tuple(x for x in actual if x in set(PRIOR_107)) == PRIOR_107
    assert tuple(x for x in actual if x in set(ORIGINAL_73)) == ORIGINAL_73


def assert_site_installation_instruction(project):
    """The existing site instruction carries the prefix and qualification contract."""
    text=(project/'docs/reference/site-workflows.md').read_text()
    for marker in ('--prefix /work/ravel-tools','--lcg-view none','RAVEL_LCG_VIEW',
                   'requirements-site-wms.lock','--require-hashes','APPTAINER_CACHEDIR',
                   'APPTAINER_TMPDIR','wms.json','lcg-view.json','PYTHONNOUSERSITE=1',
                   'one release for one campaign','--min-free-gb','tester-qualification',
                   'ravel transport qualify','RAVEL_LEASE_SCOPE=batch-slot',
                   '_CONDOR_SCRATCH_DIR/.ravel-lease','--shared-state-root'):
        assert marker in text



def assert_live_steering_instruction(project):
    """The existing declared check-in document carries live steering commands."""
    text = (project / 'docs/workflow/checklists/check-ins.md').read_text()
    for marker in ('dispatch_permitted', 'steer ack', 'steering_policy', 'observed-stopped',
                   'approval_sha256_at_event', 'An unchanged receipt leaves the hold in force.',
                   'steering mirrors and missing custody',
                   'the plan node that owns it', 'no single owner holds while any'):
        assert marker in text


def assert_scheduler_profile_instruction(project):
    """The existing site instruction names the shared-filesystem profile contract."""
    text = (project / 'docs/reference/site-workflows.md').read_text()
    for marker in ('ravel-wms-condor-submit', 'ravel-wms-condor-status', 'tester-qualification',
                   'run-keys.json', 'RavelPause', 'RAVEL_LEASE_SCOPE=batch-slot',
                   'status_cache_seconds', 'missing_grace_seconds',
                   'snakemake-interface-executor-plugins>=9.3.2,<10',
                   'not on object storage', 'site_profiles.write_profile'):
        assert marker in text


def assert_amplitude_installation_instruction(project):
    """The instruction declares installation defaults and authority while the group is released.

    A withheld group's installation is not named in an operational instruction."""
    from ravel.setup import manifest as mf
    text = (project / 'docs/reference/amplitude-reweighting.md').read_text()
    if 'mcfm-amplitudes' in mf.unreleased_groups(mf.view(project)):
        for marker in ('--only mcfm-amplitudes', 'installations/mcfm-amplitudes.json'):
            assert marker not in text
        return
    for marker in ('--only mcfm-amplitudes', 'ravel-podman machine start ravel',
                   'installations/mcfm-amplitudes.json', 'ravel.paths.native_build_root()',
                   'study inputs and every backend', 'built-unqualified', 'never a human'):
        assert marker in text
