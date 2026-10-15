// -*- C++ -*-
#include "Rivet/Analysis.hh"
#include "Rivet/AnalysisHandler.hh"
#include "Rivet/AnalysisInfo.hh"
#include "Rivet/Config/RivetCommon.hh"
#include "Rivet/Projections/CentralityProjection.hh"
#include "Rivet/Projections/GeneratedPercentileProjection.hh"
#include "Rivet/Projections/ImpactParameterProjection.hh"
#include "Rivet/Projections/UserCentEstimate.hh"
#include "Rivet/Tools/BeamConstraint.hh"
#include <regex>

namespace Rivet {


  Analysis::Analysis(const string& name)
      : _analysishandler(nullptr) {
    ProjectionApplier::_allowProjReg = false;
    _defaultname = name;
    _info = AnalysisInfo::make(name);
    assert(_info);
  }


  double Analysis::sqrtS() const {
    double sqrts = getOption<double>("ENERGY", 0.0);
    if (isZero(sqrts) || isnan(sqrts)) return handler().runSqrtS();
    MSG_DEBUG("Using beam energy from 'ENERGY' option: " << sqrts);
    return sqrts;
  }

  const ParticlePair& Analysis::beams() const {
    return handler().runBeams();
  }

  pair<double, double> Analysis::beamEnergies() const {
    return handler().runBeamEnergies();
  }

  vector<double> Analysis::allowedEnergies() const {
    // Return list of allowed energies from info file
    vector<double> energies;
    for (const auto& beams : info().energies()) {
      energies.push_back(::Rivet::sqrtS(beams));
    }
    std::sort(energies.begin(), energies.end());
    energies.erase(std::unique(energies.begin(), energies.end()), energies.end());
    return energies;
  }

  PdgIdPair Analysis::beamIDs() const {
    return handler().runBeamIDs();
  }


  const string Analysis::histoDir() const {
    /// @todo Cache in a member variable
    string _histoDir;
    if (_histoDir.empty()) {
      _histoDir = replace_all("/"s + name(), "//", "/"); //< iterates until none
    }
    return _histoDir;
  }


  const string Analysis::histoPath(const string& hname) const {
    const string path = histoDir() + "/" + hname;
    return path;
  }


  const string Analysis::histoPath(unsigned int datasetID, unsigned int xAxisID, unsigned int yAxisID) const {
    return histoDir() + "/" + mkAxisCode(datasetID, xAxisID, yAxisID);
  }


  const string Analysis::mkAxisCode(unsigned int datasetID,
                                    unsigned int xAxisID,
                                    unsigned int yAxisID) const {
    std::stringstream axisCode;
    axisCode << "d";
    if (datasetID < 10) axisCode << 0;
    axisCode << datasetID;
    axisCode << "-x";
    if (xAxisID < 10) axisCode << 0;
    axisCode << xAxisID;
    axisCode << "-y";
    if (yAxisID < 10) axisCode << 0;
    axisCode << yAxisID;
    return axisCode.str();
  }


  Log& Analysis::getLog() const {
    string logname = "Rivet.Analysis." + name();
    return Log::getLog(logname);
  }


  ///////////////////////////////////////////


  size_t Analysis::numEvents() const {
    return handler().numEvents();
  }

  double Analysis::effNumEvents() const {
    return handler().effNumEvents();
  }

  double Analysis::sumW() const {
    return handler().sumW();
  }

  double Analysis::sumW2() const {
    return handler().sumW2();
  }


  ///////////////////////////////////////////


  bool Analysis::beamsMatch(const ParticlePair& beams) const {
    return compatibleBeams(Analysis::beams(), beams);
  }

  bool Analysis::beamsMatch(PdgId beam1, PdgId beam2, double e1, double e2) const {
    return compatibleBeams(Analysis::beams(), make_pair(beam1, beam2), make_pair(e1, e2));
  }

  bool Analysis::beamsMatch(const PdgIdPair& beamids, const std::pair<double, double>& energies) const {
    return compatibleBeams(Analysis::beams(), beamids, energies);
  }

  bool Analysis::beamIDsMatch(PdgId beam1, PdgId beam2) const {
    return compatibleBeamIDs(Analysis::beams(), make_pair(beam1, beam2));
  }

  bool Analysis::beamIDsMatch(const PdgIdPair& beamids) const {
    return compatibleBeamIDs(Analysis::beams(), beamids);
  }

  bool Analysis::beamEnergiesMatch(double e1, double e2) const {
    /// @todo Need to match to beam ID ordering?
    return compatibleBeamEnergies(Analysis::beams(), make_pair(e1, e2));
  }

  bool Analysis::beamEnergiesMatch(const std::pair<double, double>& energies) const {
    /// @todo Need to match to beam ID ordering?
    return compatibleBeamEnergies(Analysis::beams(), energies);
  }

  bool Analysis::beamEnergyMatch(double sqrts) const {
    return compatibleBeamEnergy(Analysis::beams(), sqrts);
  }

  bool Analysis::beamEnergyMatch(const std::pair<double, double>& energies) const {
    return beamEnergyMatch(Rivet::sqrtS(energies));
  }


  bool Analysis::compatibleWithRun() const {
    bool beamidmatch = requiredBeamIDs().empty();
    for (const PdgIdPair& reqbeamids : requiredBeamIDs()) {
      MSG_TRACE("Beam IDs = " << beamIDs() << " vs. required " << reqbeamids << "  [10000 == ANY]");
      if (beamIDsMatch(reqbeamids)) {
        MSG_TRACE("Beam IDs MATCH!");
        beamidmatch = true;
        break;
      }
    }
    if (!beamidmatch) {
      MSG_DEBUG("Run doesn't match required beam IDs");
      return false;
    }

    bool beamenergymatch = requiredBeamEnergies().empty();
    for (const pair<double, double>& reqbeamenergies : requiredBeamEnergies()) {
      MSG_TRACE("Beam energies = " << beamEnergies() << " vs. required " << reqbeamenergies);
      /// @todo Can't currently guarantee that the energies are matched to the correct beams... use sqrt(s) for now
      if (beamEnergiesMatch(reqbeamenergies)) {
        // if (beamEnergyMatch(reqbeamenergies)) {
        MSG_TRACE("Beam energies MATCH!");
        beamenergymatch = true;
        break;
      }
    }
    if (!beamenergymatch) {
      MSG_DEBUG("Run doesn't match required beam energies");
    }
    return beamenergymatch;
  }


  void Analysis::raiseBeamErrorIf(const bool condition) const {
    if (condition && !merging()) {
      throw BeamError("Invalid beam energy for " + name() + "\n");
    }
  }


  // bool Analysis::isCompatible(const ParticlePair& beams) const {
  //   return isCompatible(beams.first.pid(),  beams.second.pid(),
  //                       beams.first.energy(), beams.second.energy());
  // }


  // bool Analysis::isCompatible(PdgId beam1, PdgId beam2, double e1, double e2) const {
  //   PdgIdPair beams(beam1, beam2);
  //   pair<double,double> energies(e1, e2);
  //   return isCompatible(beams, energies);
  // }


  // bool Analysis::beamIDsCompatible(const PdgIdPair& beams) const {
  //   bool beamIDsOk = false;
  //   for (const PdgIdPair& bp : requiredBeams()) {
  //     if (compatible(beams, bp)) {
  //       beamIDsOk =  true;
  //       break;
  //     }
  //   }
  //   return beamIDsOk;
  // }


  // /// Check that the energies are compatible (within 1% or 1 GeV, whichever is larger, for a bit of UI forgiveness)
  // bool Analysis::beamEnergiesCompatible(const pair<double,double>& energies) const {
  //   /// @todo Use some sort of standard ordering to improve comparisons, esp. when the two beams are different particles
  //   bool beamEnergiesOk = requiredEnergies().size() > 0 ? false : true;
  //   typedef pair<double,double> DoublePair;
  //   for (const DoublePair& ep : requiredEnergies()) {
  //     if ((fuzzyEquals(ep.first, energies.first, 0.01) && fuzzyEquals(ep.second, energies.second, 0.01)) ||
  //         (fuzzyEquals(ep.first, energies.second, 0.01) && fuzzyEquals(ep.second, energies.first, 0.01)) ||
  //         (abs(ep.first - energies.first) < 1*GeV && abs(ep.second - energies.second) < 1*GeV) ||
  //         (abs(ep.first - energies.second) < 1*GeV && abs(ep.second - energies.first) < 1*GeV)) {
  //       beamEnergiesOk =  true;
  //       break;
  //     }
  //   }
  //   return beamEnergiesOk;
  // }


  // bool Analysis::beamsCompatible(const PdgIdPair& beams, const pair<double,double>& energies) const {
  //   // bool Analysis::isCompatible(const PdgIdPair& beams, const pair<double,double>& energies) const {

  //   // First check the beam IDs
  //   bool beamIDsOk = false;
  //   for (const PdgIdPair& bp : requiredBeams()) {
  //     if (compatible(beams, bp)) {
  //       beamIDsOk =  true;
  //       break;
  //     }
  //   }
  //   if (!beamIDsOk) return false;

  //   // Next check that the energies are compatible (within 1% or 1 GeV, whichever is larger, for a bit of UI forgiveness)

  //   /// @todo Use some sort of standard ordering to improve comparisons, esp. when the two beams are different particles
  //   bool beamEnergiesOk = requiredEnergies().size() > 0 ? false : true;
  //   typedef pair<double,double> DoublePair;
  //   for (const DoublePair& ep : requiredEnergies()) {
  //     if ((fuzzyEquals(ep.first, energies.first, 0.01) && fuzzyEquals(ep.second, energies.second, 0.01)) ||
  //         (fuzzyEquals(ep.first, energies.second, 0.01) && fuzzyEquals(ep.second, energies.first, 0.01)) ||
  //         (abs(ep.first - energies.first) < 1*GeV && abs(ep.second - energies.second) < 1*GeV) ||
  //         (abs(ep.first - energies.second) < 1*GeV && abs(ep.second - energies.first) < 1*GeV)) {
  //       beamEnergiesOk =  true;
  //       break;
  //     }
  //   }
  //   return beamEnergiesOk;
  // }


  bool Analysis::isCompatibleWithSqrtS(const double energy, double tolerance) const {
    return fuzzyEquals(sqrtS() / GeV, energy / GeV, tolerance);
  }


  ///////////////////////////////////////////


  double Analysis::crossSection() const {
    double xs = handler().crossSection()->val();
    if (isnan(xs)) {
      string errMsg = "cross section missing for analysis " + name() + "; will return 0";
      return 0.;
    }
    return xs;
  }

  double Analysis::crossSectionError() const {
    double xserr = handler().crossSection()->errAvg();
    if (isnan(xserr)) {
      string errMsg = "cross section missing for analysis " + name() + "; will return 0";
      return 0.;
    }
    return xserr;
  }

  double Analysis::crossSectionPerEvent() const {
    return crossSection() / sumW();
  }

  double Analysis::crossSectionErrorPerEvent() const {
    return crossSectionError() / sumW();
  }

  ////////////////////////////////////////////////////////////
  // Histogramming

  // For thread safety.
  static std::mutex cache_ref_data_mutex_guard{};

  void Analysis::_cacheRefData() const {
    std::lock_guard<mutex> lock(cache_ref_data_mutex_guard); // For thread safety.

    if (_refdata.empty()) {
      MSG_TRACE("Getting refdata cache for paper " << name());
      _refdata = getRefData(refDataName());
    }
  }

  // vector<YODA::AnalysisObjectPtr> Analysis::getAllData(bool includeorphans) const{
  //   return handler().getData(includeorphans, false, false);
  // }


  CounterPtr& Analysis::book(CounterPtr& ctr, const string& cname) {
    return ctr = registerAO(Counter(histoPath(cname)));
  }


  CounterPtr& Analysis::book(CounterPtr& ctr,
                             unsigned int datasetID,
                             unsigned int xAxisID,
                             unsigned int yAxisID) {
    const string axisCode = mkAxisCode(datasetID, xAxisID, yAxisID);
    return book(ctr, axisCode);
  }


  Estimate0DPtr& Analysis::book(Estimate0DPtr& est, const string& cname) {
    return est = registerAO(Estimate0D(histoPath(cname)));
  }


  Estimate0DPtr& Analysis::book(Estimate0DPtr& est,
                                unsigned int datasetID,
                                unsigned int xAxisID,
                                unsigned int yAxisID) {
    const string axisCode = mkAxisCode(datasetID, xAxisID, yAxisID);
    return book(est, axisCode);
  }


  /////////////////////

  void Analysis::divide(const Counter& c1, const Counter& c2, Estimate0DPtr est) const {
    const string path = est->path();
    *est = (c1 / c2);
    est->setPath(path);
  }
  //
  void Analysis::divide(CounterPtr c1, CounterPtr c2, Estimate0DPtr est) const {
    return Analysis::divide(*c1, *c2, est);
  }


  void Analysis::divide(const YODA::Estimate0D& e1, const YODA::Estimate0D& e2, Estimate0DPtr est) const {
    const string path = est->path();
    *est = e1 / e2;
  }
  //
  void Analysis::divide(Estimate0DPtr e1, Estimate0DPtr e2, Estimate0DPtr est) const {
    return Analysis::divide(*e1, *e2, est);
  }


}


//////////////////////////////////


namespace Rivet {


  // void Analysis::addAnalysisObject(const MultiplexAOPtr& ao) {
  //   if (handler().stage() == AnalysisHandler::Stage::INIT) {
  //     _analysisobjects.push_back(ao);
  //   }
  //   else {
  //     errormsg(name());
  //   }
  // }


  void Analysis::removeAnalysisObject(const string& path) {
    for (auto it = _analysisobjects.begin(); it != _analysisobjects.end(); ++it) {
      if ((*it)->path() == path) {
        _analysisobjects.erase(it);
        break;
      }
    }
  }

  void Analysis::removeAnalysisObject(const MultiplexAOPtr& ao) {
    for (auto it = _analysisobjects.begin(); it != _analysisobjects.end(); ++it) {
      if ((*it) == ao) {
        _analysisobjects.erase(it);
        break;
      }
    }
  }

  const CentralityProjection& Analysis::declareCentrality(const SingleValueProjection& proj,
                                                          string calAnaName,
                                                          string calHistName,
                                                          const string projName,
                                                          PercentileOrder pctorder) {

    CentralityProjection cproj;

    // Select the centrality variable from option. Use REF as default.
    // Other selections are "GEN", "IMP", "RAW" and "USR" (USR only in HEPMC 3).
    string sel = getOption<string>("cent", "REF");
    set<string> done;

    if (sel == "REF") {
      YODA::Estimate1DPtr refest;
      map<string, YODA::AnalysisObjectPtr> refmap;
      try {
        refmap = getRefData(calAnaName);
      }
      catch (...) {
        MSG_ERROR("No reference calibration file for CentralityProjection "
                  << calAnaName << " found.\nDid you mean to generate one yourself?\n"
                  << "Once generated, you can preload the calibration file using the "
                  << "-p flag\nand steer the routine logic using the 'cent' option "
                  << "with the appropriate value (e.g. =GEN).");
        exit(1);
      }
      if (refmap.find(calHistName) != refmap.end())
        refest = dynamic_pointer_cast<Estimate1D>(refmap.find(calHistName)->second);

      if (!refest) {
        MSG_WARNING("No reference calibration histogram for " << "CentralityProjection " << projName
                                                              << " found " << "(requested histogram "
                                                              << calHistName << " in " << calAnaName << ")");
      }
      else {
        MSG_INFO("Found calibration histogram " << sel << " " << refest->path());
        cproj.add(PercentileProjection(proj, *refest, pctorder), sel);
      }
    }
    else if (sel == "GEN") {
      YODA::Estimate1DPtr genhists = getPreload<Estimate1D>("/" + calAnaName + "/" + calHistName);
      if (!genhists || genhists->areaUnderCurve() <= 0.0) {
        MSG_WARNING("No generated calibration histogram for "
                    << "CentralityProjection " << projName << " found " << "(requested histogram "
                    << calHistName << " in " << calAnaName << ").\nDid you mean to generate one "
                    << "yourself and forgot? Generate with " << calAnaName
                    << " and preload the calibration file using the -p flag.");
      }
      else {
        MSG_INFO("Found calibration histogram " << sel << " " << genhists->path());
        cproj.add(PercentileProjection(proj, *genhists, pctorder), sel);
      }
    }
    else if (sel == "IMP") {
      YODA::Estimate1DPtr imphists = getPreload<Estimate1D>("/" + calAnaName + "/" + calHistName + "_IMP");
      if (!imphists || imphists->areaUnderCurve() <= 0.0) {
        MSG_WARNING("No impact parameter calibration histogram for "
                    << "CentralityProjection " << projName << " found " << "(requested histogram "
                    << calHistName << "_IMP in " << calAnaName << ").\nDid you mean to generate one "
                    << "yourself and forgot? Generate with " << calAnaName
                    << " and preload the calibration file using the -p flag.");
      }
      else {
        MSG_INFO("Found calibration histogram " << sel << " " << imphists->path());
        cproj.add(PercentileProjection(ImpactParameterProjection(), *imphists, PercentileOrder::INCREASING),
                  sel);
      }
    }
    else if (sel == "USR") {
      YODA::Estimate1DPtr usrhists = getPreload<Estimate1D>("/" + calAnaName + "/" + calHistName + "_USR");
      if (!usrhists || usrhists->areaUnderCurve() <= 0.0) {
        MSG_WARNING("No user-defined calibration histogram for "
                    << "CentralityProjection " << projName << " found " << "(requested histogram "
                    << calHistName << "_USR in " << calAnaName << ")");
      }
      else {
        MSG_INFO("Found calibration histogram " << sel << " " << usrhists->path());
        cproj.add(PercentileProjection(UserCentEstimate(), *usrhists, PercentileOrder::INCREASING), sel);
      }
    }
    else if (sel == "RAW") {
      cproj.add(GeneratedPercentileProjection(), sel);
    }
    else
      MSG_ERROR("'" << sel << "' is not a valid PercentileProjection tag.");

    if (cproj.empty()) {
      MSG_WARNING("CentralityProjection " << projName << " did not contain any valid PercentileProjections.");
    }

    return declare(cproj, projName);
  }


  vector<string> Analysis::_weightNames() const {
    return handler().weightNames();
  }

  YODA::AnalysisObjectPtr Analysis::_getPreload(const string& path) const {
    return handler().getPreload(path);
  }

  size_t Analysis::defaultWeightIndex() const {
    return handler().defaultWeightIndex();
  }

  MultiplexAOPtr Analysis::_getOtherAnalysisObject(const std::string& ananame, const std::string& name) {
    std::string path = "/" + ananame + "/" + name;
    const auto& ana = handler().analysis(ananame);
    return ana->getAnalysisObject(name); //< @todo includeorphans check??
  }

  void Analysis::_checkBookInit() const {
    if (handler().stage() != AnalysisHandler::Stage::INIT) {
      MSG_ERROR("Can't book objects outside of init()");
      throw UserError(name() + ": Can't book objects outside of init().");
    }
  }

  bool Analysis::_inInit() const {
    return handler().stage() == AnalysisHandler::Stage::INIT;
  }

  bool Analysis::_inFinalize() const {
    return handler().stage() == AnalysisHandler::Stage::FINALIZE;
  }

}
