"""Legacy CLI bytes are unchanged by the literature and output-contract commands.

The digests below were captured at the integration base 73a3578 by running
``cli.main([*command, '--help'])`` in process with ``sys.argv[0] == 'ravel'`` and
``COLUMNS=100`` (stdout, a NUL byte, then stderr). Every command present at the
base must keep its exact help bytes and its focused-module mapping.
"""
import contextlib
import hashlib
import io
import json
import re

import pytest

from ravel import cli

# Re-pinned at integration: the site command's description names its saved site profile.
BASE_FOCUSED_SHA256 = '81c98ede7925bea525bfafe9a7d519807b98dc1e72124cfcea95a5fa091b743d'
NEW_COMMANDS = ('output-contract', 'literature-query', 'literature-score', 'models', 'setup-models',
                'governed-runtime')
BASE_HELP_SHA256 = {
    # Re-pinned at integration: the site command's top-level description names its saved site profile.
    '': '5df07cb7464b9a7c7f67edf3146bdb09055f7dc61123c87fbd9f070cef4ddbc5',
    'agent-audit': '1d8bbeaa9eaf7b32b096450a623c35dcd6a6cc8cb73b207f71239d37c0ad8870',
    # Re-pinned at integration: the safety bundle's module description says owner setup supplies worker logins.
    'agent-cli': '7a415a079d871c31d86c73bcd8ede43c7a5648a33b2b7b965b2a14f9070daa09',
    'agent-graph': 'dc254899c7e69fa0cfbc9dea8b2f1de3da65a65bb4621a3c1a8b7a3804d5d872',
    'agent-surface': '001a6d63a3f5948bb9bc9a3b2851298ff6741c0f8dc72c29b78a4e2cd300a732',
    'agentrivet-construction': '104d546e730ce7b585ff22183d80e679c928b42276b4a8108fd26bd29093fd43',
    'amplitudes': '5f16e3f7edaa9548f8a70863b17551c4cc1faa8da6dce2c1e67206dd44d11c12',
    'analysis-witness': '820116b6bcf98a63ce207352e38d9729767f8b92fc97f510068c969151532fdc',
    'authored-analysis': '9aaaa5ffe8c6c4b869e500a5a7b330a833f27a1ed223761dfe8c0b917d84acd2',
    'backend': '35db497f238e9ed8fe7da6d9ff493b4e9f621fa943e35a5c7f7cf16fbf583d5e',
    'backend-provider': 'ebdac37aaacdeaabadfca4cc9493f539558d481c81e498ca85157e0a7e2f1384',
    'catalogue': 'e6c079036625fe54b49cbdd657d92fa33f7d5ed56a6f1ced326752cd2b184730',
    'chargino-decay-table': '3a0ab7f64f1065b0776957f16539a5bbfc97d83ceccbdddcab33cea31ff81d6e',
    'check:event_accounting': '74f736f61dedb762172a986558fc4e56da88128533252723c1bebc79c4e1cb82',
    'checkmate-events': 'ca7b6873d8fe03aef02f868559896d46c0d3c0f6ac05a9453eaa6866e4f0aa1e',
    'columnar-analysis': 'dbdb07a054c71fb61ac969e5a10560ba32fc2be9b58b60cb83bbecc4a60ffe81',
    'compare': '3a0e084fa6219bdfa76013498cf065d6f062436fd51de7c48a04440182b23bb0',
    'conformance': 'bf179b03a9b37265c7fa929a7b927aaad0f9e509913e2ec7971d5259f971a63b',
    'contur-companion': '3d518f87ee185aebdd937ae38f48bbb1c24ad7897159efe5a105c9b5fd31353d',
    'contur-yoda': 'a1eea7375d03950120ae03bbbc86dbaef53d2252e93c2a49d99fd5728d0720c0',
    'cost': '652b78294c684c406635a4fefb77585bd42dcdd7fc4667b8ab64f1948eff08a6',
    'dataset-query-quantities': '277a3ae262bba9e7ff9aac65ec12cddb1c26cc500333fafd550c3857153b97d6',
    'decision-case': '8c1ea9f142ca42bbf339f114a12880325adf62413e6edc02510c670de936caba',
    'deliver-workspace': 'ca61726b18ff69a0b5f2856a951a05bcb98e551c663568141ecdc6df1f83e268',
    'detector-card': 'a416bc129048ad70c05d3966c5ed14453883243bcb481e32782ac414e3f75fd1',
    'diagnose': 'efd392a542fce7afd167c20e54000111890086ad19b7d41898bb7ee27ab969c1',
    'diagram-analysis': '304ec1a676f44de4a660013eda769c5d4bef669ae76afdc0c2931b8d1b559be1',
    'doctor': '585aa0d3e628a8b98a6cdc3ffb40f66e6a8da150dd8320c836b7a658f8d621ee',
    'drive': 'ed855a3dda006257c7c56319c3381d2d594cc1a280c482db25f3619de307d755',
    'env': 'a299965fdf99dde5b11d575c5c0ba294c674a2575498ce17b19eed1b06d09ff5',
    'event-production': 'fbf165ff390ef54364a425d8191d1591763b540817a561c46b364f64da70da29',
    'evidence-independence': 'cbbbcaa715a9c71e288f5ecca3a8ff0351cb79bdc9c9e4cbf37fc723cf37a19d',
    'experiment-allocator': 'b9ab1ee4fa6f5c10d2017313af7a383ab9e3dc4efd7599ff818dc83d8a931c7e',
    'export-submission': '3bbdd3ac5bc87becc247f7894e5ede831ea90491db1b033f05fd07ca421e342d',
    'failed-review': 'e2adbd94a1a25432f81b090bb430e610ea76159e9f1cf4fb7c2ebf8a3b6b4c9c',
    'feyn-graph': 'c097bcf2d841fb5fe4e10b1b510f8019903c4d2ca85398b5b5d01427bdde7f9a',
    'feynarts-amplitude': '93fadda5f10ff83cd47f6d54dae73b115a9dcd711b2d808da9b61d000a8805a4',
    'figure': '8f5d4871efe9748fc4b44d96a3bf637b7735515505f899e87b1a15db11af8a6b',
    'fill-template': 'b10fa65d54c81623e198c7f229cb336c564ce4d2a04dccc99a0fc89a90f80222',
    'gate': '1c9e7f42a7d1608696f01fad39c1421817aa45647c440f630c50d73db68edc57',
    'gate-wiring': 'bcc0e72bd4c7abb111f430c002d2f69c0589f797c766180912c890d9514babad',
    'generation-efficiency': '24463d7d4295b2c0389b7064e3efaeae0683c39cbfb7010430dd262d0ef6f9b4',
    'graph': '00bc1bc30b9b67903582a147ec032439b155e83c715544f4c6a26715d186126d',
    'hypothesis-board': 'aa60e22aedc30e006a9cc77ab01ee5d43c34b5b0f74f67aa3ae5076de8f64e37',
    'inference': 'a8167b17617e0c2413b38b042b21823f21fa62d0abca49270c8c5917c26e7d83',
    'intake-plan': '47ee03b5fbe9a98c7eb0b482d7a4d08e173989421f32a409c8001d2df6343904',
    'judgment': '54c3773d6380e70a33eda05eda2d606cdf66daefe520efb918a28f4413ef6228',
    'knowledge': '4899d04bcda9c3ba20ecc9bab82cec4e843e428f174a2abc35600d172146a37f',
    'lease': 'c15431aad32c32e8d46c40ac94f041a698bd9547fce7a994d979503c39bf13b4',
    'lhe-transform': '3337dd084dc316ba85ba7057f818bb599093d4b1cd565d0ab23d489b5cee7d62',
    'lineshape': '6bd48387e4aa7326137b1486ef89d5b7ff9f6613bc7762597689e55e8bbbd267',
    'literature': 'e83f85e7646a2aa1e33e381aaeeb1e661324d571f92046652793f0f0995e9a7c',
    'literature check-cards': '407de2dea8643e3c88c78c9bb622616ed1ee53f5899ba4bbbcc19019229254ca',
    'literature follow': 'f218307609285bffb58a5432f5adbcc9ba0de7788b3920533e0ffaf88e8e4ce5',
    'literature resolve-title': 'bc2b0940d8d156e0438912bca28c8bc5075cd6747c3aae036724ba65db753b11',
    'literature tier': 'bee8370d47aa882f69ceeb1e5609cc34b376380adadf73f5b7dcfd03252d454c',
    'manuscript': '0cd69ab59d28c7f4856fa9e968c40fa034422665bed502f681c2128bd90ea700',
    'method-decision': '121efa419fa3dafa7cbe3d8965af8b8ea2c1cfdbd4afc8df820bb115bf124c88',
    'model': 'ea1e438e28123f319f33a4b70a11521387d6685f2f85e1c99a77a013bee5f0e4',
    'model-conventions': 'd58bfac7bc8af51a9157276ddea4b93931e17b805515bed2206274c6f81fa9b7',
    # Re-pinned at integration: the width-receipt subcommand that binds model admission into generation.
    'model-derivation-bridge': '79a9694bfd050df1b692380005225b64c512a03793a4b58ac433f5422de3b03f',
    'model-events': '105cb958a3d0b3efa75b01e5238118d58738571cb5aca273750ecc55229b00c7',
    'model-portfolio': '0b9761f68f60dd4e5a6d13caf04fb946d509edce12a39789c79375070640f1db',
    'model-provider-bridge': '8bca89d59ca433e7339c570a4c0d18857e868ac00d6cb918debe34952d43bce8',
    'model-spectrum': '3317da13fb601f84677295ae1c3397dba8b31962be1badd1a888a9577ebfebed',
    'model-tool-bridge': 'a6c49944637327e223b22a7166083be2a65af1d761860d440fb3777825aeb01f',
    'modes': '4899d04bcda9c3ba20ecc9bab82cec4e843e428f174a2abc35600d172146a37f',
    'mssm-physical-map': 'fa2bd2d617595b06403dfa234e224a9c7bc159015b8712e3b8226f810408fe8b',
    'normalization': 'cd0f8d415a15367fdd033989983541e746a121917d6c813705206eb9262de7f2',
    'normalization-ledger': '939b94ac66696569d00ac49ff3d37f9d1c983bee7f40e35ca731e1a4e5d37797',
    'note-profile': '1e7ee09b37b54d6bade194900482b541ae6c9835eb49cb61d0e5383cbd305b44',
    'ntuples': '53de70e660e60dbb7e358dba044f71bdc247ebebd0534c3d831abf64e48f9a46',
    'numerical-witness': 'bc609d2f4bef1b6a39b94474dbf2a80d5a2b6b974b1f10981a8cd85a6a71f3f5',
    'output-gate': '885004335423d9aab8747c2b182314892bba54f1ae81dbb2c35fc98cd6c16f3f',
    'parameter-space-sampling': 'c36d159250ccd89a070cd132459e86e52f6685599c7218226e125c1751baefbd',
    'partitions': 'fd41dfcd7a2ef4519277dddf8d98af93fcafb8c5fd4ed7b82261dc1481d83a10',
    'pilot-cost': '4ec3ed6296c66bbada07c9227aea4a5b2d0508f4c31b7a4d7dcd34446749a542',
    'procedure': '6c760712a948cdddaf21c2de81aa34598ed28f13b2f6eca7ec30c81538314dab',
    'project-instructions': '02728aef91c87637fc228df4e1f239b24a8cc7f65a6a1c22a235edc97bdaf3f4',
    'rdj': '8b2a2f1532db4f5447048a10b93ea0165831100ca6448aa3da74660ed051a3fd',
    'reco-ntuple': '7bf69f4aedf0c36eb9c84526a97fc8100700fc648f5c0a0d2bb40bab192df986',
    'release': '968a3487c52029e4b99b6cf5048a55ba894395b89ff95e3e0c3d5d7030773750',
    'research-cycle': '6b8daed02461a6daa1b0d5eb2300706404f23bfd322febb5971893163ce9d5c0',
    'research-orchestrate': '1f14b691aa4980a6b134fc0e4fe785731ed343e5cb33e93eb72541cb5c15e4bd',
    'research-preregister': '0d4762a9ff660f93cdaf175ad80b4f5b8141c9af00d0c4fd30b4b9b1efd3597d',
    'research-protocol': '97aa59fda150d2e5771fb8fbebd14aad7e5c9c7b6595f5ff864fe269b75a5385',
    # WE-1 added the literature-expand and literature-score subcommands to this module's own parser;
    # every other row still pins the 73a3578 help bytes.
    'research-tools': '6e5c31f75009b0acaf210e081fe2351d99b6badefcffbaba9bfdf380f55166d5',
    'resonance-study': 'dacb3b4ae227f439d92e39c2eab05cb036852b2b0cc80e2514aa7f42dc58c85c',
    # Re-pinned at integration: respond gains --confirm-terminal for a terminal-confirmed case approval.
    'respond': '56d7011369cc33c746f5890dc18085e20f60d974f9702a2c9b49144dd1d2f91f',
    'review': '3f1acd7ae562b9867435999b8ad28f236c335c25c1ea60ee45735976b9e1b650',
    'review-context': '820e26f50f8c06a84b118c63a7745a7d652f5cf4a99b10af08c6e525b3aff220',
    'review-rubric': '38aced467cdff0f05beec3427167c135f27482f8ae1c7c30c0191ca91d044630',
    'rivet-hepdata-map': 'e2f2ea471a4e7fc66248cd6cbb51046ad89aab7a8d62366cd62bf0766f490c85',
    'root-schema': '2f116a1e0385238f6fd1f74f3ff6f9204a7f6944737d76cacca665f25ded0175',
    'root-stream': 'ab1b2a3bfc69cde19bd64f7c62d03801e0644340bc90aaa164e820d58b9670f5',
    'sfitter-observed-events': '6b2fc07c20c362e8d8733d412a1ff23780fcfac8d23a6bb0ccc14d2c4434741a',
    'sfitter-review': 'ddeb63491fc26f8851d3e00525d69315ff15eb6ebe808b792cca6e300377cce2',
    'sfitter-workflow': '6eb0d7f1b6e6113d3b8afc464a3b8d35753951a579a23757a540a993b3efb6d8',
    'simplified-spectrum': '24c766b283875be73adb8db4ac82cba5f73a3311117a940775d948ee6c9732c4',
    # Re-pinned at integration: site gains the init and show subcommands.
    'site': '67f72cdcf3a16c0154d946e50e04deb7d621bf88ec410ef430a50e7a376bd33d',
    'site-workflow': '870fea658b3f8d25b885dc024fcabf8d1d6de3ad114cece8a7ad85a5177cfdac',
    'spec-reconcile': 'a4bd7673e98cd68cc6c4c515801ccd959272a726ad23f9bbc09a2683d7dcd2f0',
    'stage': 'bbff71f0c7208ac7e7f1cf6babada0438938e6baafd8fe7eaf87e61e40e0fb94',
    'steer': 'f6da297ec305ea445ca893cbfe9b3e241173a37d3cf35efefed501882eea055b',
    'study-grid': '534b2faaea5c159841456a091fd2a6c85e58be8e7792d093fbdb4bf1f20708b6',
    'symbolic-evaluation': '718c7bb7423c0ff85f466cec04f7b8bbbea5bf07113345347992bfec64e6f804',
    'task-completion': '16d3cef5386c20edcc856691793f9dc18faa12cf0f5e73d6677071c8b4e204a0',
    # Re-pinned at integration: the model-selection paragraph now states the cheap tier for cheap_ok cards.
    'transport': 'eb5c4a5ae96a56a3c84465fd06076bbeb1231f543269822991be97f77efd4988',
    'trap-sweep': 'f7d9b00a7a389953d226339d88f42386729fa8e5b5a10cbd0f5de5553bd15515',
    'tree-array-export': 'cd781b716b25d1964b59aea700a6af68b200eda433917899b689785ad93e8b67',
    'wms': '8be325ed2effad919f330148bcba30fe81bedd852ea55a427188189eada0e234',
    'work': 'ce812c29a755c793de0df166dbd41255b0b3b63e595a1c4d637d69c75b9250e2',
    'xsec': '23e9a0e2bb565448ac171a10076507b81d5b6e19a26fed05469d987489850c1f',
}
BASE_COMMANDS = sorted(k for k in BASE_HELP_SHA256 if k and ' ' not in k)


def _help(monkeypatch, argv):
    monkeypatch.setattr('sys.argv', ['ravel'])
    monkeypatch.setenv('COLUMNS', '100')
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main([*argv, '--help'])
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue() + '\0' + err.getvalue()


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_focused_mapping_of_every_base_command_is_unchanged():
    assert set(BASE_COMMANDS) <= set(cli.FOCUSED_COMMANDS)
    mapping = {name: list(cli.FOCUSED_COMMANDS[name]) for name in BASE_COMMANDS}
    assert hashlib.sha256(json.dumps(mapping, sort_keys=True).encode()).hexdigest() == BASE_FOCUSED_SHA256
    # The legacy literature catalogue owner is retained; the new commands are additions only.
    assert cli.FOCUSED_COMMANDS['literature'][0] == 'workflow.literature'
    assert set(cli.FOCUSED_COMMANDS) - set(BASE_COMMANDS) == set(NEW_COMMANDS)
    assert cli.FOCUSED_COMMANDS['literature-query'][0] == 'workflow.literature_query'
    assert cli.FOCUSED_COMMANDS['literature-score'][0] == 'workflow.literature_evidence_scoring'
    assert cli.FOCUSED_COMMANDS['output-contract'][0] == 'workflow.output_contract'
    # The operator entry stays a controller command and is not duplicated as a focused module.
    assert 'operator' in cli.CONTROLLER_COMMANDS and 'operator' not in cli.FOCUSED_COMMANDS


@pytest.mark.parametrize('command', [k for k in BASE_HELP_SHA256 if k])
def test_help_bytes_of_every_base_command_are_unchanged(monkeypatch, command):
    code, text = _help(monkeypatch, command.split(' '))
    assert code == 0 and _sha(text) == BASE_HELP_SHA256[command]


def test_top_level_help_only_adds_the_new_commands(monkeypatch):
    code, text = _help(monkeypatch, [])
    assert code == 0
    kept, skipping = [], False
    for line in text.splitlines(keepends=True):
        if any(line.startswith('    ' + name + ' ') for name in NEW_COMMANDS):
            skipping = True
            continue
        if skipping and line.startswith(' ' * 24):
            continue
        skipping = False
        kept.append(re.sub(r'(?<=[{,])(?:' + '|'.join(map(re.escape, NEW_COMMANDS)) + r'),', '', line))
    assert _sha(''.join(kept)) == BASE_HELP_SHA256['']
