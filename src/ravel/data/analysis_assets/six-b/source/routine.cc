// -*- C++ -*-
#include "Rivet/Analysis.hh"
#include "Rivet/Math/LorentzTrans.hh"
#include "Rivet/Projections/DirectFinalState.hh"
#include "Rivet/Projections/FastJets.hh"
#include "Rivet/Projections/FinalState.hh"
#include "Rivet/Projections/LeptonFinder.hh"
#include "Rivet/Projections/MissingMomentum.hh"
#include "Rivet/Projections/SmearedJets.hh"
#include "Rivet/Projections/SmearedParticles.hh"
#include "Rivet/Projections/Sphericity.hh"
#include "Rivet/Tools/Cutflow.hh"
#include "Rivet/Tools/ExptSmearingFunctions.hh"
#include "Rivet/Tools/RivetONNXrt.hh"

#include <algorithm>

namespace Rivet {


  /// @brief ATLAS search for triple higgs boson production in the 6$b$ final state
  class ATLAS_2024_I2845789 : public Analysis {
  public:

    /// Constructor
    RIVET_DEFAULT_ANALYSIS_CTOR(ATLAS_2024_I2845789);


    /// @name Analysis methods
    /// @{

    /// Book histograms and initialise projections before the run
    void init() {

      // Initialise and register projections

      // The basic final-state projection:
      // all final-state particles within
      // the given eta acceptance
      const FinalState fs(Cuts::abseta < 4.9);

      // leptons
      // n.b. cut too low to account for smearing
      const DirectFinalState bare_leptons((Cuts::abspid == PID::ELECTRON || Cuts::abspid == PID::MUON));
      declare(bare_leptons, "bare_leps");
      const DirectFinalState photons(Cuts::abspid == PID::PHOTON);
      LeptonFinder dressed_leps(bare_leptons, photons, 0.1, Cuts::abseta < 2.6 && Cuts::pt > 15 * GeV);
      SmearedParticles recomuons(dressed_leps,
                                 Cuts::abspid == PID::MUON && Cuts::pt > 20 * GeV && Cuts::abseta < 2.5,
                                 MUON_EFF_ATLAS_RUN2_MEDIUM, MUON_SMEAR_ATLAS_RUN2);
      declare(recomuons, "SmearedMuon");

      // Small-R jets
      const FinalState fsj(Cuts::abseta < 4.8);
      FastJets Sj(fsj, JetAlg::ANTIKT, 0.4, JetMuons::DECAY);
      // B-tagging perfect here, so we can get consistent 60,70 and 77 WPs
      // in the main body of the analysis
      SmearedJets SSj(Sj, JET_SMEAR_ATLAS_RUN2, JET_BTAG_PERFECT);
      declare(SSj, "smearedSjet");

      // Load neural nets
      _nnRes = {getONNX(name(), "res.odd"), getONNX(name(), "res.even")};
      _nnNonRes = {getONNX(name(), "nonres.odd"), getONNX(name(), "nonres.even")};
      _nnHeavyRes = {getONNX(name(), "heavyres.odd"), getONNX(name(), "heavyres.even")};
      // And the norms...
      _nnResNorms = {_nnRes.first->retrieve<float>("scale"), _nnRes.second->retrieve<float>("scale")};
      _nnNonResNorms = {_nnNonRes.first->retrieve<float>("scale"),
                        _nnNonRes.second->retrieve<float>("scale")};
      _nnHeavyResNorms = {_nnHeavyRes.first->retrieve<float>("scale"),
                          _nnHeavyRes.second->retrieve<float>("scale")};
      // And the offsets...
      _nnResOffsets = {_nnRes.first->retrieve<float>("offset"), _nnRes.second->retrieve<float>("offset")};
      _nnNonResOffsets = {_nnNonRes.first->retrieve<float>("offset"),
                          _nnNonRes.second->retrieve<float>("offset")};
      _nnHeavyResOffsets = {_nnHeavyRes.first->retrieve<float>("offset"),
                            _nnHeavyRes.second->retrieve<float>("offset")};


      // BOOKING
      for (const string s : {"4b", "5b", "6b"}) {

        // NN input validation plots
        // Matching Aux Figures 3-13: not on HepData, but fantastic that this
        // information has been released for the first time!
        book(_h["inputval_mH_radius_" + s], "_inputval_mH_radius_" + s, 20, 0, 200);
        book(_h["inputval_mH1_" + s], "_inputval_mH1_" + s, 20, 0, 400);
        book(_h["inputval_RMS_mjj_" + s], "_inputval_RMS_mjj_" + s, 20, 0, 400);
        book(_h["inputval_RMS_DeltaRjj_" + s], "_inputval_RMS_DeltaRjj_" + s, 17, 0.3, 2.0);
        book(_h["inputval_RMS_eta_" + s], "_inputval_RMS_eta_" + s, 20, 0., 2.);
        book(_h["inputval_Skewness_DeltaAjj_" + s], "_inputval_Skewness_DeltaAjj_" + s, 15, -1.2, 3.3);
        book(_h["inputval_HT_6j_" + s], "_inputval_HT_6j_" + s, 24, 200, 1400);
        book(_h["inputval_cosTheta_" + s], "_inputval_cosTheta_" + s, 20, -1., 1.);
        book(_h["inputval_Aplanarity_6j_" + s], "_inputval_Aplanarity_6j_" + s, 20, 0., 0.4);
        book(_h["inputval_Sphericity_6j_" + s], "_inputval_Sphericity_6j_" + s, 20, 0., 1.);
        book(_h["inputval_TransverseSphericity_6j_" + s], "_inputval_TransverseSphericity_6j_" + s, 20, 0.,
             1.);
        book(_h["inputval_Sphericity_allj_" + s], "_inputval_Sphericity_allj_" + s, 20, 0., 1.);
        book(_h["inputval_eta_mHHH_" + s], "_inputval_eta_mHHH_" + s, 20., 0., 1.);
        book(_h["inputval_DeltaRH1_" + s], "_inputval_DeltaRH1_" + s, 22, 0., 4.4);
        book(_h["inputval_DeltaRH2_" + s], "_inputval_DeltaRH2_" + s, 22, 0., 4.4);
        book(_h["inputval_DeltaRH3_" + s], "_inputval_DeltaRH3_" + s, 22, 0., 4.4);
      }

      // NN output plots
      // Seperate copies: some are normed, some are not, use slightly diff. binning.
      // Normed for comparison to aux figure plots (validation),
      // unnormed for use in likelihoods (HS3 json) and for comp. to HepData

      for (const string s : {"6b", "5b", "4b"}) {
        book(_h["resNN_" + s], "_resNN_" + s, 20, 0., 1.);
        book(_h["nonResNN_" + s], "_nonResNN_" + s, 20, 0., 1.);
        book(_h["heavyResNN_" + s], "_heavyResNN_" + s, 20, 0., 1.);

        // N.b. HepData Histos are provided as BinnedEstimate<s>, with lower bin edge
        // converted to string?! This is a pain to workaround!
        if (s == "6b") {
          book(_s["Final_resNN_" + s], 6, 1, 1);
          book(_s["Final_nonResNN_" + s], 5, 1, 1);
          book(_s["Final_heavyResNN_" + s], 7, 1, 1);
        }
        else {
          book(_s["Final_resNN_" + s], "_Final_resNN_" + s, getEdges(_s["Final_resNN_6b"]));
          book(_s["Final_nonResNN_" + s], "_Final_nonResNN_" + s, getEdges(_s["Final_nonResNN_6b"]));
          book(_s["Final_heavyResNN_" + s], "_Final_heavyResNN_" + s, getEdges(_s["Final_heavyResNN_6b"]));
        }
      }

      // The (simple) cutflow provided:
      // Given how we handle trigger efficiencies, this will not really match properly until the end.
      book(_cutflows, {"_cf4b", "_cf5b", "_cf6b"},
           {vector<string>{"Trigger", ">=6 jets", "4 jets pt>40", ">=4 b-jets", "==4 bjets"},
            vector<string>{"Trigger", ">=6 jets", "4 jets pt>40", ">=4 b-jets", "==5 bjets"},
            vector<string>{"Trigger", ">=6 jets", "4 jets pt>40", ">=4 b-jets", "==6 bjets"}});
    }


    /// Perform the per-event analysis
    void analyze(const Event& event) {

      _cutflows->groupfillinit();

      // Get (smallR) jets
      Jets smallJets = apply<JetFinder>(event, "smearedSjet")
                           .jetsByPt(Cuts::pt > 20 * GeV && Cuts::abseta < 2.5);
      // Let's have a go at applying a JVT like-cut.
      // TODO: NNJVT instead, have not been able to find an equivalent plot.
      idiscard(smallJets, [](const Jet& j) { return rand01() > ATLAS_JVT_EFF_MEDIUM(j); });

      // Get the Leptons.
      Particles smeared_muons = apply<ParticleFinder>(event, "SmearedMuon").particlesByPt();

      // Overlap removal (not really, more like overlap addition):
      // This is effectively handled automatically by using JetMuons::Decay

      // bjets
      Jets bjets;
      Jets nonbjets;
      Jets bjets60;
      Jets bjets70;
      Jets jets35;
      for (const Jet& j : smallJets) {
        const double r = rand01();
        // For use in main analysis
        if (r < JET_BTAG_ATLAS_RUN2_DL1d_77(j))
          bjets.push_back(j);
        else
          nonbjets.push_back(j);
        // For use in triggers only
        if (j.pt() >= 35 * GeV) jets35.push_back(j);
        if (r < (0.6 / 0.77) * JET_BTAG_ATLAS_RUN2_2016_MV2C10_77(j) && j.pt() >= 35 * GeV)
          bjets60.push_back(j);
        if (r < (0.7 / 0.77) * JET_BTAG_ATLAS_RUN2_2016_MV2C10_77(j) && j.pt() >= 35 * GeV)
          bjets70.push_back(j);
      }
      isortByPt(bjets);
      const size_t njets35 = jets35.size();
      const size_t nbjets60 = bjets60.size();
      const size_t nbjets70 = bjets70.size();

      // Trigger requirements
      // TODO there are correction factors mentioned, would be nice to see these...
      // Trigger 90-98% efficient depending on year.
      // 4 jets at L1
      if (smallJets.size() < 4) vetoEvent;
      // 2b2j (2016 + 2018)
      const bool trigger2016and2018 = njets35 >= 4 && nbjets60 >= 2;
      // 3b1j (2017)
      const bool trigger2017 = njets35 >= 4 && nbjets70 >= 3;
      if (!trigger2016and2018 && !trigger2017) vetoEvent;
      const double triggerfrac = get_frac_from_triggers(trigger2016and2018, trigger2017);
      _cutflows->groupfillnext("Trigger", triggerfrac);

      // Simple Pre-selection
      // >= 6 jets
      if (smallJets.size() < 6) vetoEvent;
      _cutflows->groupfillnext(">= 6 jets", triggerfrac);

      // Lead 4 jets have pt > 40
      if (smallJets[3].pT() <= 40 * GeV) vetoEvent;
      _cutflows->groupfillnext("4 jets pt>40", triggerfrac);

      // At least four b-jets
      if (bjets.size() < 4) vetoEvent;
      _cutflows->groupfillnext(">=4 b-jets", triggerfrac);

      // Are we in 4b, 5b, or 6b mode?
      const int bjetMultiplicity = (bjets.size() > 6) ? 6 : bjets.size();
      const string bjetMultiplicityString = std::to_string((bjets.size() > 6) ? 6 : bjets.size());
      _cutflows->fillnext("_cf" + bjetMultiplicityString + "b", triggerfrac);

      // Higgs boson reconstruction (slightly tricky)
      Jets pairingCandidates;
      pairingCandidates.reserve(6);
      if (bjetMultiplicity == 6) {
        pairingCandidates.assign(bjets.begin(), bjets.begin() + 6);
      }
      else if (bjetMultiplicity == 5) {
        pairingCandidates.assign(bjets.begin(), bjets.begin() + 5);
        pairingCandidates.push_back(nonbjets[0]);
      }
      else {
        pairingCandidates.assign(bjets.begin(), bjets.begin() + 4);
        pairingCandidates.push_back(nonbjets[0]);
        pairingCandidates.push_back(nonbjets[1]);
      }

      const vector<pair<Jet, Jet>> pairedJets = getJetPairs(pairingCandidates);
      const P4 H1 = pairedJets[0].first.mom() + pairedJets[0].second.mom();
      const P4 H2 = pairedJets[1].first.mom() + pairedJets[1].second.mom();
      const P4 H3 = pairedJets[2].first.mom() + pairedJets[2].second.mom();

      // Variables useful later, not nn inputs:
      const float m_HHH = (H1 + H2 + H3).mass();

      // Get all NN variables.
      const float mH_radius = sqrt((120 * GeV - H1.mass()) * (120 * GeV - H1.mass())
                                   + (115 * GeV - H2.mass()) * (115 * GeV - H2.mass())
                                   + (110 * GeV - H3.mass()) * (110 * GeV - H3.mass()));
      const float mH1 = H1.mass();
      // const float RMS_mjj = get_RMS_mjj(pairingCandidates);
      // const float RMS_DeltaRjj = get_RMS_deltaRjj(pairingCandidates);
      // For this analysis, RMS=std dev (thanks to analysis team for pointing out)
      const float RMS_mjj = get_sigma_mjj(pairingCandidates);
      const float RMS_DeltaRjj = get_sigma_deltaRjj(pairingCandidates);
      // Thanks to analsysi team for re-checking the original analysis and noting that this
      // is actually the std. dev. of the six higgs candidate jets, not the higgs candidates themselves.
      const float mean_eta = std::accumulate(pairingCandidates.begin(), pairingCandidates.end(), 0.f,
                                             [](float tot, const Jet& j) { return tot + j.eta(); })
          / 6.;
      const float mean_square_eta = std::accumulate(pairingCandidates.begin(), pairingCandidates.end(), 0.f,
                                                    [](float tot, const Jet& j) {
                                                      return tot + (j.eta() * j.eta());
                                                    })
          / 6.;
      const float RMS_eta = sqrt(mean_square_eta - mean_eta * mean_eta);

      // This is the third input that loops over all 15 jet pairs... might be a more efficient way?
      const float Skewness_DeltaAjj = get_Skewness_DeltaAjj(pairingCandidates);
      const float HT_6j = pairingCandidates[0].pT() + pairingCandidates[1].pT() + pairingCandidates[2].pT()
          + pairingCandidates[3].pT() + pairingCandidates[4].pT() + pairingCandidates[5].pT();
      // This is what's in the paper, I think it does not match what they did (see simpleAnalysis)
      // const float cosTheta = ((H1.mass()*120*GeV)+(H2.mass()*115*GeV)+(H3.mass()*110*GeV))/
      //               sqrt((H1.mass()*H1.mass()+H2.mass()*H2.mass()+H3.mass()*H3.mass())
      //                 *(120*GeV*120*GeV+115*GeV*115*GeV+110*GeV*110*GeV));
      // This is copied from SimpleAnalysis, matches internal validation distributions better
      // Effectively the angle between the displacement of the Higgs mass system from
      // ideal and a unit vector x=y=z vector.
      // Still not fantastic validation but expect very sensitive to jet reco.
      const float cosTheta = ((H1.mass() - 120) * (1 / sqrt(3)) + (H2.mass() - 115) * (1 / sqrt(3))
                              + (H3.mass() - 110) * (1 / sqrt(3)))
          / mH_radius;

      // Sphericities
      Sphericity sph_6j_r2(2);
      Sphericity sph_6j_r1(1);
      Sphericity sph_allj(1);

      // Again thanks to analysis team for checking, turns out original analysis boosted
      // some of the jets before calculating some of the observables (not in paper or SA)
      const P4 hhh_p4 = sumP4(static_cast<const Jets>(pairingCandidates));
      const P3 hhh_boostvec = {hhh_p4.x() / hhh_p4.t(), hhh_p4.y() / hhh_p4.t(), hhh_p4.z() / hhh_p4.t()};

      LorentzTransform hhh_booster = LorentzTransform::mkFrameTransformFromBeta(hhh_boostvec);
      Jets boostedPairingCandidates;
      for (const Jet& j : pairingCandidates) {
        boostedPairingCandidates.push_back(hhh_booster.transform(j));
      }

      sph_6j_r2.calc(boostedPairingCandidates);
      sph_6j_r1.calc(boostedPairingCandidates);
      sph_allj.calc(smallJets);

      const float Aplanarity_6j = sph_6j_r1.aplanarity();
      const float Sphericity_6j = sph_6j_r1.sphericity();
      const float TransverseSphericity_6j = sph_6j_r2.transSphericity();
      const float Sphericity_allj = sph_allj.sphericity();
      const float eta_mHHH = get_eta(pairingCandidates) / (m_HHH * m_HHH);
      const float DeltaRH1 = deltaR(pairedJets[0].first, pairedJets[0].second);
      const float DeltaRH2 = deltaR(pairedJets[1].first, pairedJets[1].second);
      const float DeltaRH3 = deltaR(pairedJets[2].first, pairedJets[2].second);

      // For validation, let's make nn input plots
      _h["inputval_mH_radius_" + bjetMultiplicityString + "b"]->fill(mH_radius, triggerfrac);
      _h["inputval_mH1_" + bjetMultiplicityString + "b"]->fill(mH1, triggerfrac);
      _h["inputval_RMS_mjj_" + bjetMultiplicityString + "b"]->fill(RMS_mjj, triggerfrac);
      _h["inputval_RMS_DeltaRjj_" + bjetMultiplicityString + "b"]->fill(RMS_DeltaRjj, triggerfrac);
      _h["inputval_RMS_eta_" + bjetMultiplicityString + "b"]->fill(RMS_eta, triggerfrac);
      _h["inputval_Skewness_DeltaAjj_" + bjetMultiplicityString + "b"]->fill(Skewness_DeltaAjj, triggerfrac);
      _h["inputval_HT_6j_" + bjetMultiplicityString + "b"]->fill(HT_6j, triggerfrac);
      _h["inputval_cosTheta_" + bjetMultiplicityString + "b"]->fill(cosTheta, triggerfrac);
      _h["inputval_Aplanarity_6j_" + bjetMultiplicityString + "b"]->fill(Aplanarity_6j, triggerfrac);
      _h["inputval_Sphericity_6j_" + bjetMultiplicityString + "b"]->fill(Sphericity_6j, triggerfrac);
      _h["inputval_TransverseSphericity_6j_" + bjetMultiplicityString + "b"]->fill(TransverseSphericity_6j,
                                                                                   triggerfrac);
      _h["inputval_Sphericity_allj_" + bjetMultiplicityString + "b"]->fill(Sphericity_allj, triggerfrac);
      _h["inputval_eta_mHHH_" + bjetMultiplicityString + "b"]->fill(eta_mHHH, triggerfrac);
      _h["inputval_DeltaRH1_" + bjetMultiplicityString + "b"]->fill(DeltaRH1, triggerfrac);
      _h["inputval_DeltaRH2_" + bjetMultiplicityString + "b"]->fill(DeltaRH2, triggerfrac);
      _h["inputval_DeltaRH3_" + bjetMultiplicityString + "b"]->fill(DeltaRH3, triggerfrac);

      // Fill NN inputs
      vector<float> _resInputs = {HT_6j,         RMS_DeltaRjj, DeltaRH2, eta_mHHH,          Sphericity_6j,
                                  Aplanarity_6j, DeltaRH1,     DeltaRH3, Skewness_DeltaAjj, cosTheta};
      vector<float> _nonResInputs = {
          mH_radius, RMS_mjj,  RMS_DeltaRjj, DeltaRH1,      RMS_eta,
          mH1,       DeltaRH2, DeltaRH3,     Aplanarity_6j, TransverseSphericity_6j};
      vector<float> _heavyResInputs = {mH_radius, RMS_DeltaRjj, RMS_mjj, DeltaRH1,      DeltaRH2,
                                       DeltaRH3,  mH1,          RMS_eta, Aplanarity_6j, Sphericity_allj};

      vector<float> resScore, nonResScore, heavyResScore;
      // TODO is this cleanest way to alternate events? Is there anything safer?
      if (event.hepmcEvent().event_number() % 2 == 1) {
        resScore = _nnRes.first->compute(normaliseInputs(_resInputs, _nnResOffsets.first, _nnResNorms.first));
        nonResScore = _nnNonRes.first->compute(
            normaliseInputs(_nonResInputs, _nnNonResOffsets.first, _nnNonResNorms.first));
        heavyResScore = _nnHeavyRes.first->compute(
            normaliseInputs(_heavyResInputs, _nnHeavyResOffsets.first, _nnHeavyResNorms.first));
      }
      else {
        resScore = _nnRes.second->compute(
            normaliseInputs(_resInputs, _nnResOffsets.second, _nnResNorms.second));
        nonResScore = _nnNonRes.second->compute(
            normaliseInputs(_nonResInputs, _nnNonResOffsets.second, _nnNonResNorms.second));
        heavyResScore = _nnHeavyRes.second->compute(
            normaliseInputs(_heavyResInputs, _nnHeavyResOffsets.second, _nnHeavyResNorms.second));
      }
      // Let's record the outputs
      _h["resNN_" + bjetMultiplicityString + "b"]->fill(resScore[0], triggerfrac);
      _h["nonResNN_" + bjetMultiplicityString + "b"]->fill(nonResScore[0], triggerfrac);
      _h["heavyResNN_" + bjetMultiplicityString + "b"]->fill(heavyResScore[0], triggerfrac);

      _s["Final_resNN_" + bjetMultiplicityString + "b"]->fill(resNNlowerbin(resScore[0]), triggerfrac);
      _s["Final_nonResNN_" + bjetMultiplicityString + "b"]->fill(nonresNNlowerbin(nonResScore[0]),
                                                                 triggerfrac);
      _s["Final_heavyResNN_" + bjetMultiplicityString + "b"]->fill(heavyresNNlowerbin(heavyResScore[0]),
                                                                   triggerfrac);
    }


    /// Normalise histograms etc., after the run
    void finalize() {
      // n.b. only used 126 invfb!
      const double sf = 126 * crossSection() / femtobarn / sumW();

      // NN input validation plots all normalised to one:
      for (const pair<const string, Histo1DPtr>& p : _h) {
        // TODO: once we migrate to C++20, replace this rfind rubbish with
        // the new starts_with function.
        if ((p.first.rfind("inputval_", 0) == 0) || (p.first.rfind("resNN") == 0)
            || (p.first.rfind("nonResNN") == 0) || (p.first.rfind("heavyResNN") == 0)) {
          if (_h[p.first]->sumW() > 0) {
            MSG_DEBUG("normalising " << p.first);
            _h[p.first]->normalize();
          }
          else
            MSG_DEBUG("Not normalising " << p.first << " (empty)");
        }
      }

      // Scale final distributions to XS.
      _cutflows->scaleW(sf);
      for (const string nbs : {"4b", "5b", "6b"}) {
        _s["Final_resNN_" + nbs]->scaleW(sf);
        _s["Final_nonResNN_" + nbs]->scaleW(sf);
        _s["Final_heavyResNN_" + nbs]->scaleW(sf);
      }
    }

    /// @}


    /// @name Histograms
    /// @{
    map<string, Histo1DPtr> _h;
    map<string, BinnedHistoPtr<string>> _s;
    CutflowsPtr _cutflows;
    /// @}

    /// @name analysis utility functions
    /// @{
    // Pair 6 b-jets to get three higgs boson candidates
    vector<pair<Jet, Jet>> getJetPairs(const Jets& inJets) {
      vector<size_t> i = {0, 1, 2, 3, 4, 5};
      vector<size_t> bestpermute;
      double lowestminval = DBL_MAX;

      do {
        const P4 H1 = inJets[i[0]].mom() + inJets[i[1]].mom();
        const P4 H2 = inJets[i[2]].mom() + inJets[i[3]].mom();
        const P4 H3 = inJets[i[4]].mom() + inJets[i[5]].mom();

        if (!((H1.pT() > H2.pT()) && (H2.pT() > H3.pT()))) continue;

        const double minval = fabs(H1.mass() - 120 * GeV) + fabs(H2.mass() - 115 * GeV)
            + fabs(H3.mass() - 110 * GeV);
        if (minval < lowestminval) {
          lowestminval = minval;
          bestpermute = i;
        }
      } while (std::next_permutation(i.begin(), i.end()));

      return {{inJets[bestpermute[0]], inJets[bestpermute[1]]},
              {inJets[bestpermute[2]], inJets[bestpermute[3]]},
              {inJets[bestpermute[4]], inJets[bestpermute[5]]}};
    }

    // Calc RMS of the mass of all possible H candidates.
    float get_RMS_mjj(const Jets& inJets) {
      // 6 jets in inJets is assumed, someone elses fault if not.
      // Yes 5 is correct limit
      float tot = 0;
      for (size_t i = 0; i < 5; ++i) {
        for (size_t j = i + 1; j < 6; ++j) {
          const float mass = (float)((inJets[i].mom() + inJets[j].mom()).mass());
          tot += mass * mass;
        }
      }
      return (float)sqrt(tot / 15.f);
    }

    // Calc std dev of mass of all possible Higgs candidates.
    float get_sigma_mjj(const Jets& inJets) {
      // 6 jets in inJets is assumed, someone elses fault if not.
      // Yes 5 is correct limit
      float tot = 0;
      float tot2 = 0;
      for (size_t i = 0; i < 5; ++i) {
        for (size_t j = i + 1; j < 6; ++j) {
          const float mass = (float)((inJets[i].mom() + inJets[j].mom()).mass());
          tot += mass;
          tot2 += mass * mass;
        }
      }
      return (float)sqrt(tot2 / 15.f - tot * tot / 225.f);
    }

    // Calc the RMS of the dR between b-jets within each H-candidate
    // across all possible Higgs candidates
    float get_RMS_deltaRjj(const Jets& inJets) {
      // 6 jets in inJets is assumed, someone elses fault if not
      // Yes 5 is correct limit
      float tot = 0;
      for (size_t i = 0; i < 5; ++i) {
        for (size_t j = i + 1; j < 6; ++j) {
          const double dR = deltaR(inJets[i], inJets[j]);
          tot += dR * dR;
        }
      }
      return (float)sqrt(tot / 15.f);
    }

    // Calc the std dev of the dR between b-jets within each H-candidate
    // across all possible Higgs candidates
    float get_sigma_deltaRjj(const Jets& inJets) {
      // 6 jets in inJets is assumed, someone elses fault if not
      // Yes 5 is correct limit
      float tot = 0;
      float tot2 = 0;
      for (size_t i = 0; i < 5; ++i) {
        for (size_t j = i + 1; j < 6; ++j) {
          const double dR = deltaR(inJets[i], inJets[j]);
          tot += dR;
          tot2 += dR * dR;
        }
      }
      return (float)sqrt(tot2 / 15.f - tot * tot / 225.f);
    }

    // Calculate Skewness Delta A_jj variable
    // See paper/simpleanalysis for variable description.
    float get_Skewness_DeltaAjj(const Jets& inJets) {
      // 6 jets in inJets is assumed, someone elses fault if not
      // Yes 5 is correct limit
      float tot = 0;
      float tot2 = 0;
      float tot3 = 0;
      for (size_t i = 0; i < 5; ++i) {
        for (size_t j = i + 1; j < 6; ++j) {
          const double dEta = deltaEta(inJets[i], inJets[j]);
          const double dPhi = deltaPhi(inJets[i], inJets[j]);
          const double Ajj = cosh(dEta) - cos(dPhi);
          tot += Ajj;
          tot2 += Ajj * Ajj;
          tot3 += Ajj * Ajj * Ajj;
        }
      }
      tot = tot / 15;
      tot2 = tot2 / 15;
      tot3 = tot3 / 15;
      const float sigma = sqrt(tot2 - tot * tot);
      const float skewness = (tot3 - 3 * tot * tot2 + 2 * tot * tot * tot) / (sigma * sigma * sigma);
      return skewness;
    }

    // Calculate the eta variable (see paper for definition)
    float get_eta(const Jets& inJets) {
      float tot = 0;
      for (size_t i = 0; i < 5; ++i) {
        for (size_t j = i + 1; j < 6; ++j) {
          const double dEta = deltaEta(inJets[i], inJets[j]);
          tot += 2 * inJets[i].pT() * inJets[j].pT() * (cosh(dEta) - 1);
        }
      }
      return tot;
    }

    inline float get_frac_from_triggers(const bool pass2016and2018, const bool pass2017) {
      return (pass2016and2018 * 81.7 + pass2017 * 44.3) / 126.;
    }
    /// @}

    /// @name Functions to deal with hepdata string histos
    /// @{
    string resNNlowerbin(const double nnscore) {
      if (nnscore < 0.05 || nnscore > 1) {
        return "overflow";
      }
      // n.b. Extra epsilon 1e-6 on final bin to avoid crash on exceedingly rare NNscore==1
      const vector<double> edges = {0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5,
                                    0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0 + 1e-6};
      const vector<string> bottomEdges = {"0.05", "0.1",  "0.15", "0.2",  "0.25", "0.3",  "0.35",
                                          "0.4",  "0.45", "0.5",  "0.55", "0.6",  "0.65", "0.7",
                                          "0.75", "0.8",  "0.85", "0.9",  "0.95"};
      return bottomEdges[binIndex(nnscore, edges)];
    }

    string nonresNNlowerbin(const double nnscore) {
      if (nnscore < 0.1 || nnscore > 1) {
        return "overflow";
      }
      // n.b. Extra epsilon 1e-6 on final bin to avoid crash on exceedingly rare NNscore==1
      const vector<double> edges = {0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5,   0.55,
                                    0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.975, 1.0 + 1e-6};
      const vector<string> bottomEdges = {"0.1",  "0.15", "0.2",  "0.25", "0.3",  "0.35", "0.4",
                                          "0.45", "0.5",  "0.55", "0.6",  "0.65", "0.7",  "0.75",
                                          "0.8",  "0.85", "0.9",  "0.95", "0.975"};
      return bottomEdges[binIndex(nnscore, edges)];
    }

    string heavyresNNlowerbin(const double nnscore) {
      if (nnscore < 0.1 || nnscore > 1) {
        return "overflow";
      }
      // n.b. Extra epsilon 1e-6 on final bin to avoid crash on exceedingly rare NNscore==1
      const vector<double> edges = {0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5,       0.55,
                                    0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0 + 1e-6};
      const vector<string> bottomEdges = {"0.1", "0.15", "0.2", "0.25", "0.3", "0.35",
                                          "0.4", "0.45", "0.5", "0.55", "0.6", "0.65",
                                          "0.7", "0.75", "0.8", "0.85", "0.9", "0.95"};
      return bottomEdges[binIndex(nnscore, edges)];
    }

    // Because h.binning().template edges<0>(false) is ugly.
    template <typename histoT>
    Rivet::strings getEdges(histoT& h) {
      return h.binning().template edges<0>(false);
    }
    /// @}


    /// @name NeuralNet related stuff
    /// @{
    // Why a pair? Because of the k-fold, two actual networks needed.
    pair<unique_ptr<RivetONNXrt>, unique_ptr<RivetONNXrt>> _nnRes;
    pair<unique_ptr<RivetONNXrt>, unique_ptr<RivetONNXrt>> _nnNonRes;
    pair<unique_ptr<RivetONNXrt>, unique_ptr<RivetONNXrt>> _nnHeavyRes;

    pair<vector<float>, vector<float>> _nnResNorms;
    pair<vector<float>, vector<float>> _nnNonResNorms;
    pair<vector<float>, vector<float>> _nnHeavyResNorms;

    pair<vector<float>, vector<float>> _nnResOffsets;
    pair<vector<float>, vector<float>> _nnNonResOffsets;
    pair<vector<float>, vector<float>> _nnHeavyResOffsets;

    // Normalise network inputs
    // Note that as for other examples in rivet, we've tweaked the original onnx
    // to include the norm information as metadata.
    vector<float> normaliseInputs(const vector<float>& inputs,
                                  const vector<float>& offsets,
                                  const vector<float>& scales) {
      vector<float> outputs;
      outputs.reserve(inputs.size());

      // n.b. assume someone else has been rigorous in ensuring in/off/scales are the right len
      for (size_t i = 0; i < inputs.size(); ++i) {
        outputs.push_back((inputs[i] - offsets[i]) / scales[i]);
      }
      return outputs;
    }
    /// @}
  };

  RIVET_DECLARE_PLUGIN(ATLAS_2024_I2845789);
}
