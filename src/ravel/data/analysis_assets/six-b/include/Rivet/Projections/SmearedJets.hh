// -*- C++ -*-
#ifndef RIVET_SmearedJets_HH
#define RIVET_SmearedJets_HH

#include "Rivet/Jet.hh"
#include "Rivet/Particle.hh"
#include "Rivet/Projection.hh"
#include "Rivet/Projections/JetFinder.hh"
#include "Rivet/Tools/SmearingFunctions.hh"
#include <functional>

namespace Rivet {


  /// @todo Allow applying a pre-smearing cut so smearing doesn't need to be applied to below-threshold micro-jets


  /// Wrapper projection for smearing {@link Jet}s with detector resolutions and efficiencies
  class SmearedJets : public JetFinder {
  public:

    /// @name Constructors etc.
    /// @{

    /// @brief Constructor with a reco efficiency and optional tagging efficiencies
    ///
    /// @todo Add a tau-tag slot
    SmearedJets(const JetFinder& ja,
                const JetSmearFn& smearFn,
                const JetEffFn& bTagEffFn = JET_BTAG_PERFECT,
                const JetEffFn& cTagEffFn = JET_CTAG_PERFECT)
        : SmearedJets(ja, bTagEffFn, cTagEffFn, smearFn) { }


    /// @brief Constructor with a parameter pack of efficiency and smearing functions,
    /// plus optional tagging efficiencies
    ///
    /// @todo Add a tau-tag slot
    template <typename... Args, typename = std::enable_if_t<allArgumentsOf<JetEffSmearFn, Args...>::value>>
    SmearedJets(const JetFinder& ja,
                const JetEffFn& bTagEffFn,
                const JetEffFn& cTagEffFn,
                Args&&... effSmearFns)
        : _detFns({JetEffSmearFn(std::forward<Args>(effSmearFns))...}),
          _bTagEffFn(bTagEffFn),
          _cTagEffFn(cTagEffFn) {
      setName("SmearedJets");
      declare(ja, "TruthJets");
      _noSmear = getEnvParam<bool>("RIVET_DISABLE_SMEARING", false);
    }

    /// @todo How to include tagging effs?
    /// @todo Variadic eff/smear fn list?
    /// @todo Add a trailing Cut arg cf. SmearedParticles? -- wrap into an eff function


    /// Clone on the heap.
    RIVET_DEFAULT_PROJ_CLONE(SmearedJets);

    /// @}

    /// Import to avoid warnings about overload-hiding
    using Projection::operator=;


    /// Compare to another SmearedJets
    CmpState compare(const Projection& p) const {
      // Compare truth jets definitions
      const CmpState teq = mkPCmp(p, "TruthJets");
      if (teq != CmpState::EQ) return teq;

      // Short-circuit if smearing is disabled
      if (_noSmear) return CmpState::EQ;

      // Compare lists of detector functions
      const SmearedJets& other = dynamic_cast<const SmearedJets&>(p);
      const CmpState nfeq = cmp(_detFns.size(), other._detFns.size());
      if (nfeq != CmpState::EQ) return nfeq;
      for (size_t i = 0; i < _detFns.size(); ++i) {
        const CmpState feq = _detFns[i].cmp(other._detFns[i]);
        if (feq != CmpState::EQ) return feq;
      }
      return Rivet::cmp(get_address(_bTagEffFn), get_address(other._bTagEffFn))
          || Rivet::cmp(get_address(_cTagEffFn), get_address(other._cTagEffFn));
    }


    /// Perform the jet finding & smearing calculation
    void project(const Event& e) {
      const Jets& truthjets = apply<JetFinder>(e, "TruthJets").jetsByPt(); //truthJets();

      // Short-circuit if smearing is disabled
      if (_noSmear) {
        _recojets = truthjets;
        return;
      }

      // Apply jet smearing and efficiency transforms
      _recojets.clear();
      _recojets.reserve(truthjets.size());
      for (const Jet& j : truthjets) {
        Jet jdet = j;
        bool keep = true;
        MSG_DEBUG("Truth jet: " << "mom=" << jdet.mom() / GeV << " GeV, pT=" << jdet.pT() / GeV
                                << ", eta=" << jdet.eta());
        for (const JetEffSmearFn& fn : _detFns) {
          double jeff = -1;
          std::tie(jdet, jeff) = fn(jdet); // smear & eff
          // Re-add constituents & tags if (we assume accidentally) they were lost by the smearing function
          if (jdet.particles().empty() && !j.particles().empty()) jdet.particles() = j.particles();
          if (jdet.tags().empty() && !j.tags().empty()) jdet.tags() = j.tags();
          MSG_DEBUG("         ->" << "mom=" << jdet.mom() / GeV << " GeV, pT=" << jdet.pT() / GeV
                                  << ", eta=" << jdet.eta());
          // MSG_DEBUG("New det jet: "
          //           << "mom=" << jdet.mom()/GeV << " GeV, pT=" << jdet.pT()/GeV << ", eta=" << jdet.eta()
          //           << ", b-tag=" << boolalpha << jdet.bTagged()
          //           << ", c-tag=" << boolalpha << jdet.cTagged()
          //           << " : eff=" << 100*jeff << "%");
          if (jeff <= 0) {
            keep = false;
            break;
          } //< no need to roll expensive dice (and we deal with -ve probabilities, just in case)
          if (jeff < 1 && rand01() > jeff) {
            keep = false;
            break;
          } //< roll dice (and deal with >1 probabilities, just in case)
        }
        if (keep) _recojets.push_back(jdet);
      }
      // Apply tagging efficiencies, using smeared kinematics as input to the tag eff functions
      for (Jet& j : _recojets) {
        // Decide whether or not there should be a b-tag on this jet
        const double beff = _bTagEffFn ? _bTagEffFn(j) : j.bTagged();
        const bool btag = beff == 1 || (beff != 0 && rand01() < beff);
        // Remove b-tags if needed, and add a dummy one if needed
        if (!btag && j.bTagged())
          j.tags().erase(std::remove_if(j.tags().begin(), j.tags().end(), hasBottom), j.tags().end());
        if (btag && !j.bTagged())
          j.tags().push_back(
              Particle(PID::BQUARK,
                       j.mom())); ///< @todo Or could use the/an actual clustered b-quark momentum?
        // Decide whether or not there should be a c-tag on this jet
        const double ceff = _cTagEffFn ? _cTagEffFn(j) : j.cTagged();
        const bool ctag = ceff == 1 || (ceff != 0 && rand01() < beff);
        // Remove c-tags if needed, and add a dummy one if needed
        if (!ctag && j.cTagged())
          j.tags().erase(std::remove_if(j.tags().begin(), j.tags().end(), hasCharm), j.tags().end());
        if (ctag && !j.cTagged()) j.tags().push_back(Particle(PID::CQUARK, j.mom())); ///< @todo As above... ?
      }
    }


    /// Return the full jet list for the JetFinder methods to use
    Jets _jets() const {
      return _recojets;
    }

    /// Get the truth jets (sorted by pT)
    const Jets truthJets() const {
      return getProjection<JetFinder>("TruthJets").jetsByPt();
    }

    /// Reset the projection. Smearing functions will be unchanged.
    void reset() {
      _recojets.clear();
    }


  protected:

    /// Smeared jets
    Jets _recojets;

    /// Stored efficiency & smearing functions
    vector<JetEffSmearFn> _detFns;

    /// Stored efficiency functions
    JetEffFn _bTagEffFn, _cTagEffFn;

    /// Flag to disable smearing
    ///
    /// @todo Could/should be handled statically and centrally
    bool _noSmear{false};
  };


}

#endif
