#include "Rivet/AnalysisInfo.hh"
#include "Rivet/Config/RivetCommon.hh"
#include "Rivet/Tools/Logging.hh"
#include "Rivet/Tools/RivetPaths.hh"
#include "Rivet/Tools/Utils.hh"
#include "yaml-cpp/yaml.h"
#include <fstream>
#include <iostream>
#include <unistd.h>

#ifdef YAML_NAMESPACE
  #define YAML YAML_NAMESPACE
#endif

namespace Rivet {

  std::string AnalysisInfo::_infoFilePath = "";

  namespace {
    Log& getLog() {
      return Log::getLog("Rivet.AnalysisInfo");
    }
  }


  /// Static factory method
  unique_ptr<AnalysisInfo> AnalysisInfo::make(const std::string& ananame) {
    // Returned AI, in semi-null state
    unique_ptr<AnalysisInfo> ai(new AnalysisInfo);
    ai->_beams += make_pair(PID::ANY, PID::ANY);
    ai->_name = ananame;

    /// If no ana data file found, return null AI
    _infoFilePath = findAnalysisInfoFile(ananame + ".info");
    if (_infoFilePath.empty()) {
      MSG_DEBUG("No datafile " << ananame + ".info found");
    }

    MSG_TRACE("AnalysisInfo pointer = " << ai.get());
    return ai;
  }


  /// Parse info file
  void AnalysisInfo::parseInfoFile() {
    if (_isInitialised || _infoFilePath.empty()) return;

    // Read data from YAML document
    MSG_DEBUG("Reading analysis data from " << _infoFilePath);
    YAML::Node doc;
    try {
      doc = YAML::LoadFile(_infoFilePath);
    }
    catch (const YAML::ParserException& ex) {
      MSG_ERROR("Parse error when reading analysis data from " << _infoFilePath << " (" << ex.what() << ")");
      return;
    }

#define THROW_INFOERR(KEY) throw InfoError("Problem in info parsing while accessing key " + string(KEY) + " in file " + _infoFilePath)

// Simple scalars (test for nullness before casting)
#define TRY_GETINFO(KEY, VAR) try { if (doc[KEY] && !doc[KEY].IsNull()) _ ## VAR = doc[KEY].as<string>(); } catch (...) { THROW_INFOERR(KEY); }
#define TRY_GETINFO_DEFAULT(KEY, VAR, DEFAULT) try { if (doc[KEY] && !doc[KEY].IsNull()) _ ## VAR = doc[KEY].as<string>(); } catch (...) { _ ## VAR = DEFAULT; }
#define TRY_GETINFO_DBL(KEY, VAR, DEFAULT) try { if (doc[KEY] && !doc[KEY].IsNull()) _ ## VAR = doc[KEY].as<double>(); } catch (...) { THROW_INFOERR(KEY); }
#define TRY_GETINFO_DBL_DEFAULT(KEY, VAR, DEFAULT) try { if (doc[KEY] && !doc[KEY].IsNull()) _ ## VAR = doc[KEY].as<double>(); } catch (...) { _ ## VAR = DEFAULT; }
    TRY_GETINFO("Name", name);
    TRY_GETINFO("Summary", summary);
    TRY_GETINFO("Status", status);
    TRY_GETINFO("RunInfo", runInfo);
    TRY_GETINFO("Description", description);
    TRY_GETINFO("Experiment", experiment);
    TRY_GETINFO("Collider", collider);
    TRY_GETINFO("Year", year);
    TRY_GETINFO("SpiresID", spiresID);
    TRY_GETINFO("InspireID", inspireID);
    TRY_GETINFO("BibKey", bibKey);
    TRY_GETINFO("BibTeX", bibTeX);
    TRY_GETINFO_DEFAULT("Warning", warning, "");
    TRY_GETINFO_DEFAULT("RefMatch", refmatch, "");
    TRY_GETINFO_DEFAULT("RefUnmatch", refunmatch, "");
    TRY_GETINFO_DEFAULT("WriterDoublePrecision", writerdoubleprecision, "");
    TRY_GETINFO_DBL_DEFAULT("Luminosity_fb", luminosityfb, -1);
#undef TRY_GETINFO
#undef TRY_GETINFO_DEFAULT
#undef TRY_GETINFO_DBL
#undef TRY_GETINFO_DBL_DEFAULT

    // Normalise the status info to upper-case
    _status = toUpper(_status);

// Sequences (test the seq *and* each entry for nullness before casting)
#define TRY_GETINFO_SEQ(KEY, VAR) try { \
        if (doc[KEY] && !doc[KEY].IsNull()) {                           \
          const YAML::Node& VAR = doc[KEY];                             \
          for (size_t i = 0; i < VAR.size(); ++i)                       \
            if (!VAR[i].IsNull()) _ ## VAR += VAR[i].as<string>();  \
        } } catch (...) { THROW_INFOERR(KEY); }
    TRY_GETINFO_SEQ("Authors", authors);
    TRY_GETINFO_SEQ("References", references);
    TRY_GETINFO_SEQ("ToDo", todos);
    TRY_GETINFO_SEQ("Keywords", keywords);
    TRY_GETINFO_SEQ("Options", options);
    TRY_GETINFO_SEQ("ReleaseTests", validation);
#undef TRY_GETINFO_SEQ

    // Build the option map
    buildOptionMap();

    // A boolean with some name flexibility
    try {
      if (doc["NeedsCrossSection"])
        _needsCrossSection = doc["NeedsCrossSection"].as<bool>();
      else if (doc["NeedCrossSection"])
        _needsCrossSection = doc["NeedCrossSection"].as<bool>();
    }
    catch (...) {
      THROW_INFOERR("NeedsCrossSection|NeedCrossSection");
    }

    // Check if reentrant
    try {
      if (doc["Reentrant"]) _reentrant = doc["Reentrant"].as<bool>();
    }
    catch (...) {
      if (statuscheck("REENTRANT") && !statuscheck("NOTREENTRY")) {
        _reentrant = true;
      }
    }

    // Beam particle identities
    try {
      if (doc["Beams"]) {
        const YAML::Node& beams = doc["Beams"];
        vector<PdgIdPair> beam_pairs;
        if (beams.size() == 2 && beams[0].IsScalar() && beams[1].IsScalar()) {
          beam_pairs += PID::make_pdgid_pair(beams[0].as<string>(), beams[1].as<string>());
        }
        else {
          for (size_t i = 0; i < beams.size(); ++i) {
            const YAML::Node& bp = beams[i];
            if (bp.size() != 2 || !bp[0].IsScalar() || !bp[1].IsScalar())
              throw InfoError(
                  "Beam ID pairs have to be either a 2-tuple or a list of 2-tuples of particle names");
            beam_pairs += PID::make_pdgid_pair(bp[0].as<string>(), bp[1].as<string>());
          }
        }
        _beams = beam_pairs;
      }
    }
    catch (...) {
      THROW_INFOERR("Beams");
    }


    // Beam energies
    try {
      if (doc["Energies"]) {
        vector<pair<double, double>> beam_energy_pairs;
        for (size_t i = 0; i < doc["Energies"].size(); ++i) {
          const YAML::Node& be = doc["Energies"][i];
          if (be.IsScalar()) {
            // If beam energy is a scalar, then assume symmetric beams each with half that energy
            beam_energy_pairs += make_pair(be.as<double>() / 2.0, be.as<double>() / 2.0);
          }
          else if (be.IsSequence()) {
            if (be.size() != 2)
              throw InfoError("Beam energies have to be a list of either numbers or pairs of numbers");
            beam_energy_pairs += make_pair(be[0].as<double>(), be[1].as<double>());
          }
          else {
            throw InfoError("Beam energies have to be a list of either numbers or pairs of numbers");
          }
        }
        _energies = beam_energy_pairs;
      }
    }
    catch (...) {
      THROW_INFOERR("Energies");
    }

#undef THROW_INFOERR

    _isInitialised = true;
  }


  /// Return the path to the reference data file
  std::string AnalysisInfo::refFile() const {
    return findAnalysisRefFile(name() + ".yoda");
  }


  /// Render the AnalysisInfo as a string
  string toString(const AnalysisInfo& ai) {
    std::stringstream ss;
    ss << ai.name();
    ss << " - " << ai.summary();
    // ss << " - " << ai.beams();
    // ss << " - " << ai.energies();
    ss << " (" << ai.status() << ")";
    return ss.str();
  }


  void AnalysisInfo::buildOptionMap() {
    _optionmap.clear();
    for (auto opttag : _options) {
      std::vector<std::string> optv = split(opttag, "=");
      std::string optname = optv[0];
      if (optv.size() < 2) {
        throw InfoError("Option '" + optname
                        + "' should have a default value; use '#' to indicate arbitrary FP values");
      }
      for (auto opt : split(optv[1], ",")) {
        _optionmap[optname].insert(opt);
      }
    }
  }


  bool AnalysisInfo::validOption(std::string key, std::string val) const {
    if (key == "ENERGY"s) return true;
    auto opt = _optionmap.find(key);
    // The option is required to be defined in the .info file.
    if (opt == _optionmap.end()) return false;
    // If the selection option is among the range of given options,
    // we are fine.
    if (opt->second.find(val) != opt->second.end()) return true;
    // Wildcard selection option for value types is #.
    if (opt->second.size() == 1 && *opt->second.begin() == "#") {
      std::istringstream ss(val);
      double test;
      if (ss >> test) return true;
    }
    // Wildcard selection option for any type is *.
    if (opt->second.size() == 1 && *opt->second.begin() == "*") return true;
    return false;
  }

}
