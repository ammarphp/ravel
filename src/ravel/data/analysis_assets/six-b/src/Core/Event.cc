// -*- C++ -*-
#include "Rivet/Event.hh"
#include "Rivet/Projections/Beam.hh"
#include "Rivet/Tools/BeamConstraint.hh"
#include "Rivet/Tools/Logging.hh"
#include "Rivet/Tools/Utils.hh"

namespace Rivet {


  Log& Event::getLog() const {
    return Log::getLog("Rivet.Event");
  }


  ParticlePair Event::beams() const {
    return Rivet::beams(*this);
  }


  double Event::sqrtS() const {
    return Rivet::sqrtS(beams());
  }


  double Event::asqrtS() const {
    return Rivet::asqrtS(beams());
  }


  void Event::_fixGenEvent() {
#ifdef HEPMC_HAS_UNITS
    const_cast<GenEvent&>(_genevent).use_units(HepMC::Units::GEV, HepMC::Units::MM);
#endif
  }

  // void Event::_strip(GenEvent& ge) {
  //   HepMCUtils::strip(ge);
  // }

  const Particles& Event::allParticles() const {
    if (_particles.empty()) { //< assume that empty means no attempt yet made
      for (ConstGenParticlePtr gp : HepMCUtils::particles(genEvent())) {
        _particles += Particle(gp);
      }
    }
    return _particles;
  }


  std::valarray<double> Event::weights() const {
    if (!_weights.size()) {
      const std::valarray<double> ws = HepMCUtils::weights(_genevent);
      const size_t Nselws = _weightIndices.size();
      if (!ws.size()) { // If no weights (original or selected), make a dummy single-weight array
        MSG_DEBUG("GenEvent has no weights! Creating dummy single, unit-weight vector");
        _weights = std::valarray<double>{1.0};
      }
      else if (ws.size() == Nselws) { // All weights are selected => just use the raw valarray
        _weights = ws;                //< correct ordering is guaranteed
      }
      else { // Using a subset of weights => copy selected ones into a new array
        _weights = std::valarray<double>(Nselws);
        for (size_t i = 0; i < Nselws; ++i) _weights[i] = ws[_weightIndices[i]];
      }
    }
    return _weights;
  }

  std::vector<std::pair<double, double>> Event::crossSections() const {
    if (!_xsecs.size()) {
      if (!_genevent.cross_section()) {
        // If no cross-section is provided by the generator, set dummy cross-section
        MSG_DEBUG("GenEvent has no cross-section! Returning a dummy 0,0 pair");
        _xsecs = {std::make_pair(0.0, 0.0)};
      }
      else { // select relevant subset of cross-sections
        const size_t Nselws = _weightIndices.size();
        _xsecs.resize(Nselws);
        for (size_t i = 0; i < Nselws; ++i) {
          _xsecs[i] = HepMCUtils::crossSection(_genevent, _weightIndices[i]);
        }
        // HepMC3 demands that variations cross-sections be explicitly set by the generator,
        // in such a way that it cannot be used directly with HepMC2 files - where these are
        // typically missing - unless the user is willing to jump through ludicrous hoops.
        bool allEqual = std::adjacent_find(_xsecs.begin(), _xsecs.end(), std::not_equal_to<>())
            == _xsecs.end();
        allEqual |= std::adjacent_find(_xsecs.begin() + 1, _xsecs.end(), std::not_equal_to<>())
            == _xsecs.end();
        if (allEqual) return {HepMCUtils::crossSection(_genevent)};
      }
    }
    return _xsecs;
  }


}
