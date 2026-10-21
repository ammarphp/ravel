# Third-party notices

The project licence is [Apache-2.0](LICENSE). The table records copied files,
fixtures and retained upstream notices in this source tree; its rows state changes
where applicable. Package selections determine which rows travel in a wheel or
source distribution. Each licence/notice column names an existing retained file;
a retained licence statement is identified as such rather than as a full licence text.
Runtime tools are also acquired by the installers. The generated
[component inventory](docs/reference/component-inventory.md) records Python
requirements with installed distribution metadata and native manifest declarations.
See [tool licences](docs/reference/tool-licences.md) for installation and process boundaries.

| Copied material | Licence | Copyright | Files | Licence text |
|---|---|---|---|---|
| FeynArts 3.12 release notice: the opening comment of `FeynArts.m`, followed by one RAVEL sentence | LGPL | Copyright by Sepp Kueblbeck, Hagen Eck, and Thomas Hahn 1991-2025 | `src/ravel/data/diagram_tools/NOTICE.FeynArts.txt` | `src/ravel/data/diagram_tools/NOTICE.FeynArts.txt` (release notice) |
| Rivet 4.1.4 six-b routine, classifier models, reference YODA and support sources; Rivet 4.1.3/4.1.4 CMS cumulant routine, correlator sources and YODA 2.1.3 headers (shipped source bundles, unchanged) | GPL-3.0 | The Rivet and YODA authors (the copied files carry their upstream notices) | `src/ravel/data/analysis_assets/six-b/**`, `src/ravel/data/native_cumulants/*.{cc,hh,h,yoda.gz}` | `src/ravel/data/analysis_assets/six-b/COPYING`, `src/ravel/data/native_cumulants/LICENSE.Rivet.txt`, `src/ravel/data/native_cumulants/LICENSE.YODA.txt` |
| MadGraph5_aMC@NLO 2.9.27 card and source fixtures | MadGraph5_aMC@NLO licence (BSD-style) | Copyright (c) 2009, 2013, the MadTeam; Copyright (c) 2009, 2011 The MadGraph5_aMC@NLO Development team and Contributors | `tests/unit/fixtures/mg5-reuse-markers/**` | `tests/unit/fixtures/mg5-reuse-markers/LICENSE.MG5.txt` |
| mapyde 0.5.0 card templates: the slepton-bino parameter template, the MadGraph leading-order run card, the MadGraph-interface Pythia card and the process definitions block | Apache-2.0 | The mapyde authors (Michael Hance, Giordon Stark and contributors) | `src/ravel/data/templates/slepton_bino_param_template.slha`, `src/ravel/data/templates/madgraph_run_default_lo.dat`, `src/ravel/data/templates/pythia8_mg_interface_card.dat`, `src/ravel/data/templates/slepton_isrslep_generate.mg5` | `src/ravel/data/templates/LICENSE.mapyde.txt` |
| ATLAS published likelihoods (HEPData records ins1771533 and ins1767649): background-only workspaces and one signal patch; the workspace JSON is re-serialized or gzip-compressed without changing its content | CC BY 4.0 | The ATLAS Collaboration | `src/ravel/data/fixtures/susy-2018-06/BkgOnly.json`, `src/ravel/data/fixtures/susy-2018-06/patch_ERJR_300p0_100p0.json`, `src/ravel/data/fixtures/susy-2018-16/BkgOnly.json.gz` | `src/ravel/data/fixtures/susy-2018-06/README.md`, `src/ravel/data/fixtures/susy-2018-16/README.md` (retained licence statements) |
| EasyScan_HEP API map | Apache-2.0 | The EasyScan_HEP authors | `src/ravel/data/easyscan/upstream-api.json` | `src/ravel/data/easyscan/LICENSE.EasyScan.txt` |
| SFitter release archive (its prose is generalized and its literature references are removed) and source map | MIT | Copyright (c) 2026 heidelberg-hepml, 2026 MadGraphTeam | `tests/fixtures/sfitteragents-6072a79e.zip`, `src/ravel/data/sfitter/upstream-source.json` | `src/ravel/data/sfitter/LICENSE.upstream.txt` |
| IRIS licence record (the retained IRIS population is no longer in the package) | MIT | Copyright (c) 2025-present Gordon Watts | `src/ravel/data/iris/LICENSE.IRIS.txt` | `src/ravel/data/iris/LICENSE.IRIS.txt` |
| ServiceX API map | BSD-3-Clause | Copyright (c) 2023, IRIS-HEP SSL | `src/ravel/data/iris/servicex-api.json` | `src/ravel/data/iris/LICENSE.ServiceX.txt` |
| FlexibleSUSY 2.9.0 spectrum conventions | GPL-3.0-or-later | The FlexibleSUSY authors (upstream AUTHORS file) | `src/ravel/data/spectrum/lowmssm-2.9.0.json`, `src/ravel/data/spectrum/nmssm-2.9.0.json`, `src/ravel/data/spectrum/nmssm-tree-yukawa.json` | `src/ravel/data/spectrum/LICENSE.FlexibleSUSY.txt` |
| FeynGraph licence record | MPL-2.0 | The FeynGraph authors | `src/ravel/data/diagram_tools/upstream-api.json` | `src/ravel/data/diagram_tools/LICENSE.FeynGraph.txt` |
| HEPTAPOD licence record | GPL-3.0 | The HEPTAPOD authors (`AUTHORS.HEPTAPOD.txt`) | `src/ravel/data/diagram_tools/upstream-api.json` | `src/ravel/data/diagram_tools/LICENSE.HEPTAPOD.txt`, `src/ravel/data/diagram_tools/AUTHORS.HEPTAPOD.txt` |
| MCFM 10.2.1 add-on | GPL-3.0-or-later | Copyright (C) 2019–2022, the respective authors of MCFM | `addons/gpl/mcfm-amplitudes/**` (a separately licensed add-on, not part of the Apache-2.0 package) | `addons/gpl/mcfm-amplitudes/COPYING.GPL-3.txt`, `addons/gpl/mcfm-amplitudes/ATTRIBUTION.md` |
