// rjr_resolve.cc
// ---------------------------------------------------------------------------
// NATIVE (no-VM, no-ATLAS-AnalysisBase) resolver for the two RestFrames
// recursive-jigsaw variables R_ISR and M_S that ATLAS's EwkCompressed2018
// (ANA-SUSY-2018-16) SUSY analysis cuts on.
//
// It links the natively-built crogan/RestFrames v1.0.1 (arm64, against recast
// ROOT 6.40) and reconstructs the EXACT same RestFrames decay/jigsaw tree that
// ANA-SUSY-2018-16.cxx::Init() builds, then per event fills the frames with the
// event's signal jets + summed signal leptons + MET exactly as
// EwkCompressed2018::ProcessEvent() does, solves the tree, and reads
//   R_ISR = |P_I . P_ISR_hat| / |P_ISR|   (all in the CM frame)
//   M_S   = S->GetMass()
// emitting a per-event CSV: Event, nJ, nLep, RISR, MS, PTISR, MISR, dphiISRI, NjV, NjISR.
//
// Object selection mirrors the .cxx KINEMATIC cuts that survive a Delphes-level
// fast sim (no truth b-tag / JVT / isolation working points are available from
// the Delphes2SA ntuple, so those flag-based refinements are necessarily
// dropped -- see the validation report). Signal jets: pt>30, |eta|<2.8.
// Signal leptons: electrons pt>4.5 |eta|<2.47, muons pt>3 |eta|<2.5. Lepton
// masses and MET handling match SimpleAnalysis's SlimReader exactly (electrons
// 0.510998910e-3 GeV, muons 105.6583715e-3 GeV; MET already muon-subtracted in
// the Delphes2SA converter; everything in GeV; objects fed TRANSVERSE, eta=0,
// exactly as AnalysisObject::transFourVect()).
//
// Build:  see rjr_resolve_build.sh
// Run (legacy ntuple mode -- its OWN looser kinematic-only object selection):
//         ./rjr_resolve <Delphes2SA.root> <out.csv>
// Run (PRE-SELECTED objects mode -- single source of truth):
//         ./rjr_resolve --objects <objfile> <out.csv>
//   where <objfile> is written by native_simpleanalysis.py and contains, per
//   line, the EXACT signalJets + summed signal-lepton system the Python
//   selection produced (after the full 5-step overlap removal). The RestFrames
//   tree/jigsaw build and the R_ISR/M_S formulas below are IDENTICAL in both
//   modes; only the source of the per-event objects differs. The --objects mode
//   is the one the productionized pipeline uses (no looser jet selection here,
//   no reading of the container's RJR_* branches).
//
// --objects file format (whitespace-separated, one event per line):
//   Event  met_pt  met_phi  nJet  (jet_pt jet_phi jet_m)*nJet  nLep  (lep_pt lep_phi lep_m)*nLep
//   Only events that passed the Python gate (baseLeptons>=1 && signalJets>=1,
//   i.e. exactly the events where ProcessEvent calls the RJR helper) appear.
//   Jets/leptons are already TRANSVERSE quantities (the Python side passes
//   pt, phi and the object mass; eta=0 is applied here via SetPtEtaPhiM, exactly
//   reproducing AnalysisObject::transFourVect()).
// ---------------------------------------------------------------------------

#include "RestFrames/RestFrames.hh"
#include "TFile.h"
#include "TTree.h"
#include "TLorentzVector.h"
#include "TVector3.h"

#include <vector>
#include <string>
#include <iostream>
#include <fstream>
#include <sstream>
#include <cmath>
#include <limits>

using namespace RestFrames;

int main(int argc, char** argv) {
  if (argc < 3) {
    std::cerr << "usage: " << argv[0] << " <Delphes2SA.root> <out.csv>\n";
    std::cerr << "   or: " << argv[0] << " --objects <objfile> <out.csv>\n";
    return 1;
  }

  // -------------------- argument parsing / mode selection --------------------
  bool objectsMode = false;
  std::string inPath, outPath;
  if (std::string(argv[1]) == "--objects") {
    if (argc < 4) {
      std::cerr << "usage: " << argv[0] << " --objects <objfile> <out.csv>\n";
      return 1;
    }
    objectsMode = true;
    inPath  = argv[2];
    outPath = argv[3];
  } else {
    inPath  = argv[1];
    outPath = argv[2];
  }

  // ---- electron / muon masses, exactly as SimpleAnalysis SlimReader.cxx ----
  const double M_ELE = 0.510998910e-3;   // GeV
  const double M_MUO = 105.6583715e-3;   // GeV

  // -----------------------------------------------------------------------
  // Build the RestFrames tree -- a 1:1 transcription of
  // ANA-SUSY-2018-16.cxx::Init() (lines 73-119).
  //
  //   LAB -> CM -> { ISR , S } ;  S -> { V , I , L }
  //   INV group  : SetMassInvJigsaw (invisible mass = 0)
  //   VIS group  : MinMassesCombJigsaw, ISR in comb-group 0 (>=1 element),
  //                V/I/L in comb-group 1 (V allowed 0 elements)
  // The contra-boost / rapidity invisible jigsaws are auto-completed by
  // RestFrames (Init() adds only SetMass + MinMasses, exactly as here).
  // -----------------------------------------------------------------------
  LabRecoFrame        LAB("LAB","LAB");
  DecayRecoFrame      CM("CM","CM");
  DecayRecoFrame      S("S","S");
  VisibleRecoFrame    ISR("ISR","ISR");
  VisibleRecoFrame    V("V","V");
  VisibleRecoFrame    L("L","L");
  InvisibleRecoFrame  I("I","I");

  InvisibleGroup      INV("INV","INV");
  SetMassInvJigsaw    InvMass("InvMass","InvMass");          // kSetMass

  CombinatoricGroup   VIS("VIS","VIS");
  MinMassesCombJigsaw SplitVis("SplitVis","SplitVis");        // kMinMasses

  LAB.SetChildFrame(CM);
  CM.AddChildFrame(ISR);
  CM.AddChildFrame(S);
  S.AddChildFrame(V);
  S.AddChildFrame(I);
  S.AddChildFrame(L);

  if (!LAB.InitializeTree()) {
    std::cerr << "FATAL: InitializeTree failed\n"; return 2;
  }

  INV.AddFrame(I);

  VIS.AddFrame(ISR);
  VIS.SetNElementsForFrame(ISR, 1, false);
  VIS.AddFrame(V);
  VIS.SetNElementsForFrame(V, 0, false);

  INV.AddJigsaw(InvMass);

  VIS.AddJigsaw(SplitVis);
  SplitVis.AddFrame(ISR, 0);   // "0" group (ISR)
  SplitVis.AddFrame(V, 1);     // "1" group (V + I + L)
  SplitVis.AddFrame(I, 1);
  SplitVis.AddFrame(L, 1);

  if (!LAB.InitializeAnalysis()) {
    std::cerr << "FATAL: InitializeAnalysis failed\n"; return 2;
  }

  // -----------------------------------------------------------------------
  // Shared per-event solver. Given the event's signal jets (already TRANSVERSE:
  // pt, phi, m), the summed signal-lepton transverse 4-vector, and the MET
  // (pt, phi), fill the RestFrames tree exactly as ProcessEvent (lines 229-243)
  // and read R_ISR / M_S. This is the SINGLE place the RestFrames formulas live
  // and is byte-for-byte identical between the legacy ntuple mode and the new
  // --objects mode -- only the source of sigJets/lepSys/met differs.
  // -----------------------------------------------------------------------
  auto solveEvent = [&](const std::vector<TLorentzVector>& sigJets,
                        const TLorentzVector& lepSys,
                        double mPt, double mPhi,
                        double& RISR, double& MS, double& PTISR, double& MISR,
                        double& dphi, int& NjV, int& NjISR) -> bool {
    LAB.ClearEvent();

    std::vector<RFKey> jetID;
    jetID.reserve(sigJets.size());
    for (const auto& jet : sigJets) {
      // transFourVect(): pt, eta=0, phi, m
      TLorentzVector tj; tj.SetPtEtaPhiM(jet.Pt(), 0.0, jet.Phi(), jet.M());
      jetID.push_back(VIS.AddLabFrameFourVector(tj));
    }

    L.SetLabFrameFourVector(lepSys);

    TVector3 metV; metV.SetPtEtaPhi(mPt, 0.0, mPhi); // MET 3-vector, GeV, muon-subtracted
    INV.SetLabFrameThreeVector(metV);

    bool ok = LAB.AnalyzeEvent();

    NjV = 0; NjISR = 0;
    RISR = -9; MS = -9; PTISR = -9; MISR = -9; dphi = -9;
    if (ok) {
      for (size_t i = 0; i < sigJets.size(); ++i) {
        if (VIS.GetFrame(jetID[i]) == V) ++NjV; else ++NjISR;
      }
      TVector3 v_P_ISR = ISR.GetFourVector(CM).Vect();
      TVector3 v_P_I   = I.GetFourVector(CM).Vect();
      PTISR = v_P_ISR.Mag();
      RISR  = std::fabs(v_P_I.Dot(v_P_ISR.Unit())) / PTISR;
      MS    = S.GetMass();
      MISR  = ISR.GetMass();
      dphi  = std::fabs(v_P_ISR.DeltaPhi(v_P_I));
    }
    return ok;
  };

  // =======================================================================
  // MODE 2 (productionized): read PRE-SELECTED objects written by
  // native_simpleanalysis.py (the single source of truth for object selection).
  // =======================================================================
  if (objectsMode) {
    std::ifstream objf(inPath);
    if (!objf) { std::cerr << "cannot open objects file " << inPath << "\n"; return 3; }

    std::ofstream out(outPath);
    out << "Event,nJ,nLep,RISR,MS,PTISR,MISR,dphiISRI,NjV,NjISR,solved\n";
    // Round-trip doubles: fixed decimal rounding can turn RISR<1 into 1.
    out.precision(std::numeric_limits<double>::max_digits10);

    Long64_t N = 0, nSolved = 0;
    std::string line;
    while (std::getline(objf, line)) {
      if (line.empty() || line[0] == '#') continue;
      std::istringstream ss(line);
      long evt; double mPt, mPhi; int nJet;
      if (!(ss >> evt >> mPt >> mPhi >> nJet)) continue;

      std::vector<TLorentzVector> sigJets;
      sigJets.reserve(nJet);
      for (int j = 0; j < nJet; ++j) {
        double pt, phi, m; ss >> pt >> phi >> m;
        TLorentzVector v4; v4.SetPtEtaPhiM(pt, 0.0, phi, m);
        sigJets.push_back(v4);
      }
      int nLep; ss >> nLep;
      TLorentzVector lepSys(0,0,0,0);
      for (int l = 0; l < nLep; ++l) {
        double pt, phi, m; ss >> pt >> phi >> m;
        TLorentzVector v4; v4.SetPtEtaPhiM(pt, 0.0, phi, m); // transFourVect per lepton, then sum
        lepSys += v4;
      }

      double RISR, MS, PTISR, MISR, dphi; int NjV, NjISR;
      bool ok = solveEvent(sigJets, lepSys, mPt, mPhi,
                           RISR, MS, PTISR, MISR, dphi, NjV, NjISR);
      if (ok) ++nSolved;
      ++N;

      out << evt << "," << (int)sigJets.size() << "," << nLep << ","
          << RISR << "," << MS << "," << PTISR << "," << MISR << ","
          << dphi << "," << NjV << "," << NjISR << "," << (ok ? 1 : 0) << "\n";
    }
    out.close();
    std::cerr << "rjr_resolve(--objects): " << N << " events, " << nSolved << " solved\n";
    return 0;
  }

  // =======================================================================
  // MODE 1 (legacy): read the Delphes2SA ntuple and apply rjr_resolve's OWN
  // looser kinematic-only object selection (kept for back-compat / debugging;
  // NOT used by the productionized pipeline).
  // =======================================================================

  // -----------------------------------------------------------------------
  // Open the Delphes2SA ntuple.
  // -----------------------------------------------------------------------
  TFile* fin = TFile::Open(inPath.c_str(), "READ");
  if (!fin || fin->IsZombie()) { std::cerr << "cannot open " << inPath << "\n"; return 3; }
  TTree* t = dynamic_cast<TTree*>(fin->Get("ntuple"));
  if (!t) { std::cerr << "no tree 'ntuple' in " << inPath << "\n"; return 3; }

  Int_t Event = 0;
  Float_t met_pt = 0.f, met_phi = 0.f;
  std::vector<float> *el_pt=nullptr, *el_eta=nullptr, *el_phi=nullptr;
  std::vector<float> *mu_pt=nullptr, *mu_eta=nullptr, *mu_phi=nullptr;
  std::vector<float> *jet_pt=nullptr, *jet_eta=nullptr, *jet_phi=nullptr, *jet_m=nullptr;

  t->SetBranchAddress("Event",   &Event);
  t->SetBranchAddress("met_pt",  &met_pt);
  t->SetBranchAddress("met_phi", &met_phi);
  t->SetBranchAddress("el_pt",   &el_pt);
  t->SetBranchAddress("el_eta",  &el_eta);
  t->SetBranchAddress("el_phi",  &el_phi);
  t->SetBranchAddress("mu_pt",   &mu_pt);
  t->SetBranchAddress("mu_eta",  &mu_eta);
  t->SetBranchAddress("mu_phi",  &mu_phi);
  t->SetBranchAddress("jet_pt",  &jet_pt);
  t->SetBranchAddress("jet_eta", &jet_eta);
  t->SetBranchAddress("jet_phi", &jet_phi);
  t->SetBranchAddress("jet_m",   &jet_m);

  std::ofstream out(outPath);
  out << "Event,nJ,nLep,RISR,MS,PTISR,MISR,dphiISRI,NjV,NjISR,solved\n";
  out.precision(std::numeric_limits<double>::max_digits10);

  const Long64_t N = t->GetEntries();
  Long64_t nSolved = 0, nGated = 0;

  for (Long64_t ev = 0; ev < N; ++ev) {
    t->GetEntry(ev);

    // --- signal jets: pt>30, |eta|<2.8  (the .cxx filterObjects(baseJets,30,2.8,JVT50Jet)
    //     kinematic part; JVT flag not available from Delphes2SA) ---
    std::vector<TLorentzVector> sigJets;
    for (size_t j = 0; jet_pt && j < jet_pt->size(); ++j) {
      double pt = (*jet_pt)[j];
      double eta = (*jet_eta)[j];
      if (pt > 30.0 && std::fabs(eta) < 2.8) {
        TLorentzVector v4; v4.SetPtEtaPhiM(pt, eta, (*jet_phi)[j], (*jet_m)[j]);
        sigJets.push_back(v4);
      }
    }

    // --- signal leptons: electrons pt>4.5 |eta|<2.47 ; muons pt>3 |eta|<2.5
    //     (the .cxx kinematic acceptance; ID/iso/d0/z0 working-point flags not
    //     available from Delphes2SA). Charge not needed for the RJR. ---
    int nLep = 0;
    TLorentzVector lepSys(0,0,0,0);   // sum of signal-lepton TRANSVERSE 4-vectors
    for (size_t i = 0; el_pt && i < el_pt->size(); ++i) {
      double pt = (*el_pt)[i], eta = (*el_eta)[i];
      if (pt > 4.5 && std::fabs(eta) < 2.47) {
        TLorentzVector v4; v4.SetPtEtaPhiM(pt, 0.0, (*el_phi)[i], M_ELE); // transFourVect
        lepSys += v4; ++nLep;
      }
    }
    for (size_t i = 0; mu_pt && i < mu_pt->size(); ++i) {
      double pt = (*mu_pt)[i], eta = (*mu_eta)[i];
      if (pt > 3.0 && std::fabs(eta) < 2.5) {
        TLorentzVector v4; v4.SetPtEtaPhiM(pt, 0.0, (*mu_phi)[i], M_MUO); // transFourVect
        lepSys += v4; ++nLep;
      }
    }

    int nJ = (int)sigJets.size();

    // ProcessEvent gate: needs >=1 signal jet (and >=1 lepton) for the RJR.
    // Match the .cxx guards so we only emit on events the container actually solved.
    if (nJ < 1 || nLep < 1) {
      ++nGated;
      out << Event << "," << nJ << "," << nLep
          << ",-9,-9,-9,-9,-9,-9,-9,0\n";
      continue;
    }

    // --- fill the tree exactly as ProcessEvent (lines 229-243) ---
    LAB.ClearEvent();

    std::vector<RFKey> jetID;
    jetID.reserve(sigJets.size());
    for (const auto& jet : sigJets) {
      // transFourVect(): pt, eta=0, phi, m
      TLorentzVector tj; tj.SetPtEtaPhiM(jet.Pt(), 0.0, jet.Phi(), jet.M());
      jetID.push_back(VIS.AddLabFrameFourVector(tj));
    }

    L.SetLabFrameFourVector(lepSys);

    TVector3 metV; metV.SetPtEtaPhi(met_pt, 0.0, met_phi); // MET 3-vector, GeV, muon-subtracted
    INV.SetLabFrameThreeVector(metV);

    bool ok = LAB.AnalyzeEvent();

    int NjV = 0, NjISR = 0;
    double RISR = -9, MS = -9, PTISR = -9, MISR = -9, dphi = -9;

    if (ok) {
      for (size_t i = 0; i < sigJets.size(); ++i) {
        if (VIS.GetFrame(jetID[i]) == V) ++NjV; else ++NjISR;
      }
      TVector3 v_P_ISR = ISR.GetFourVector(CM).Vect();
      TVector3 v_P_I   = I.GetFourVector(CM).Vect();
      PTISR = v_P_ISR.Mag();
      RISR  = std::fabs(v_P_I.Dot(v_P_ISR.Unit())) / PTISR;
      MS    = S.GetMass();
      MISR  = ISR.GetMass();
      dphi  = std::fabs(v_P_ISR.DeltaPhi(v_P_I));
      ++nSolved;
    }

    out << Event << "," << nJ << "," << nLep << ","
        << RISR << "," << MS << "," << PTISR << "," << MISR << ","
        << dphi << "," << NjV << "," << NjISR << "," << (ok ? 1 : 0) << "\n";
  }

  out.close();
  fin->Close();
  std::cerr << "rjr_resolve: " << N << " events, " << nSolved
            << " solved, " << nGated << " gated (nJ<1 || nLep<1)\n";
  return 0;
}
