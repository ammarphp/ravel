# Component inventory

Rendered by `python scripts/maintenance/render_component_inventory.py`.
Run it with `--check` in the same full-profile environment to detect drift.
The Python rows record declared requirements and metadata visible to the generating
interpreter. Version compatibility is established through the declared checks.
Licence fields use License-Expression, then License (first line only), then licence
classifiers. Missing fields are `unknown`; absent metadata is `metadata not installed`.
Native rows report licence names and installation boundaries declared in the manifest,
not an installed-tool census. These are packaging and installation facts.
See [tool licences](tool-licences.md) for process boundaries and
[copied material](../../THIRD-PARTY-NOTICES.md) for files retained in the source tree.

| Python requirement | Declared in | Installed version | Metadata licence |
|---|---|---|---|
| awkward==2.6.7 | base package, full host profile | 2.6.7 | BSD-3-Clause |
| cabinetry==0.6.0 | base package, full host profile | 0.6.0 | BSD 3-Clause |
| camb==1.6.5 | extra: cosmology, full host profile | 1.6.5 | LicenseRef-LGPLv3-arxiv |
| certifi&gt;=2024.8.30 | base package, full host profile | 2026.10.18 | MPL-2.0 |
| classy==3.4.1.0 | extra: cosmology, full host profile | 3.4.1.0 | unknown |
| cobaya==3.6.2 | extra: cosmology, full host profile | 3.6.2 | LGPL-3.0-or-later AND LicenseRef-GFDL-1.3-or-later |
| dynesty==2.1.5 | base package, full host profile | 2.1.5 | MIT |
| emcee==3.1.6 | base package, full host profile | 3.1.6 | MIT |
| flavio==2.7.1 | base package, full host profile | 2.7.1 | MIT |
| func-adl-servicex-xaodr25==2.5.0.25.2.80 | base package, full host profile | 2.5.0.25.2.80 | BSD-3-Clause |
| hatchling==1.27.0 | full host profile | 1.27.0 | MIT |
| hepdata-cli==0.3.1 | base package, full host profile | 0.3.1 | GPLv3 |
| hf-xet==1.7.0 | base package, full host profile | 1.7.0 | Apache-2.0 |
| hist==2.8.0 | base package, full host profile | 2.8.0 | License :: OSI Approved :: BSD License |
| huggingface-hub==1.33.0 | base package, full host profile | 1.33.0 | Apache-2.0 |
| iminuit==2.32.0 | base package, full host profile | 2.32.0 | MIT+LGPL |
| jax[cpu]==0.4.35 | base package, full host profile | 0.4.35 | Apache-2.0 |
| jaxlib==0.4.35 | base package, full host profile | 0.4.35 | Apache-2.0 |
| jsonpatch==1.33 | base package, full host profile | 1.33 | Modified BSD License |
| jsonschema&gt;=4.23,&lt;5 | base package, extra: source-validation, full host profile | 4.26.0 | MIT |
| langchain-core==1.6.7 | base package, full host profile | 1.6.7 | MIT |
| langgraph==1.2.14 | base package, full host profile | 1.2.14 | MIT |
| langgraph-checkpoint==4.2.0 | base package, full host profile | 4.2.0 | MIT |
| langgraph-checkpoint-sqlite==3.1.1 | base package, full host profile | 3.1.1 | MIT |
| matplotlib==3.9.4 | base package, full host profile | 3.9.4 | License agreement for matplotlib versions 1.3.0 and later |
| matplotlib&gt;=3.9.4,&lt;3.10 | extra: replay, extra: science | 3.9.4 | License agreement for matplotlib versions 1.3.0 and later |
| mplhep==0.3.59 | base package, full host profile | 0.3.59 | MIT |
| mplhep&gt;=0.3.59,&lt;1 | extra: science | 0.3.59 | MIT |
| mpmath==1.3.0 | base package, full host profile | 1.3.0 | BSD |
| numpy==1.26.4 | base package, full host profile | 1.26.4 | Copyright (c) 2005-2023, NumPy Developers. |
| numpy&gt;=1.26.4,&lt;2 | extra: classifier, extra: measurement, extra: replay, extra: science | 1.26.4 | Copyright (c) 2005-2023, NumPy Developers. |
| onnx==1.23.0 | base package, extra: classifier, full host profile | 1.23.0 | Apache-2.0 |
| onnxruntime==1.30.0 | base package, extra: classifier, full host profile | 1.30.0 | MIT License |
| packaging&gt;=24.2,&lt;27 | base package, full host profile | 25.0 | License :: OSI Approved :: Apache Software License; License :: OSI Approved :: BSD License |
| pandas==2.2.3 | base package, full host profile | 2.2.3 | BSD 3-Clause License |
| particle==0.26.2 | base package, full host profile | 0.26.2 | BSD-3-Clause |
| Pillow&gt;=10,&lt;13 | base package, extra: figures, full host profile | 12.3.0 | MIT-CMU |
| pydantic==2.14.0 | base package, full host profile | 2.14.0 | MIT |
| pyhf[minuit]==0.7.6 | base package, extra: replay, full host profile | 0.7.6 | Apache-2.0 |
| pypdf&gt;=5,&lt;7 | base package, extra: figures, full host profile | 6.21.1 | BSD-3-Clause |
| pypdfium2==5.14.0 | base package, full host profile | 5.14.0 | BSD-3-Clause, Apache-2.0, dependency licenses |
| pySecDec==1.6.6 | base package, full host profile | 1.6.6 | GPLv3 |
| pyslha==3.3.2 | base package, full host profile | 3.3.2 | License :: OSI Approved :: GNU General Public License v3 (GPLv3) |
| pytest&gt;=8.3.5,&lt;9 | extra: test, full host profile | 8.4.2 | MIT |
| PyYAML&gt;=6.0.2,&lt;7 | base package, extra: replay, extra: source-tables, full host profile | 6.0.3 | MIT |
| scipy==1.14.1 | base package, full host profile | 1.14.1 | Copyright (c) 2001-2002 Enthought, Inc. 2003-2024, SciPy Developers. |
| scipy&gt;=1.13.1,&lt;1.15 | extra: measurement, extra: replay, extra: science | 1.14.1 | Copyright (c) 2001-2002 Enthought, Inc. 2003-2024, SciPy Developers. |
| servicex==3.3.1 | base package, full host profile | 3.3.1 | BSD-3-Clause |
| smelli==2.4.3 | base package, full host profile | 2.4.3 | MIT |
| snakemake==9.27.0 | base package, full host profile | 9.27.0 | MIT |
| snakemake-executor-plugin-cluster-generic==1.0.9 | base package, full host profile | 1.0.9 | MIT |
| spey==0.2.6 | base package, extra: measurement, full host profile | 0.2.6 | MIT |
| sympy==1.14.0 | base package, full host profile | 1.14.0 | BSD |
| sympy&gt;=1.14.0,&lt;2 | extra: symbolic | 1.14.0 | BSD |
| tokenizers==0.22.1 | base package, full host profile | 0.22.1 | License :: OSI Approved :: Apache Software License |
| uproot==5.3.12 | base package, full host profile | 5.3.12 | BSD-3-Clause |
| uproot&gt;=5.3,&lt;6 | extra: science | 5.3.12 | BSD-3-Clause |
| wilson==2.5.2 | base package, full host profile | 2.5.2 | MIT |

| Native group | Manifest licences | Declared installation boundary |
|---|---|---|
| agent-sources | GPL-3.0-or-later | prefix destination: {CONFIG}; prefix destination: {TOOLS} |
| analysis-catalogue | GPL-3.0-or-later | prefix destination: {P}; prefix destination: {TOOLS} |
| checkmate | GPL-2.0-only; GPL-2.0-or-later; GPL-3.0-or-later | own environment: {ENVS}/checkmate; own environment: {ENVS}/pythia82; prefix destination: {TOOLS} |
| compiler-bootstrap | BSD-3-Clause | own environment: {ENVS}/host-build |
| container-runtime | Apache-2.0 | prefix destination: {CONTAINERS}; prefix destination: {TOOLS} |
| contur | GPL-2.0-or-later; GPL-3.0-or-later | own environment: {ENVS}/herwig; pip interpreter: {ENVS}/rivet/bin/python; prefix destination: {ENVS}; prefix destination: {SHARE} |
| cosmology | LGPL-3.0-or-later; LicenseRef-LGPLv3-arxiv; LicenseRef-upstream | no install steps |
| diagram-consumers | GPL-3.0-only | pip interpreter: {ENVS}/diagrams/bin/python |
| easyscan | Apache-2.0; GPL-2.0-or-later; GPL-3.0-or-later | own environment: {ENVS}/easyscan; prefix destination: {CONFIG}; prefix destination: {TOOLS} |
| feyngraph | MPL-2.0 | own environment: {ENVS}/diagrams; pip interpreter: {ENVS}/diagrams/bin/python; prefix destination: {TOOLS} |
| finite-integrals | GPL-3.0-or-later | own environment: {ENVS}/integrals |
| iris | BSD-3-Clause | no install steps |
| lhapdf-sets | LicenseRef-upstream | prefix destination: {ENVS} |
| ma5 | GPL-3.0-or-later | prefix destination: {TOOLS} |
| madgraph | GPL-3.0-or-later; LicenseRef-MG5aMC | own environment: {ENVS}/mg5; own environment: {ENVS}/mg5-3; prefix destination: {TOOLS} |
| mcfm-amplitudes | GPL-3.0-or-later | prefix destination: {CONTAINERS}; prefix destination: {P}; prefix destination: {TOOLS}; separate container image |
| mg5-py8-interface | LicenseRef-MG5aMC | prefix destination: {TOOLS} |
| ml | BSD-3-Clause; MIT | own environment: {ENVS}/ml; pip interpreter: {ENVS}/ml/bin/python |
| nyx | BSD-3-Clause; BSD-3-Clause-LBNL | prefix destination: {TOOLS} |
| pdg | BSD-3-Clause; CC-BY-4.0 | prefix destination: {SHARE} |
| publication | BSD-3-Clause; BSD-3-Clause AND Apache-2.0; EPL-1.0; GPL-2.0-or-later; LGPL-2.1-or-later | own environment: {ENVS}/reports |
| python-host | none declared | declared environment output: {REPO}/.venv; declared environment output: {REPO}/.venv-sfitter; declared environment output: {REPO}/.venv-smodels; prefix destination: {REPO} |
| recast-base | GPL-2.0-or-later; GPL-3.0-or-later; LGPL-2.1-or-later | own environment: {ENVS}/recast; prefix destination: {TOOLS} |
| research-host | none declared | prefix destination: {CONFIG} |
| restframes | MIT | prefix destination: {BIN}; prefix destination: {TOOLS} |
| rivet-shower | GPL-2.0-or-later; GPL-3.0-or-later | own environment: {ENVS}/rivet; prefix destination: {BIN}; prefix destination: {ENVS} |
| root-combine | LGPL-2.1-or-later; LicenseRef-upstream | separate container image |
| sfitter | MIT | pip interpreter: {REPO}/.venv-sfitter/bin/python; prefix destination: {TOOLS} |
| simpleanalysis | Apache-2.0 | own environment: {ENVS}/pipeline; separate container image |
| site-access | none declared | no install steps |
| site-root-wms | none declared | declared environment output: {P}/.ravel-site/site-analysis; prefix destination: {P} |
| smodels | CC-BY-4.0 | own environment: {ENVS}/smodels311; pip interpreter: {ENVS}/smodels311/bin/python; prefix destination: {CONFIG}; prefix destination: {SHARE} |
| spectrum | GPL-3.0-only; LicenseRef-SPheno | own environment: {ENVS}/spectrum; prefix destination: {TOOLS} |
| tex | none declared | prefix destination: {BIN} |
| wolfram | GPL-3.0-only; GPL-3.0-or-later; LGPL-3.0-or-later; LicenseRef-FeynRules | prefix destination: {CONFIG}; prefix destination: {TOOLS} |
