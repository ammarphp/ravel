"""lhapdf-pdf-sets blocks on own .info and run-card texts."""
SKILL = "lhapdf-pdf-sets"
INFO = "SetDesc: own fixture\nSetIndex: 99900\nNumMembers: 3\nErrorType: replicas\nFlavors: [-2, -1, 21, 1, 2, 22, 11, -11]\n"


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert set(handbook.listed(SKILL)) == {"pdf-info-flavours", "beam-readback"}


def test_info_summary(handbook):
    summary = handbook.load(SKILL, "pdf-info-flavours")["pdf_set_summary"](INFO)
    assert summary == {"lhaid": 99900, "members": 3, "error_type": "replicas",
                       "flavours": [-2, -1, 21, 1, 2, 22, 11, -11], "leptons_and_photon": [-11, 11, 22]}


def test_beam_readback_finds_the_lepton_leg_default(handbook):
    mismatch = handbook.load(SKILL, "beam-readback")["beam_mismatch"]
    card = " 1 = lpp1 ! beam 1 type\n 0 = lpp2 ! beam 2 type\n 6500 = ebeam1\n 1000 = ebeam2\n"
    assert mismatch(card, (1, 1)) == [("lpp2", "0", 1)]
    assert mismatch(card.replace(" 0 = lpp2", " 1 = lpp2"), (1, 1)) == []
