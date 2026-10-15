// -*- C++ -*-
//
// This file is part of YODA -- Yet more Objects for Data Analysis
// Copyright (C) 2008-2025 The YODA collaboration (see AUTHORS for details)
//
#include "YODA/WriterYODA.h"

#include <iostream>
#include <iomanip>
using namespace std;

namespace YODA {


  /// Singleton creation function
  Writer& WriterYODA::create() {
    static WriterYODA _instance;
    _instance.setPrecision(6);
    return _instance;
  }


  /// YODA text-format version
  ///
  /// - V1/empty = make-plots annotations style
  /// - V2 = YAML annotations
  /// - V3 = YODA2 types
  static const int YODA_FORMAT_VERSION = 3;


  // Version-formatting helper function
  inline string _iotypestr(const string& baseiotype) {
    ostringstream os;
    os << "YODA_" << Utils::toUpper(baseiotype) << "_V" << YODA_FORMAT_VERSION;
    return os.str();
  }


  void WriterYODA::_writeAnnotations(std::ostream& os, const AnalysisObject& ao) {
    os << scientific << setprecision(_aoprecision);
    for (const string& a : ao.annotations()) {
      if (a.empty()) continue;
      /// @todo Write out floating point annotations as scientific notation
      string ann = ao.annotation(a);
      // remove spurious line returns at the end of a string so that we don't
      // end up with two line returns.
      ann.erase(std::remove(ann.begin(), ann.end(), '\n'), ann.end());
      os << a << ": " << ann << "\n";
    }
    os << "---\n";
  }


  void WriterYODA::writeAO(std::ostream& os, const AnalysisObject& ao) {
    ios_base::fmtflags oldflags = os.flags();
    os << scientific << showpoint << setprecision(_aoprecision);
    os << "BEGIN " << _iotypestr(ao.type()) << " " << ao.path() << "\n";
    _writeAnnotations(os, ao);
    ao._renderYODA(os, _aoprecision+7); // = "-1." + _aoprecision + "e+23"
    os << "END " << _iotypestr(ao.type()) << "\n\n";
    os << flush;
    os.flags(oldflags);
  }

}
