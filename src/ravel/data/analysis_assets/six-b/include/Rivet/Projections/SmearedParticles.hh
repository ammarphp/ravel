// -*- C++ -*-
#ifndef RIVET_SmearedParticles_HH
#define RIVET_SmearedParticles_HH

#include "Rivet/Particle.hh"
#include "Rivet/Projection.hh"
#include "Rivet/Projections/ParticleFinder.hh"
#include "Rivet/Tools/SmearingFunctions.hh"

namespace Rivet {


  /// Wrapper projection for smearing {@link Jet}s with detector resolutions and efficiencies
  class SmearedParticles : public ParticleFinder {
  public:

    /// @name Constructors etc.
    /// @{

    /// @brief Constructor with a variadic ordered list of efficiency and smearing function args
    template <typename... Args,
              typename = std::enable_if_t<allArgumentsOf<ParticleEffSmearFn, Args...>::value>>
    SmearedParticles(const ParticleFinder& pf, Args&&... effSmearFns)
        : SmearedParticles(pf, Cuts::open(), std::forward<Args>(effSmearFns)...) { }

    /// @brief Constructor with a variadic ordered list of efficiency and smearing function args
    ///
    /// @note The Cut must be provided *before* the eff/smearing functions
    ///
    /// @todo Wouldn't it be nice if the Cut could also go *after* the parameter pack?
    template <typename... Args,
              typename = std::enable_if_t<allArgumentsOf<ParticleEffSmearFn, Args...>::value>>
    SmearedParticles(const ParticleFinder& pf, const Cut& c, Args&&... effSmearFns)
        : ParticleFinder(c), _detFns({ParticleEffSmearFn(std::forward<Args>(effSmearFns))...}) {
      setName("SmearedParticles");
      declare(pf, "TruthParticles");
      _noSmear = getEnvParam<bool>("RIVET_DISABLE_SMEARING", false);
    }


    /// Clone on the heap.
    RIVET_DEFAULT_PROJ_CLONE(SmearedParticles);

    /// @}

    /// Import to avoid warnings about overload-hiding
    using Projection::operator=;


    /// Compare to another SmearedParticles
    ///
    /// @note Comparing detector functions doesn't work for functors/lambdas,
    /// hence are always treated as not equivalent
    CmpState compare(const Projection& p) const {
      const SmearedParticles& other = dynamic_cast<const SmearedParticles&>(p);

      // Compare truth particles definitions
      const CmpState teq = mkPCmp(other, "TruthParticles");
      if (teq != CmpState::EQ) return teq;

      // Compare cuts
      if (_cuts != other._cuts) return CmpState::NEQ;

      // Compare lists of detector functions
      if (!_noSmear) {
        const CmpState nfeq = cmp(_detFns.size(), other._detFns.size());
        MSG_TRACE("Numbers of detector functions = " << _detFns.size() << " VS " << other._detFns.size());
        if (nfeq != CmpState::EQ) return nfeq;
        for (size_t i = 0; i < _detFns.size(); ++i) {
          const CmpState feq = _detFns[i].cmp(other._detFns[i]);
          if (feq != CmpState::EQ) return feq;
        }
      }

      // If we got this far, we're equal
      MSG_DEBUG("Equivalent detected! " << p.name() << ", " << this->name());
      return CmpState::EQ;
    }


    /// Perform the particle finding & smearing calculation
    void project(const Event& e) {
      const Particles& truthparticles = apply<ParticleFinder>(e, "TruthParticles")
                                            .particlesByPt(); //truthParticles();

      // Short-circuit (with cuts) if smearing is disabled
      if (_noSmear) {
        _theParticles = select(truthparticles, _cuts);
        return;
      }

      // Apply the smearing and then reco-level cuts to each particle
      _theParticles.clear();
      _theParticles.reserve(truthparticles.size());
      for (const Particle& p : truthparticles) {
        Particle pdet = p;
        double peff = -1;
        bool keep = true;
        MSG_TRACE("Number of detector functions = " << _detFns.size());
        for (const ParticleEffSmearFn& fn : _detFns) {
          std::tie(pdet, peff) = fn(pdet); // smear & eff
          // Test the short-circuit random numbers if possible; note handling of < 0 and > 1 probabilities
          if (peff <= 0 || rand01() > peff) keep = false;
          MSG_DEBUG("New det particle: pid=" << pdet.pid() << ", mom=" << pdet.mom() / GeV << " GeV, "
                                             << "pT=" << pdet.pT() / GeV << ", eta=" << pdet.eta()
                                             << " : eff=" << 100 * peff << "%, discarded=" << std::boolalpha
                                             << !keep);
          if (!keep) break; // discarded; no need to try more smear-eff functions
        }
        // If discarding, go straight to the next particle
        if (!keep) continue;
        // Ensure the smeared particle satisfies the cuts associated with this projection
        if (!_cuts->accept(pdet)) continue;

        // Store, recording where the smearing was built from
        pdet.addConstituent(p); ///< @todo Is this a good idea?? What if raw particles are requested?
        _theParticles.push_back(pdet);
      }
    }

    /// Get the truth particles (sorted by pT)
    const Particles truthParticles() const {
      return getProjection<ParticleFinder>("TruthParticles").particlesByPt();
    }

    /// Reset the projection. Smearing functions will be unchanged.
    void reset() {
      _theParticles.clear();
    }


  protected:

    /// Stored efficiency & smearing functions
    vector<ParticleEffSmearFn> _detFns;

    /// Flag to disable smearing
    ///
    /// @todo Could/should be handled statically and centrally
    bool _noSmear{false};
  };


}

#endif
