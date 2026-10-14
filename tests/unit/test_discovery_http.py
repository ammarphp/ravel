"""Public discovery services: plain-client requests, HEPData record fallbacks, census index.

Every response here is recorded in the test; no network access is needed.
"""
import synthetic_identifiers as syn
import io
import json
import urllib.error

import pytest

from ravel.workflow import discovery_http, hepdata_fetch, resource_census


class _Resp(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeWeb:
    """URL -> JSON payload or HTTP status; records every request's headers."""

    def __init__(self, routes, blocked_agents=()):
        self.routes = routes
        self.blocked_agents = blocked_agents
        self.requests = []

    def __call__(self, req, timeout=None, context=None):
        url = req.full_url
        headers = {k.lower(): v for k, v in req.header_items()}
        self.requests.append((url, headers))
        if any(b in headers.get("user-agent", "") for b in self.blocked_agents):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        for key, value in self.routes.items():
            if url.startswith(key):
                if isinstance(value, int):
                    raise urllib.error.HTTPError(url, value, "status", {}, None)
                return _Resp(value)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


@pytest.fixture
def web(monkeypatch):
    def install(routes, blocked_agents=()):
        fake = FakeWeb(routes, blocked_agents)
        monkeypatch.setattr(discovery_http, "_urlopen", fake)
        return fake
    return install


HEP = "https://www.hepdata.net/record/"
INSPIRE = "https://inspirehep.net/api/literature/"

RECORD = {"recid": 1001, "version": 2,
          "record": {"recid": 1001, "inspire_id": "1008", "resources": [
              {"description": "Full statistical likelihood (pyhf)", "type": "json",
               "url": "https://www.hepdata.net/record/resource/99?landing_page=true"}]},
          "data_tables": [{"id": 1, "name": "Figure 3a Observed", "description": "Observed limit"},
                          {"id": 2, "name": "Table 2", "description": "Cutflow"}]}


def test_requests_send_json_accept_with_a_plain_client_agent(web):
    fake = web({HEP + "ins1008": RECORD})
    discovery_http.get_json(HEP + "ins1008?format=json")
    url, headers = fake.requests[0]
    assert headers["accept"] == "application/json"
    agent = headers["user-agent"]
    assert "Mozilla" not in agent and "(research use)" not in agent
    assert agent.split()[-1].count("/") == 1          # a product/version token


def test_a_blocked_agent_is_retried_with_another_plain_client(web):
    first = discovery_http.CLIENT_AGENTS[0]
    fake = web({HEP + "ins1008": RECORD}, blocked_agents=(first,))
    rec = discovery_http.get_json(HEP + "ins1008?format=json")
    assert rec["recid"] == 1001
    agents = [h["user-agent"] for _, h in fake.requests]
    assert agents[0] == first and agents[1] != first


def test_every_agent_blocked_raises_the_403(web):
    web({}, blocked_agents=tuple(discovery_http.CLIENT_AGENTS))
    with pytest.raises(urllib.error.HTTPError) as err:
        discovery_http.get_json(HEP + "ins1?format=json")
    assert err.value.code == 403


def test_record_lookup_retries_the_numeric_id_inspire_lists(web):
    web({HEP + "ins1008": 403,
         INSPIRE + "1008": {"metadata": {"external_system_identifiers": [
             {"schema": "HEPDATA", "value": "1001"}]}},
         HEP + "1001": RECORD})
    res = discovery_http.fetch_hepdata_record("1008")
    assert res["status"] == "OK"
    assert res["ref"] == "1001"
    assert res["resolved_via"] == "inspire-hepdata-id"
    assert [a["http_status"] for a in res["attempts"]] == [403]


def test_census_rung_reports_record_found_through_the_numeric_id(web):
    web({HEP + "ins1008": 403,
         INSPIRE + "1008": {"metadata": {"external_system_identifiers": [
             {"schema": "HEPDATA", "value": "1001"}]}},
         HEP + "1001": RECORD})
    r1 = resource_census.rung_hepdata("1008")
    assert r1["status"] == "OK"
    assert r1["n_tables"] == 2 and len(r1["likelihood_candidates"]) == 1
    assert r1["url"] == "https://www.hepdata.net/record/1001"


def test_served_404_maps_to_absent_in_the_census(web):
    web({HEP + "ins1002": 404,
         INSPIRE + "1002": {"metadata": {"external_system_identifiers": []}}})
    r1 = resource_census.rung_hepdata("1002")
    assert r1["status"] == "ABSENT"
    assert r1["corroborated_by_inspire"] is True


def test_403_everywhere_is_an_outage_not_an_absence(web):
    web({HEP + "ins1003": 403,
         INSPIRE + "1003": {"metadata": {"external_system_identifiers": [
             {"schema": "HEPDATA", "value": "ins1003"}]}}})
    r1 = resource_census.rung_hepdata("1003")
    assert r1["status"] == "ERROR" and r1["classification"] == "outage-or-block"


def test_hepdata_fetch_reports_absence_distinctly(web, tmp_path, capsys):
    web({HEP + "ins1004": 404,
         INSPIRE + "1004": {"metadata": {"external_system_identifiers": []}}})
    with pytest.raises(SystemExit) as end:
        hepdata_fetch.main(["--inspire", "1004", "--out", str(tmp_path)])
    assert end.value.code == hepdata_fetch.EXIT_ABSENT
    manifest = json.loads((tmp_path / "hepdata_manifest.json").read_text())
    assert manifest["status"] == "ABSENT"
    assert "no hepdata record" in capsys.readouterr().err.lower()


def test_hepdata_fetch_follows_the_numeric_record(web, tmp_path):
    web({HEP + "ins1008": 404,
         INSPIRE + "1008": {"metadata": {"external_system_identifiers": [
             {"schema": "HEPDATA", "value": "1001"}]}},
         HEP + "1001": RECORD})
    hepdata_fetch.main(["--inspire", "ins1008", "--out", str(tmp_path)])
    manifest = json.loads((tmp_path / "hepdata_manifest.json").read_text())
    assert manifest["status"] == "OK"
    assert manifest["record_ref"] == "1001"
    assert manifest["figure_index"] == {"3a": ["Figure 3a Observed"]}
    assert len(manifest["likelihoods"]) == 1


# ------------------------------------------------------------- multi-analysis + keyword census
def _offline_rungs(monkeypatch):
    """Stub the rungs that are not under test so a census runs without network or gh."""
    monkeypatch.setattr(resource_census, "rung_github",
                        lambda terms: {"status": "SKIPPED", "reason": "test"})
    monkeypatch.setattr(resource_census, "rung_routines",
                        lambda q: {"status": "OK", "query": q, "report": "stub"})
    monkeypatch.setattr(resource_census, "rung_inspire_zenodo",
                        lambda i, a: {"status": "OK", "inspire": {"total_citations": 0}})
    monkeypatch.setattr(resource_census, "rung_arxiv",
                        lambda a: {"status": "OK", "title": "stub"})


def test_several_analyses_each_get_a_file_and_one_index(web, monkeypatch, tmp_path):
    _offline_rungs(monkeypatch)
    web({HEP + "ins1008": RECORD,
         HEP + "ins1002": 404,
         INSPIRE + "1002": {"metadata": {"external_system_identifiers": []}}})
    rc = resource_census.main(["--analysis", ("inspire=1008,arxiv=" + syn.arxiv(680) + ",id=" + syn.analysis(487)),
                               "--analysis", "inspire=1002", "--rundir", str(tmp_path)])
    assert rc == 0
    folder = tmp_path / "inputs" / "resource_census"
    assert sorted(p.name for p in folder.iterdir()) == ["ins1002.json", "ins1008.json"]
    one = json.loads((folder / "ins1008.json").read_text())
    assert one["analysis_id"] == (syn.analysis(487)) and one["rungs"]["R1_hepdata"]["status"] == "OK"
    index = json.loads((tmp_path / "inputs" / "resource_census.json").read_text())
    assert index["kind"] == "resource-census-index"
    assert [e["id"] for e in index["entries"]] == ["ins1002", "ins1008"]
    assert index["entries"][0]["file"] == "inputs/resource_census/ins1002.json"
    # the lifecycle gate reads `rungs` from this file: statuses survive the flattening
    assert index["rungs"]["ins1008/R1_hepdata"]["status"] == "OK"
    assert index["rungs"]["ins1002/R1_hepdata"]["status"] == "ABSENT"
    assert "ins1008/R1_hepdata" in index["rungs_ok"]


def test_a_second_census_adds_to_the_index_instead_of_replacing_it(web, monkeypatch, tmp_path):
    _offline_rungs(monkeypatch)
    web({HEP + "ins1008": RECORD, HEP + "ins1006": RECORD})
    assert resource_census.main(["--inspire", "1008", "--rundir", str(tmp_path)]) == 0
    single = json.loads((tmp_path / "inputs" / "resource_census.json").read_text())
    # one analysis keeps the familiar single-census fields at the top level
    assert single["inspire"] == "1008" and "R1_hepdata" in single["rungs"]
    assert resource_census.main(["--inspire", "1006", "--rundir", str(tmp_path)]) == 0
    index = json.loads((tmp_path / "inputs" / "resource_census.json").read_text())
    assert [e["id"] for e in index["entries"]] == ["ins1006", "ins1008"]


def test_an_existing_single_census_is_kept_when_the_index_is_written(web, monkeypatch, tmp_path):
    _offline_rungs(monkeypatch)
    web({HEP + "ins1006": RECORD})
    legacy = {"schema_version": 1, "analysis_id": "X", "inspire": "1005", "arxiv": None,
              "rungs": {"R1_hepdata": {"status": "OK"}}, "manual_rungs": [], "rungs_ok": ["R1_hepdata"]}
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "resource_census.json").write_text(json.dumps(legacy))
    assert resource_census.main(["--inspire", "1006", "--rundir", str(tmp_path)]) == 0
    kept = json.loads((tmp_path / "inputs" / "resource_census" / "ins1005.json").read_text())
    assert kept["analysis_id"] == "X"
    index = json.loads((tmp_path / "inputs" / "resource_census.json").read_text())
    assert {e["id"] for e in index["entries"]} == {"ins1005", "ins1006"}


SEARCH = {"total": 2, "results": [
    {"inspire_id": "1008", "recid": 1001, "title": "Search for a heavy resonance in dilepton events",
     "arxiv_id": ("arXiv:" + syn.arxiv(680)), "collaborations": ["CMS"], "total_tables": 2,
     "analyses": [{"type": "rivet", "analysis": "https://rivet.hepforge.org/analyses/SYN_9563_I1577"}]},
    {"inspire_id": "1007", "recid": 40000, "title": "A second dilepton search",
     "arxiv_id": ("arXiv:" + syn.arxiv(681)), "collaborations": ["ATLAS"], "total_tables": 5, "analyses": []}]}
LIT = {"hits": {"total": 1, "hits": [
    {"metadata": {"control_number": 1007, "titles": [{"title": "A second dilepton search"}],
                  "arxiv_eprints": [{"value": (syn.arxiv(681))}],
                  "report_numbers": [{"value": "LAB-EP-9019-001"}, {"value": (syn.analysis(488))}]}}]}}


def test_keyword_mode_records_the_search_and_censuses_each_candidate(web, monkeypatch, tmp_path):
    _offline_rungs(monkeypatch)
    fake = web({"https://www.hepdata.net/search/": SEARCH,
                "https://inspirehep.net/api/literature?": LIT,
                HEP + "ins1008": RECORD, HEP + "ins1007": RECORD})
    rc = resource_census.main(["--keyword", "dilepton resonance", "--limit", "2",
                               "--rundir", str(tmp_path)])
    assert rc == 0
    folder = tmp_path / "inputs" / "resource_census"
    search = json.loads((folder / "search-dilepton-resonance.json").read_text())
    assert search["kind"] == "search" and search["query"] == "dilepton resonance"
    cands = {c["inspire"]: c for c in search["candidates"]}
    assert set(cands) == {"1008", "1007"}
    assert cands["1007"]["analysis_id"] == (syn.analysis(488))
    assert sorted(cands["1007"]["found_by"]) == ["hepdata", "inspire"]
    index = json.loads((tmp_path / "inputs" / "resource_census.json").read_text())
    assert [s["id"] for s in index["searches"]] == ["search-dilepton-resonance"]
    assert {e["id"] for e in index["entries"]} == {"ins1008", "ins1007"}
    assert index["rungs"]["search-dilepton-resonance/hepdata_search"]["status"] == "OK"
    searched = [u for u, _ in fake.requests if u.startswith("https://www.hepdata.net/search/")]
    assert "format=json" in searched[0] and "dilepton" in searched[0]


def test_keyword_search_only_satisfies_the_index_without_expanding(web, monkeypatch, tmp_path):
    _offline_rungs(monkeypatch)
    web({"https://www.hepdata.net/search/": SEARCH, "https://inspirehep.net/api/literature?": LIT})
    rc = resource_census.main(["--keyword", "dilepton resonance", "--search-only",
                               "--rundir", str(tmp_path)])
    assert rc == 0
    index = json.loads((tmp_path / "inputs" / "resource_census.json").read_text())
    assert index["entries"] == [] and index["rungs_ok"]


def test_keyword_mode_with_every_search_down_is_an_environment_finding(web, monkeypatch, tmp_path):
    _offline_rungs(monkeypatch)
    web({"https://www.hepdata.net/search/": 503, "https://inspirehep.net/api/literature?": 503})
    assert resource_census.main(["--keyword", "anything", "--rundir", str(tmp_path)]) == 3
    assert not (tmp_path / "inputs" / "resource_census.json").exists()
