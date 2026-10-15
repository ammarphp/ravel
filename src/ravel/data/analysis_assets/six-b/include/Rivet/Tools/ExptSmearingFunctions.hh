// -*- C++ -*-
#ifndef RIVET_ExptSmearingFunctions_HH
#define RIVET_ExptSmearingFunctions_HH

#include "Rivet/Tools/JetSmearingFunctions.hh"
#include "Rivet/Tools/MomentumSmearingFunctions.hh"
#include "Rivet/Tools/ParticleSmearingFunctions.hh"

namespace Rivet {


  /// @defgroup smearing Detector smearing & efficiency functions
  ///
  /// A family of smearing functions must include the following names and return types:
  ///
  ///   ParticleEffFn <PARTICLE>_EFF_<FAMILY>_<IDCLASS>
  ///   ParticleSmearFn <PARTICLE>_SMEAR_<FAMILY>
  ///   ParticleEffFn TRK_EFF_<FAMILY>
  ///   ParticleSmearFn TRK_SMEAR_<FAMILY>
  ///   JetEffFn JET_BTAG_<FAMILY>_<TAGGER>
  ///   JetSmearFn JET_SMEAR_<FAMILY>
  ///   METSmearParamsFn MET_SMEARPARAMS_<FAMILY>
  ///   METSmearFn MET_SMEAR_<FAMILY>
  ///
  /// where @c <PARTICLE> is all of @c ELECTRON, @c MUON, @c PHOTON, and @c TAU,
  /// @c <IDCLASS> is all of @c LOOSE, @c MEDIUM, and @c TIGHT. The family name
  /// and tagger name are free (within the constraints of function naming. Providing
  /// a full set may require use of alias/wrapper functions and/or the predefined
  /// eff/smearing @c IDENTITY functions.
  ///
  /// @{


  /// @defgroup smearing_elec Experiment-specific electron efficiency and smearing functions
  /// @{

  /// ATLAS Run 1 electron reconstruction efficiency
  /// @todo Include reco eff (but no e/y discrimination) in forward region
  inline double ELECTRON_RECOEFF_ATLAS_RUN1(const Particle& e) {
    if (e.abspid() != PID::ELECTRON) return 0;
    if (e.abseta() > 2.5) return 0;
    if (e.pT() < 10 * GeV) return 0;
    return (e.abseta() < 1.5) ? 0.95 : 0.85;
  }

  /// ATLAS Run 2 electron reco efficiency
  ///
  /// Based on https://arxiv.org/pdf/1902.04655.pdf Fig 2
  inline double ELECTRON_RECOEFF_ATLAS_RUN2(const Particle& e) {
    if (e.abspid() != PID::ELECTRON) return 0;
    const double et = e.Et();
    if (e.abseta() > 2.5 || e.Et() < 2 * GeV) return 0;
    if (et > 25 * GeV) return 0.97;
    if (et > 10 * GeV) return 0.92 + (et / GeV - 10) / 15. * 0.05;
    if (et > 6 * GeV) return 0.85 + (et / GeV - 6) / 4. * 0.07;
    if (et > 5 * GeV) return 0.70 + (et / GeV - 5) / 1. * 0.15;
    if (et > 2 * GeV) return 0.00 + (et / GeV - 2) / 3. * 0.70;
    return 0;
  }


  /// @brief ATLAS Run 2 'loose' electron reco+identification efficiency
  ///
  /// Values read from Fig 3 of ATL-PHYS-PUB-2015-041
  ///
  /// @todo What about faking by jets or non-electrons?
  inline double ELECTRON_EFF_ATLAS_RUN2_LOOSE(const Particle& e) {
    if (e.abspid() != PID::ELECTRON) return 0;

    // Manually symmetrised eta eff histogram
    const static vector<double> edges_eta = {0.0, 0.1, 0.8, 1.37, 1.52, 2.01, 2.37, 2.47};
    const static vector<double> effs_eta = {0.950, 0.965, 0.955, 0.885, 0.950, 0.935, 0.90};
    // Et eff histogram (10-20 is a guess)
    const static vector<double> edges_et = {0, 10, 20, 25, 30, 35, 40, 45, 50, 60, 80};
    const static vector<double> effs_et = {
        0.0,   0.90,  0.91, 0.92, 0.94, 0.95,
        0.955, 0.965, 0.97, 0.98, 0.98}; //Extra value extrapolated for overflow

    if (e.abseta() > 2.47) return 0.0; // no ID outside the tracker

    const int i_eta = binIndex(e.abseta(), edges_eta);
    const int i_et = binIndex(e.Et() / GeV, edges_et, true);
    const double eff = effs_et[i_et] * effs_eta[i_eta]
        / 0.95; //< norm factor as approximate double differential
    return min(eff, 1.0) * ELECTRON_RECOEFF_ATLAS_RUN2(e);
  }

  /// @brief Pretend that ATLAS Run 1 loose was the same as in Run 2
  inline double ELECTRON_EFF_ATLAS_RUN1_LOOSE(const Particle& e) {
    return ELECTRON_EFF_ATLAS_RUN2_LOOSE(e);
  }


  /// @brief ATLAS Run 1 'medium' electron reco+identification efficiency
  inline double ELECTRON_EFF_ATLAS_RUN1_MEDIUM(const Particle& e) {
    if (e.abspid() != PID::ELECTRON) return 0;

    const static vector<double> eta_edges_10 = {0.000, 0.049, 0.454, 1.107, 1.46, 1.790, 2.277, 2.500};
    const static vector<double> eta_vals_10 = {0.730, 0.757, 0.780, 0.771, 0.77, 0.777, 0.778};

    const static vector<double> eta_edges_15 = {0.000, 0.053, 0.456, 1.102, 1.463, 1.783, 2.263, 2.500};
    const static vector<double> eta_vals_15 = {0.780, 0.800, 0.819, 0.759, 0.749, 0.813, 0.829};

    const static vector<double> eta_edges_20 = {0.000, 0.065, 0.362, 0.719, 0.980, 1.289,
                                                1.455, 1.681, 1.942, 2.239, 2.452, 2.500};
    const static vector<double> eta_vals_20 = {0.794, 0.806, 0.816, 0.806, 0.797, 0.774,
                                               0.764, 0.788, 0.793, 0.806, 0.825};

    const static vector<double> eta_edges_25 = {0.000, 0.077, 0.338, 0.742, 1.004, 1.265,
                                                1.467, 1.692, 1.940, 2.227, 2.452, 2.500};
    const static vector<double> eta_vals_25 = {0.833, 0.843, 0.853, 0.845, 0.839, 0.804,
                                               0.790, 0.825, 0.830, 0.833, 0.839};

    const static vector<double> eta_edges_30 = {0.000, 0.077, 0.350, 0.707, 0.980, 1.289,
                                                1.479, 1.681, 1.942, 2.239, 2.441, 2.500};
    const static vector<double> eta_vals_30 = {0.863, 0.872, 0.881, 0.874, 0.870, 0.824,
                                               0.808, 0.847, 0.845, 0.840, 0.842};

    const static vector<double> eta_edges_35 = {0.000, 0.058, 0.344, 0.700, 1.009, 1.270,
                                                1.458, 1.685, 1.935, 2.231, 2.468, 2.500};
    const static vector<double> eta_vals_35 = {0.878, 0.889, 0.901, 0.895, 0.893, 0.849,
                                               0.835, 0.868, 0.863, 0.845, 0.832};

    const static vector<double> eta_edges_40 = {0.000, 0.047, 0.355, 0.699, 0.983, 1.280,
                                                1.446, 1.694, 1.943, 2.227, 2.441, 2.500};
    const static vector<double> eta_vals_40 = {0.894, 0.901, 0.909, 0.905, 0.904, 0.875,
                                               0.868, 0.889, 0.876, 0.848, 0.827};

    const static vector<double> eta_edges_45 = {0.000, 0.058, 0.356, 0.712, 0.997, 1.282,
                                                1.459, 1.686, 1.935, 2.220, 2.444, 2.500};
    const static vector<double> eta_vals_45 = {0.900, 0.911, 0.923, 0.918, 0.917, 0.897,
                                               0.891, 0.904, 0.894, 0.843, 0.796};

    const static vector<double> eta_edges_50 = {0.000, 0.059, 0.355, 0.711, 0.983, 1.280,
                                                1.469, 1.682, 1.919, 2.227, 2.441, 2.500};
    const static vector<double> eta_vals_50 = {0.903, 0.913, 0.923, 0.922, 0.923, 0.903,
                                               0.898, 0.908, 0.895, 0.831, 0.774};

    const static vector<double> eta_edges_60 = {0.000, 0.053, 0.351, 0.720, 1.006, 1.291,
                                                1.469, 1.696, 1.946, 2.243, 2.455, 2.500};
    const static vector<double> eta_vals_60 = {0.903, 0.917, 0.928, 0.924, 0.927, 0.915,
                                               0.911, 0.915, 0.899, 0.827, 0.760};

    const static vector<double> eta_edges_80 = {0.000, 0.053, 0.351, 0.720, 0.994, 1.292,
                                                1.482, 1.708, 1.934, 2.220, 2.458, 2.500};
    const static vector<double> eta_vals_80 = {0.936, 0.942, 0.952, 0.956, 0.956, 0.934,
                                               0.931, 0.944, 0.933, 0.940, 0.948};

    const static vector<double> et_edges = {10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 80};
    const static vector<vector<double>> et_eta_edges = {eta_edges_10, eta_edges_15, eta_edges_20,
                                                        eta_edges_25, eta_edges_30, eta_edges_35,
                                                        eta_edges_40, eta_edges_45, eta_edges_50,
                                                        eta_edges_60, eta_edges_80};
    const static vector<vector<double>> et_eta_vals = {eta_vals_10, eta_vals_15, eta_vals_20, eta_vals_25,
                                                       eta_vals_30, eta_vals_35, eta_vals_40, eta_vals_45,
                                                       eta_vals_50, eta_vals_60, eta_vals_80};

    if (e.abseta() > 2.5 || e.Et() < 10 * GeV) return 0.0;
    const int i_et = binIndex(e.Et() / GeV, et_edges, true);
    const int i_eta = binIndex(e.abseta(), et_eta_edges[i_et]);
    return et_eta_vals[i_et][i_eta] * ELECTRON_RECOEFF_ATLAS_RUN1(e);
  }

  /// @brief ATLAS Run 2 'medium' electron reco+identification efficiency
  ///
  /// ~1% increase over Run 1 informed by Fig 1 in https://cds.cern.ch/record/2157687/files/ATLAS-CONF-2016-024.pdf
  inline double ELECTRON_EFF_ATLAS_RUN2_MEDIUM(const Particle& e) {
    if (e.abspid() != PID::ELECTRON) return 0;
    return 1.01 * ELECTRON_EFF_ATLAS_RUN1_MEDIUM(e);
  }


  /// @brief ATLAS Run 1 'tight' electron reco+identification efficiency
  inline double ELECTRON_EFF_ATLAS_RUN1_TIGHT(const Particle& e) {
    if (e.abspid() != PID::ELECTRON) return 0;

    const static vector<double> eta_edges_10 = {0.000, 0.049, 0.459, 1.100, 1.461, 1.789, 2.270, 2.500};
    const static vector<double> eta_vals_10 = {0.581, 0.632, 0.668, 0.558, 0.548, 0.662, 0.690};

    const static vector<double> eta_edges_15 = {0.000, 0.053, 0.450, 1.096, 1.463, 1.783, 2.269, 2.500};
    const static vector<double> eta_vals_15 = {0.630, 0.678, 0.714, 0.633, 0.616, 0.700, 0.733};

    const static vector<double> eta_edges_20 = {0.000, 0.065, 0.362, 0.719, 0.992, 1.277,
                                                1.479, 1.692, 1.930, 2.227, 2.464, 2.500};
    const static vector<double> eta_vals_20 = {0.653, 0.695, 0.735, 0.714, 0.688, 0.635,
                                               0.625, 0.655, 0.680, 0.691, 0.674};

    const static vector<double> eta_edges_25 = {0.000, 0.077, 0.362, 0.719, 0.992, 1.300,
                                                1.479, 1.692, 1.942, 2.227, 2.464, 2.500};
    const static vector<double> eta_vals_25 = {0.692, 0.732, 0.768, 0.750, 0.726, 0.677,
                                               0.667, 0.692, 0.710, 0.706, 0.679};

    const static vector<double> eta_edges_30 = {0.000, 0.053, 0.362, 0.719, 1.004, 1.277,
                                                1.467, 1.681, 1.954, 2.239, 2.452, 2.500};
    const static vector<double> eta_vals_30 = {0.724, 0.763, 0.804, 0.789, 0.762, 0.702,
                                               0.690, 0.720, 0.731, 0.714, 0.681};

    const static vector<double> eta_edges_35 = {0.000, 0.044, 0.342, 0.711, 0.971, 1.280,
                                                1.456, 1.683, 1.944, 2.218, 2.442, 2.500};
    const static vector<double> eta_vals_35 = {0.736, 0.778, 0.824, 0.811, 0.784, 0.730,
                                               0.718, 0.739, 0.743, 0.718, 0.678};

    const static vector<double> eta_edges_40 = {0.000, 0.047, 0.355, 0.699, 0.983, 1.268,
                                                1.457, 1.671, 1.931, 2.204, 2.453, 2.500};
    const static vector<double> eta_vals_40 = {0.741, 0.774, 0.823, 0.823, 0.802, 0.764,
                                               0.756, 0.771, 0.771, 0.734, 0.684};

    const static vector<double> eta_edges_45 = {0.000, 0.056, 0.354, 0.711, 0.984, 1.280,
                                                1.458, 1.684, 1.945, 2.207, 2.442, 2.500};
    const static vector<double> eta_vals_45 = {0.758, 0.792, 0.841, 0.841, 0.823, 0.792,
                                               0.786, 0.796, 0.794, 0.734, 0.663};

    const static vector<double> eta_edges_50 = {0.000, 0.059, 0.355, 0.699, 0.983, 1.268,
                                                1.446, 1.682, 1.943, 2.216, 2.453, 2.500};
    const static vector<double> eta_vals_50 = {0.771, 0.806, 0.855, 0.858, 0.843, 0.810,
                                               0.800, 0.808, 0.802, 0.730, 0.653};

    const static vector<double> eta_edges_60 = {0.000, 0.050, 0.350, 0.707, 0.981, 1.278,
                                                1.468, 1.694, 1.944, 2.242, 2.453, 2.500};
    const static vector<double> eta_vals_60 = {0.773, 0.816, 0.866, 0.865, 0.853, 0.820,
                                               0.812, 0.817, 0.804, 0.726, 0.645};

    const static vector<double> eta_edges_80 = {0.000, 0.051, 0.374, 0.720, 0.981, 1.279,
                                                1.468, 1.707, 1.945, 2.207, 2.457, 2.500};
    const static vector<double> eta_vals_80 = {0.819, 0.855, 0.899, 0.906, 0.900, 0.869,
                                               0.865, 0.873, 0.869, 0.868, 0.859};

    const static vector<double> et_edges = {10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 80};
    const static vector<vector<double>> et_eta_edges = {eta_edges_10, eta_edges_15, eta_edges_20,
                                                        eta_edges_25, eta_edges_30, eta_edges_35,
                                                        eta_edges_40, eta_edges_45, eta_edges_50,
                                                        eta_edges_60, eta_edges_80};
    const static vector<vector<double>> et_eta_vals = {eta_vals_10, eta_vals_15, eta_vals_20, eta_vals_25,
                                                       eta_vals_30, eta_vals_35, eta_vals_40, eta_vals_45,
                                                       eta_vals_50, eta_vals_60, eta_vals_80};

    if (e.abseta() > 2.5 || e.Et() < 10 * GeV) return 0.0;
    const int i_et = binIndex(e.Et() / GeV, et_edges, true);
    const int i_eta = binIndex(e.abseta(), et_eta_edges[i_et]);
    return et_eta_vals[i_et][i_eta] * ELECTRON_RECOEFF_ATLAS_RUN1(e);
  }

  /// @brief ATLAS Run 2 'tight' electron reco+identification efficiency
  ///
  /// ~1% increase over Run 1 informed by Fig 1 in https://cds.cern.ch/record/2157687/files/ATLAS-CONF-2016-024.pdf
  inline double ELECTRON_EFF_ATLAS_RUN2_TIGHT(const Particle& e) {
    if (e.abspid() != PID::ELECTRON) return 0;
    const static vector<double> et_edges = {/* 10, 15, */ 20, 25, 30, 35, 40, 45, 50, 60, 80};
    const static vector<double> et_effs = {
        0.785, 0.805, 0.820, 0.830, 0.840,
        0.850, 0.875, 0.910, 0.910}; //Extra value extrapolated for overflow
    const static vector<double> eta_edges = {0.000, 0.051, 0.374, 0.720, 0.981, 1.279,
                                             1.468, 1.707, 1.945, 2.207, 2.457, 2.500}; // from ET > 80 bin
    const static vector<double> eta_refs = {0.819, 0.855, 0.899, 0.906, 0.900, 0.869,
                                            0.865, 0.873, 0.869, 0.868, 0.859};
    if (e.abseta() > 2.5 || e.Et() < 20 * GeV) return 0.0;
    const int i_et = binIndex(e.Et() / GeV, et_edges, true);
    const int i_eta = binIndex(e.abseta(), eta_edges);
    const double eff_et = et_effs[i_et]; //< integral eff
    // Scale to |eta| shape, following the ~85% efficient high-ET bin from Run 1
    const double eff = eff_et * (eta_refs[i_eta] / 0.85) * ELECTRON_RECOEFF_ATLAS_RUN2(e);
    //return ELECTRON_IDEFF_ATLAS_RUN1_TIGHT(e);
    return eff;
  }


  /// ATLAS Run 1 electron reco smearing
  inline Particle ELECTRON_SMEAR_ATLAS_RUN1(const Particle& e) {
    static const vector<double> edges_eta = {0., 2.5, 3.};
    static const vector<double> edges_pt = {0., 0.1, 25.};
    static const vector<double> e2s = {0.000, 0.015, 0.005, 0.005, 0.005, 0.005, 0.107, 0.107, 0.107};
    static const vector<double> es = {0.00, 0.00, 0.05, 0.05, 0.05, 0.05, 2.08, 2.08, 2.08};
    static const vector<double> cs = {0.00, 0.00, 0.25, 0.25, 0.25, 0.25, 0.00, 0.00, 0.00};

    const int i_eta = binIndex(e.abseta(), edges_eta, true);
    const int i_pt = binIndex(e.pT() / GeV, edges_pt, true);
    const int i = i_eta * edges_pt.size() + i_pt;

    // Calculate absolute resolution in GeV
    const double c1 = sqr(e2s[i]), c2 = sqr(es[i]), c3 = sqr(cs[i]);
    const double resolution = sqrt(c1 * e.E2() + c2 * e.E() + c3) * GeV;

    // normal_distribution<> d(e.E(), resolution);
    // const double mass = e.mass2() > 0 ? e.mass() : 0; //< numerical carefulness...
    // const double smeared_E = max(d(gen), mass); //< can't let the energy go below the mass!
    // return Particle(e.pid(), FourMomentum::mkEtaPhiME(e.eta(), e.phi(), mass, smeared_E));
    return Particle(e.pid(), P4_SMEAR_E_GAUSS(e, resolution));
  }


  /// ATLAS Run 2 electron reco smearing
  ///
  /// @todo Currently just a copy of the Run 1 version: fix!
  inline Particle ELECTRON_SMEAR_ATLAS_RUN2(const Particle& e) {
    return ELECTRON_SMEAR_ATLAS_RUN1(e);
  }


  /// @todo Add charge flip efficiency?


  /// CMS Run 1 electron reconstruction efficiency
  inline double ELECTRON_EFF_CMS_RUN1(const Particle& e) {
    if (e.abspid() != PID::ELECTRON) return 0;
    if (e.abseta() > 2.5) return 0;
    if (e.pT() < 10 * GeV) return 0;
    return (e.abseta() < 1.5) ? 0.95 : 0.85;
  }
  /// CMS Run 1 loose electron reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double ELECTRON_EFF_CMS_RUN1_LOOSE(const Particle& e) {
    return ELECTRON_EFF_CMS_RUN1(e);
  }
  /// CMS Run 1 medium electron reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double ELECTRON_EFF_CMS_RUN1_MEDIUM(const Particle& e) {
    return ELECTRON_EFF_CMS_RUN1(e);
  }
  /// CMS Run 1 tight electron reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double ELECTRON_EFF_CMS_RUN1_TIGHT(const Particle& e) {
    return ELECTRON_EFF_CMS_RUN1(e);
  }


  /// CMS Run 2 electron reco efficiency
  ///
  /// @todo Currently just a copy of Run 1: fix!
  inline double ELECTRON_EFF_CMS_RUN2(const Particle& e) {
    if (e.abspid() != PID::ELECTRON) return 0;
    return ELECTRON_EFF_CMS_RUN1(e);
  }
  /// CMS Run 2 loose electron reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double ELECTRON_EFF_CMS_RUN2_LOOSE(const Particle& e) {
    return ELECTRON_EFF_CMS_RUN2(e);
  }
  /// CMS Run 2 medium electron reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double ELECTRON_EFF_CMS_RUN2_MEDIUM(const Particle& e) {
    return ELECTRON_EFF_CMS_RUN2(e);
  }
  /// CMS Run 2 tight electron reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double ELECTRON_EFF_CMS_RUN2_TIGHT(const Particle& e) {
    return ELECTRON_EFF_CMS_RUN2(e);
  }


  /// @brief CMS electron energy smearing, preserving direction
  ///
  /// Calculate resolution
  /// for pT > 0.1 GeV, E resolution = |eta| < 0.5 -> sqrt(0.06^2 + pt^2 * 1.3e-3^2)
  ///                                  |eta| < 1.5 -> sqrt(0.10^2 + pt^2 * 1.7e-3^2)
  ///                                  |eta| < 2.5 -> sqrt(0.25^2 + pt^2 * 3.1e-3^2)
  inline Particle ELECTRON_SMEAR_CMS_RUN1(const Particle& e) {
    // Calculate absolute resolution in GeV from functional form
    double resolution = 0;
    const double abseta = e.abseta();
    if (e.pT() > 0.1 * GeV && abseta < 2.5) { //< should be a given from efficiencies
      if (abseta < 0.5) {
        resolution = add_quad(0.06, 1.3e-3 * e.pT() / GeV) * GeV;
      }
      else if (abseta < 1.5) {
        resolution = add_quad(0.10, 1.7e-3 * e.pT() / GeV) * GeV;
      }
      else { // still |eta| < 2.5
        resolution = add_quad(0.25, 3.1e-3 * e.pT() / GeV) * GeV;
      }
    }

    // normal_distribution<> d(e.E(), resolution);
    // const double mass = e.mass2() > 0 ? e.mass() : 0; //< numerical carefulness...
    // const double smeared_E = max(d(gen), mass); //< can't let the energy go below the mass!
    // return Particle(e.pid(), FourMomentum::mkEtaPhiME(e.eta(), e.phi(), mass, smeared_E));
    return Particle(e.pid(), P4_SMEAR_E_GAUSS(e, resolution));
  }

  /// CMS Run 2 electron reco smearing
  ///
  /// @todo Currently just a copy of the Run 1 version: fix!
  inline Particle ELECTRON_SMEAR_CMS_RUN2(const Particle& e) {
    return ELECTRON_SMEAR_CMS_RUN1(e);
  }

  /// @}


  /// @defgroup smearing_photon Experiment-specific photon efficiency and smearing functions
  /// @{

  /// @brief ATLAS Run 2 photon reco efficiency
  ///
  /// Taken from converted photons, Fig 8, in arXiv:1606.01813
  inline double PHOTON_EFF_ATLAS_RUN1(const Particle& y) {
    if (y.abspid() != PID::PHOTON) return 0; ///< @todo Allow electron misID? What about jet misID?

    if (y.pT() < 10 * GeV) return 0;
    if (inRange(y.abseta(), 1.37, 1.52) || y.abseta() > 2.37) return 0;

    static const vector<double> edges_eta = {0., 0.6, 1.37, 1.52, 1.81, 2.37};
    static const vector<double> edges_pt = {10., 15., 20., 25.,  30.,  35.,  40.,  45.,
                                            50., 60., 80., 100., 125., 150., 175., 250.};
    static const vector<double> effs = {
        0.53, 0.65, 0.73, 0.83, 0.86, 0.93, 0.94, 0.96, 0.97, 0.98, 0.98, 0.98, 0.98, 0.98, 0.98, 0.98, //
        0.45, 0.57, 0.67, 0.74, 0.84, 0.87, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98, 0.98, 0.99, 0.99, 0.99, //
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, //
        0.48, 0.56, 0.68, 0.76, 0.86, 0.90, 0.93, 0.95, 0.96, 0.97, 0.98, 0.99, 0.99, 1.00, 1.00, 1.00, //
        0.50, 0.61, 0.74, 0.82, 0.88, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.98, 0.98, 0.98, 0.99, 0.99};

    const int i_eta = binIndex(y.abseta(), edges_eta);
    const int i_pt = binIndex(y.pT() / GeV, edges_pt, true);
    const int i = i_eta * edges_pt.size() + i_pt;
    const double eff = effs[i];
    return eff;
  }
  /// ATLAS Run 1 loose photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_ATLAS_RUN1_LOOSE(const Particle& y) {
    return PHOTON_EFF_ATLAS_RUN1(y);
  }
  /// ATLAS Run 1 medium photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_ATLAS_RUN1_MEDIUM(const Particle& y) {
    return PHOTON_EFF_ATLAS_RUN1(y);
  }
  /// ATLAS Run 1 tight photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_ATLAS_RUN1_TIGHT(const Particle& y) {
    return PHOTON_EFF_ATLAS_RUN1(y);
  }


  /// @brief ATLAS Run 2 photon reco efficiency
  ///
  /// Taken from converted photons, Fig 6, in ATL-PHYS-PUB-2016-014
  inline double PHOTON_EFF_ATLAS_RUN2(const Particle& y) {
    if (y.abspid() != PID::PHOTON) return 0; ///< @todo Allow electron misID? What about jet misID?

    if (y.pT() < 10 * GeV) return 0;
    if (inRange(y.abseta(), 1.37, 1.52) || y.abseta() > 2.37) return 0;

    static const vector<double> edges_eta = {0., 0.6, 1.37, 1.52, 1.81, 2.37};
    static const vector<double> edges_pt = {10., 15., 20., 25.,  30.,  35.,  40.,  45.,
                                            50., 60., 80., 100., 125., 150., 175., 250.};
    static const vector<double> effs = {
        0.55, 0.70, 0.85, 0.89, 0.93, 0.95, 0.96, 0.96, 0.97, 0.97, 0.98, 0.97, 0.97, 0.97, 0.97, 0.97, //
        0.47, 0.66, 0.79, 0.86, 0.89, 0.94, 0.96, 0.97, 0.97, 0.98, 0.97, 0.98, 0.98, 0.98, 0.98, 0.98, //
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, //
        0.54, 0.71, 0.84, 0.88, 0.92, 0.93, 0.94, 0.95, 0.96, 0.96, 0.96, 0.96, 0.96, 0.96, 0.96, 0.96, //
        0.61, 0.74, 0.83, 0.88, 0.91, 0.94, 0.95, 0.96, 0.97, 0.98, 0.98, 0.98, 0.98, 0.98, 0.98, 0.98};

    const int i_eta = binIndex(y.abseta(), edges_eta);
    const int i_pt = binIndex(y.pT() / GeV, edges_pt, true);
    const int i = i_eta * edges_pt.size() + i_pt;
    const double eff = effs[i];
    return eff;
  }
  /// ATLAS Run 2 loose photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_ATLAS_RUN2_LOOSE(const Particle& y) {
    return PHOTON_EFF_ATLAS_RUN2(y);
  }
  /// ATLAS Run 2 medium photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_ATLAS_RUN2_MEDIUM(const Particle& y) {
    return PHOTON_EFF_ATLAS_RUN2(y);
  }
  /// ATLAS Run 2 tight photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_ATLAS_RUN2_TIGHT(const Particle& y) {
    return PHOTON_EFF_ATLAS_RUN2(y);
  }


  /// CMS Run 1 photon reco efficiency
  ///
  /// @todo Currently from Delphes
  inline double PHOTON_EFF_CMS_RUN1(const Particle& y) {
    if (y.abspid() != PID::PHOTON) return 0; ///< @todo Allow electron misID? What about jet misID?
    if (y.pT() < 10 * GeV || y.abseta() > 2.5) return 0;
    return (y.abseta() < 1.5) ? 0.95 : 0.85;
  }
  /// CMS Run 1 loose photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_CMS_RUN1_LOOSE(const Particle& y) {
    return PHOTON_EFF_CMS_RUN1(y);
  }
  /// CMS Run 1 medium photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_CMS_RUN1_MEDIUM(const Particle& y) {
    return PHOTON_EFF_CMS_RUN1(y);
  }
  /// CMS Run 1 tight photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_CMS_RUN1_TIGHT(const Particle& y) {
    return PHOTON_EFF_CMS_RUN1(y);
  }


  /// CMS Run 2 photon reco efficiency
  ///
  /// @todo Currently just a copy of Run 1: fix!
  inline double PHOTON_EFF_CMS_RUN2(const Particle& y) {
    if (y.abspid() != PID::PHOTON) return 0; ///< @todo Allow electron misID? What about jet misID?
    return PHOTON_EFF_CMS_RUN1(y);
  }
  /// CMS Run 2 loose photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_CMS_RUN2_LOOSE(const Particle& y) {
    return PHOTON_EFF_CMS_RUN2(y);
  }
  /// CMS Run 2 medium photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_CMS_RUN2_MEDIUM(const Particle& y) {
    return PHOTON_EFF_CMS_RUN2(y);
  }
  /// CMS Run 2 tight photon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double PHOTON_EFF_CMS_RUN2_TIGHT(const Particle& y) {
    return PHOTON_EFF_CMS_RUN2(y);
  }


  /// @todo Use real photon smearing
  inline Particle PHOTON_SMEAR_ATLAS_RUN1(const Particle& y) {
    return y;
  }
  inline Particle PHOTON_SMEAR_ATLAS_RUN2(const Particle& y) {
    return y;
  }
  inline Particle PHOTON_SMEAR_CMS_RUN1(const Particle& y) {
    return y;
  }
  inline Particle PHOTON_SMEAR_CMS_RUN2(const Particle& y) {
    return y;
  }

  /// @}


  /// @defgroup smearing_muon Experiment-specific muon efficiency and smearing functions
  /// @{

  /// ATLAS Run 1 muon reco efficiency
  inline double MUON_EFF_ATLAS_RUN1(const Particle& m) {
    if (m.abspid() != PID::MUON) return 0;
    if (m.abseta() > 2.7) return 0;
    if (m.pT() < 10 * GeV) return 0;
    return (m.abseta() < 1.5) ? 0.95 : 0.85;
  }
  /// ATLAS Run 1 loose muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double MUON_EFF_ATLAS_RUN1_LOOSE(const Particle& m) {
    return MUON_EFF_ATLAS_RUN1(m);
  }
  /// ATLAS Run 1 medium muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double MUON_EFF_ATLAS_RUN1_MEDIUM(const Particle& m) {
    return MUON_EFF_ATLAS_RUN1(m);
  }
  /// ATLAS Run 1 tight muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double MUON_EFF_ATLAS_RUN1_TIGHT(const Particle& m) {
    return MUON_EFF_ATLAS_RUN1(m);
  }


  /// ATLAS Run 2 muon reco efficiency
  ///
  /// From https://arxiv.org/pdf/1603.05598.pdf , Fig3 top
  inline double MUON_RECOEFF_ATLAS_RUN2(const Particle& m) {
    if (m.abspid() != PID::MUON) return 0;
    if (m.abseta() > 2.5) return 0;
    if (m.abseta() < 0.1) return 0.61;
    // if (m.pT() < 10*GeV) return 0;
    return (m.abseta() < 1) ? 0.98 : 0.99;
  }


  /// @brief ATLAS Run 2 muon isolation efficiency
  ///
  /// For loose ID, from 21 of https://arxiv.org/pdf/2012.00578
  inline double MUON_ISOEFF_ATLAS_RUN2_LOOSE(const Particle& m) {
    if (m.abspid() != PID::MUON) return 0;
    static const vector<double> edges_pt = {0., 3., 4., 5., 6., 7., 8., 9., 10., 15., 20., 30., 40.};
    static const vector<double> effs_pt = {0.,   0.58, 0.70, 0.75, 0.80, 0.82, 0.85,
                                           0.87, 0.90, 0.95, 0.98, 1.00, 1.00};
    const int i_pt = binIndex(m.pT() / GeV, edges_pt, true);
    const double eff_pt = effs_pt[i_pt];
    return eff_pt;
  }


  /// @brief ATLAS Run 2 muon reco+ID efficiency
  ///
  /// For loose ID, from Fig 12 of https://arxiv.org/pdf/2012.00578
  inline double MUON_EFF_ATLAS_RUN2_LOOSE(const Particle& m) {
    if (m.abspid() != PID::MUON) return 0;
    if (m.abseta() > 2.5) return 0;
    static const vector<double> edges_pt = {0., 3.5, 4., 5., 6., 7., 8., 10.};
    static const vector<double> effs = {0.00, 0.88, 0.92, 0.97, 0.98, 0.98, 0.98, 0.99};
    const int i_pt = binIndex(m.pT() / GeV, edges_pt, true);
    const double eff = effs[i_pt];
    // no eta dependence
    return eff * MUON_ISOEFF_ATLAS_RUN2_LOOSE(m);
  }


  /// @brief ATLAS Run 2 muon reco+ID efficiency
  ///
  /// For medium ID, from Fig 12+13 of https://arxiv.org/pdf/2012.00578
  inline double MUON_EFF_ATLAS_RUN2_MEDIUM(const Particle& m) {
    if (m.abspid() != PID::MUON) return 0;
    if (m.abseta() > 2.5) return 0;
    static const vector<double> edges_pt = {0.,  3.5, 4.,  5.,  6.,  7.,  8.,  9.,  10., 12.,
                                            14., 16., 18., 20., 25., 30., 35., 40., 45., 50.};
    static const vector<double> effs_pt = {0.00, 0.48, 0.62, 0.82, 0.94, 0.95, 0.96, 0.96, 0.97, 0.97,
                                           0.97, 0.97, 0.97, 0.98, 0.98, 0.98, 0.98, 0.98, 0.98, 0.98};
    const int i_pt = binIndex(m.pT() / GeV, edges_pt, true);
    const double eff_pt = effs_pt[i_pt];
    static const vector<double> edges_eta = {0., 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50};
    static const vector<double> effs_eta = {0.85, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99};
    const int i_eta = binIndex(m.abseta(), edges_eta, true);
    const double eff_eta = effs_eta[i_eta] / 0.99; //< norm factor as approximate double differential
    return eff_pt * eff_eta * MUON_ISOEFF_ATLAS_RUN2_LOOSE(m);
  }


  /// @brief ATLAS Run 2 muon reco+ID efficiency
  ///
  /// For tight ID, from Fig 12 of https://arxiv.org/pdf/2012.00578
  inline double MUON_EFF_ATLAS_RUN2_TIGHT(const Particle& m) {
    if (m.abspid() != PID::MUON) return 0;
    if (m.abseta() > 2.5) return 0;
    static const vector<double> edges_pt = {0., 3.5, 4., 5., 6., 7., 8., 9., 10., 12., 14., 16., 18., 20.};
    static const vector<double> effs_pt = {0.00, 0.00, 0.68, 0.81, 0.85, 0.88, 0.89,
                                           0.90, 0.91, 0.92, 0.92, 0.92, 0.93, 0.93};
    const int i_pt = binIndex(m.pT() / GeV, edges_pt, true);
    const double eff_pt = effs_pt[i_pt];
    static const vector<double> edges_eta = {0., 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50};
    static const vector<double> effs_eta = {0.78, 0.94, 0.96, 0.96, 0.96, 0.96, 0.96, 0.96, 0.96, 0.96, 0.96};
    const int i_eta = binIndex(m.abseta(), edges_eta, true);
    const double eff_eta = effs_eta[i_eta] / 0.96; //< norm factor as approximate double differential
    return eff_pt * eff_eta * MUON_ISOEFF_ATLAS_RUN2_LOOSE(m);
  }


  /// ATLAS Run 1 muon reco smearing
  ///
  /// Based on Delphes R1 resolution, augmented with high-pT scaling
  /// based on https://arxiv.org/pdf/2012.00578 Fig 2 .
  inline Particle MUON_SMEAR_ATLAS_RUN1(const Particle& m) {
    static const vector<double> edges_eta = {0, 1.5, 2.5};
    static const vector<double> edges_pt = {0, 0.1, 1.0, 10., 200.};
    static const vector<double> res = {0., 0.03, 0.02, 0.03, 0.05, 0., 0.04, 0.03, 0.04, 0.05};

    const int i_eta = binIndex(m.abseta(), edges_eta);
    const int i_pt = binIndex(m.pT() / GeV, edges_pt, true);
    const int i = i_eta * edges_pt.size() + i_pt;
    const double resolution_fixed = res[i];

    // For pT > 200 GeV, add an ad-hoc linear scaling to follow the trend of
    // https://arxiv.org/pdf/2012.00578 Fig 2 but without the high-pT working point,
    // slightly generously hitting 45% rather than 66% at 2500 GeV.
    const double resolution = resolution_fixed
        * (1.0 + max(0.0, (((0.45 - 0.05) / 0.05 - 1.0) / 2300) * (m.pT() - 200 * GeV) / GeV));

    // Smear by a Gaussian centered on the current pT, with width given by the resolution
    // normal_distribution<> d(m.pT(), resolution*m.pT());
    // const double smeared_pt = max(d(gen), 0.);
    // const double mass = m.mass2() > 0 ? m.mass() : 0; //< numerical carefulness...
    // return Particle(m.pid(), FourMomentum::mkEtaPhiMPt(m.eta(), m.phi(), mass, smeared_pt));
    return Particle(m.pid(), P4_SMEAR_PT_GAUSS(m, resolution * m.pT()));
  }

  /// ATLAS Run 2 muon reco smearing
  ///
  /// From https://arxiv.org/abs/1603.05598 , eq (10) and Fig 12 and
  /// the later https://arxiv.org/pdf/2012.00578 Fig 2 -- we assume
  /// that the high-pT working point is being used, and match the 300
  /// GeV resolution there to the earlier paper's form.
  inline Particle MUON_SMEAR_ATLAS_RUN2(const Particle& m) {
    // Low-pT res limit:
    double mres_pt = 0.015;
    // Hit sig_mm / m_mm ~ 0.025 at 100 GeV cf. Fig 12:
    if (m.pT() > 50 * GeV) mres_pt = 0.015 + 0.01 * (m.pT() - 50 * GeV) / (50 * GeV);
    // Hit sig(q/p) = 32% / sqrt(2) at pT = 2500 cf. Fig 2, degrade linearly:
    if (m.pT() > 100 * GeV) mres_pt = 0.025 + 0.0084 * (m.pT() - 100 * GeV) / (100 * GeV);
    const double ptres_pt = SQRT2 * mres_pt; //< from Eq (10)
    const double resolution = (m.abseta() < 1.5 ? 1.0 : 1.25) * ptres_pt;
    return Particle(m.pid(), P4_SMEAR_PT_GAUSS(m, resolution * m.pT()));
  }

  /// CMS Run 1 muon reco efficiency
  inline double MUON_EFF_CMS_RUN1(const Particle& m) {
    if (m.abspid() != PID::MUON) return 0;
    if (m.abseta() > 2.4) return 0;
    if (m.pT() < 10 * GeV) return 0;
    return 0.95 * (m.abseta() < 1.5 ? 1 : exp(0.5 - 5e-4 * m.pT() / GeV));
  }
  /// CMS Run 1 loose muon reconstruction efficiency
  /// @todo Add muon loose/medium/tight ID efficiencies? All around 95-98%... ignore?
  /// @todo Just an alias to generic: improve!
  inline double MUON_EFF_CMS_RUN1_LOOSE(const Particle& m) {
    return MUON_EFF_CMS_RUN1(m);
  }
  /// CMS Run 1 medium muon reconstruction efficiency
  /// @todo Add muon loose/medium/tight ID efficiencies? All around 95-98%... ignore?
  /// @todo Just an alias to generic: improve!
  inline double MUON_EFF_CMS_RUN1_MEDIUM(const Particle& m) {
    return MUON_EFF_CMS_RUN1(m);
  }
  /// CMS Run 1 tight muon reconstruction efficiency
  /// @todo Add muon loose/medium/tight ID efficiencies? All around 95-98%... ignore?
  /// @todo Just an alias to generic: improve!
  inline double MUON_EFF_CMS_RUN1_TIGHT(const Particle& m) {
    return MUON_EFF_CMS_RUN1(m);
  }


  /// CMS Run 2 muon reco efficiency
  ///
  /// @todo Currently just a copy of Run 1: fix!
  inline double MUON_EFF_CMS_RUN2(const Particle& m) {
    return MUON_EFF_CMS_RUN1(m);
  }
  /// CMS Run 2 loose muon reconstruction efficiency
  /// @todo Add muon loose/medium/tight ID efficiencies? All around 95-98%... ignore?
  /// @todo Just an alias to generic: improve!
  inline double MUON_EFF_CMS_RUN2_LOOSE(const Particle& m) {
    return MUON_EFF_CMS_RUN2(m);
  }
  /// CMS Run 2 medium muon reconstruction efficiency
  /// @todo Add muon loose/medium/tight ID efficiencies? All around 95-98%... ignore?
  /// @todo Just an alias to generic: improve!
  inline double MUON_EFF_CMS_RUN2_MEDIUM(const Particle& m) {
    return MUON_EFF_CMS_RUN2(m);
  }
  /// CMS Run 2 tight muon reconstruction efficiency
  /// @todo Add muon loose/medium/tight ID efficiencies? All around 95-98%... ignore?
  /// @todo Just an alias to generic: improve!
  inline double MUON_EFF_CMS_RUN2_TIGHT(const Particle& m) {
    return MUON_EFF_CMS_RUN2(m);
  }


  /// CMS Run 1 muon reco smearing
  inline Particle MUON_SMEAR_CMS_RUN1(const Particle& m) {
    // Calculate fractional resolution
    // for pT > 0.1 GeV, mom resolution = |eta| < 0.5 -> sqrt(0.01^2 + pt^2 * 2.0e-4^2)
    //                                    |eta| < 1.5 -> sqrt(0.02^2 + pt^2 * 3.0e-4^2)
    //                                    |eta| < 2.5 -> sqrt(0.05^2 + pt^2 * 2.6e-4^2)
    double resolution = 0;
    const double abseta = m.abseta();
    if (m.pT() > 0.1 * GeV && abseta < 2.5) {
      if (abseta < 0.5) {
        resolution = add_quad(0.01, 2.0e-4 * m.pT() / GeV);
      }
      else if (abseta < 1.5) {
        resolution = add_quad(0.02, 3.0e-4 * m.pT() / GeV);
      }
      else { // still |eta| < 2.5... but isn't CMS' mu acceptance < 2.4?
        resolution = add_quad(0.05, 2.6e-4 * m.pT() / GeV);
      }
    }

    // Smear by a Gaussian centered on the current pT, with width given by the resolution
    // normal_distribution<> d(m.pT(), resolution*m.pT());
    // const double smeared_pt = max(d(gen), 0.);
    // const double mass = m.mass2() > 0 ? m.mass() : 0; //< numerical carefulness...
    // return Particle(m.pid(), FourMomentum::mkEtaPhiMPt(m.eta(), m.phi(), mass, smeared_pt));
    return Particle(m.pid(), P4_SMEAR_PT_GAUSS(m, resolution * m.pT()));
  }

  /// CMS Run 2 muon reco smearing
  ///
  /// @todo Currently just a copy of the Run 1 version: fix!
  inline Particle MUON_SMEAR_CMS_RUN2(const Particle& m) {
    return MUON_SMEAR_CMS_RUN1(m);
  }

  /// @}


  /// @defgroup smearing_tau Experiment-specific tau efficiency and smearing functions
  /// @{

  /// @brief ATLAS Run 1 8 TeV tau efficiencies (medium working point)
  ///
  /// Taken from http://arxiv.org/pdf/1412.7086.pdf
  ///   20-40 GeV 1-prong LMT eff|mis = 0.66|1/10, 0.56|1/20, 0.36|1/80
  ///   20-40 GeV 3-prong LMT eff|mis = 0.45|1/60, 0.38|1/100, 0.27|1/300
  ///   > 40 GeV 1-prong LMT eff|mis = 0.66|1/15, 0.56|1/25, 0.36|1/80
  ///   > 40 GeV 3-prong LMT eff|mis = 0.45|1/250, 0.38|1/400, 0.27|1/1300
  inline double TAU_EFF_ATLAS_RUN1_MEDIUM(const Particle& t) {
    if (t.abseta() > 2.5) return 0;                //< hmm... mostly
    if (inRange(t.abseta(), 1.37, 1.52)) return 0; //< crack region
    double pThadvis = 0;
    Particles chargedhadrons;
    for (const Particle& p : t.children()) {
      if (p.isHadron()) {
        pThadvis += p.pT(); //< right definition? Paper is unclear
        if (p.charge3() != 0 && p.abseta() < 2.5 && p.pT() > 1 * GeV) chargedhadrons += p;
      }
    }
    if (chargedhadrons.empty()) return 0; //< leptonic tau
    if (pThadvis < 20 * GeV) return 0;    //< below threshold
    if (pThadvis < 40 * GeV) {
      if (chargedhadrons.size() == 1) return (t.abspid() == PID::TAU) ? 0.56 : 0; //1/20.;
      if (chargedhadrons.size() == 3) return (t.abspid() == PID::TAU) ? 0.38 : 0; //1/100.;
    }
    else {
      if (chargedhadrons.size() == 1) return (t.abspid() == PID::TAU) ? 0.56 : 0; //1/25.;
      if (chargedhadrons.size() == 3) return (t.abspid() == PID::TAU) ? 0.38 : 0; //1/400.;
    }
    return 0;
  }
  /// ATLAS Run 1 medium muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_ATLAS_RUN1(const Particle& t) {
    return TAU_EFF_ATLAS_RUN1_MEDIUM(t);
  }
  /// ATLAS Run 1 loose tau reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_ATLAS_RUN1_LOOSE(const Particle& t) {
    return TAU_EFF_ATLAS_RUN1(t);
  }
  /// ATLAS Run 1 tight muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_ATLAS_RUN1_TIGHT(const Particle& t) {
    return TAU_EFF_ATLAS_RUN1(t);
  }


  /// @brief ATLAS Run 1 8 TeV tau misID rates (medium working point)
  ///
  /// Taken from http://arxiv.org/pdf/1412.7086.pdf
  ///   20-40 GeV 1-prong LMT eff|mis = 0.66|1/10, 0.56|1/20, 0.36|1/80
  ///   20-40 GeV 3-prong LMT eff|mis = 0.45|1/60, 0.38|1/100, 0.27|1/300
  ///   > 40 GeV 1-prong LMT eff|mis = 0.66|1/15, 0.56|1/25, 0.36|1/80
  ///   > 40 GeV 3-prong LMT eff|mis = 0.45|1/250, 0.38|1/400, 0.27|1/1300
  inline double TAUJET_EFF_ATLAS_RUN1(const Jet& j) {
    if (j.abseta() > 2.5) return 0;                //< hmm... mostly
    if (inRange(j.abseta(), 1.37, 1.52)) return 0; //< crack region
    double pThadvis = 0;
    Particles chargedhadrons;
    for (const Particle& p : j.particles()) {
      if (p.isHadron()) {
        pThadvis += p.pT(); //< right definition? Paper is unclear
        if (p.charge3() != 0 && p.abseta() < 2.5 && p.pT() > 1 * GeV) chargedhadrons += p;
      }
    }

    if (chargedhadrons.empty()) return 0; //< leptonic tau?
    if (pThadvis < 20 * GeV) return 0;    //< below threshold

    const Particles ttags = j.tauTags(Cuts::pT > 10 * GeV);
    // MisID rates for jets without truth tau label
    if (ttags.empty()) {
      if (pThadvis < 40 * GeV)
        return chargedhadrons.size() == 1 ? 1 / 20.
            : chargedhadrons.size() == 3  ? 1 / 100.
                                          : 0; //< fake rates
      else
        return chargedhadrons.size() == 1 ? 1 / 25.
            : chargedhadrons.size() == 3  ? 1 / 400.
                                          : 0; //< fake rates
    }
    // Efficiencies for jets with a truth tau label
    const Particles prongs = ttags[0].stableDescendants(Cuts::charge3 > 0 && Cuts::pT > 1 * GeV
                                                        && Cuts::abseta < 2.5);
    return prongs.size() == 1 ? 0.56 : 0.38;
  }


  /// @brief ATLAS Run 2 13 TeV tau efficiencies (medium working point)
  ///
  /// From https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PUBNOTES/ATL-PHYS-PUB-2015-045/ATL-PHYS-PUB-2015-045.pdf
  ///   LMT 1 prong efficiency/mistag = 0.6|1/30, 0.55|1/50, 0.45|1/120
  ///   LMT 3 prong efficiency/mistag = 0.5|1/30, 0.4|1/110, 0.3|1/300
  inline double TAU_EFF_ATLAS_RUN2_MEDIUM(const Particle& t) {
    if (t.abspid() != PID::TAU) return 0;
    if (t.abseta() > 2.5) return 0;                //< hmm... mostly
    if (inRange(t.abseta(), 1.37, 1.52)) return 0; //< crack region
    double pThadvis = 0;
    Particles chargedhadrons;
    for (const Particle& p : t.children()) {
      if (p.isHadron()) {
        pThadvis += p.pT(); //< right definition? Paper is unclear
        if (p.charge3() != 0 && p.abseta() < 2.5 && p.pT() > 1 * GeV) chargedhadrons += p;
      }
    }
    if (chargedhadrons.empty()) return 0;                                       //< leptonic tau
    if (pThadvis < 20 * GeV) return 0;                                          //< below threshold
    if (chargedhadrons.size() == 1) return (t.abspid() == PID::TAU) ? 0.55 : 0; //1/50.;
    if (chargedhadrons.size() == 3) return (t.abspid() == PID::TAU) ? 0.40 : 0; //1/110.;
    return 0;
  }
  /// ATLAS Run 2 medium muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_ATLAS_RUN2(const Particle& t) {
    return TAU_EFF_ATLAS_RUN2_MEDIUM(t);
  }
  /// ATLAS Run 2 loose tau reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_ATLAS_RUN2_LOOSE(const Particle& t) {
    return TAU_EFF_ATLAS_RUN2(t);
  }
  /// ATLAS Run 2 tight muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_ATLAS_RUN2_TIGHT(const Particle& t) {
    return TAU_EFF_ATLAS_RUN2(t);
  }


  /// @brief ATLAS Run 2 13 TeV tau misID rate (medium working point)
  ///
  /// From https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PUBNOTES/ATL-PHYS-PUB-2015-045/ATL-PHYS-PUB-2015-045.pdf
  ///   LMT 1 prong efficiency/mistag = 0.6|1/30, 0.55|1/50, 0.45|1/120
  ///   LMT 3 prong efficiency/mistag = 0.5|1/30, 0.4|1/110, 0.3|1/300
  inline double TAUJET_EFF_ATLAS_RUN2(const Jet& j) {
    if (j.abseta() > 2.5) return 0;                //< hmm... mostly
    if (inRange(j.abseta(), 1.37, 1.52)) return 0; //< crack region
    double pThadvis = 0;
    Particles chargedhadrons;
    for (const Particle& p : j.particles()) {
      if (p.isHadron()) {
        pThadvis += p.pT(); //< right definition? Paper is unclear
        if (p.charge3() != 0 && p.abseta() < 2.5 && p.pT() > 1 * GeV) chargedhadrons += p;
      }
    }
    if (chargedhadrons.empty()) return 0;
    if (pThadvis < 20 * GeV) return 0; //< below threshold
    const Particles ttags = j.tauTags(Cuts::pT > 10 * GeV);
    // if (ttags.empty()) {
    //   if (pThadvis < 40*GeV)
    //     return chargedhadrons.size() == 1 ? 1/50. : 1/110.; //< fake rates
    //   else
    //     return chargedhadrons.size() == 1 ? 1/25. : 1/400.; //< fake rates
    // }
    if (ttags.empty())
      return chargedhadrons.size() == 1 ? 1 / 50. : chargedhadrons.size() == 3 ? 1 / 110. : 0; //< fake rates
    const Particles prongs = ttags[0].stableDescendants(Cuts::charge3 > 0 && Cuts::pT > 1 * GeV
                                                        && Cuts::abseta < 2.5);
    return prongs.size() == 1 ? 0.55 : 0.40;
  }


  /// ATLAS Run 1 tau smearing
  ///
  /// @todo Currently a copy of the jet smearing
  inline Particle TAU_SMEAR_ATLAS_RUN1(const Particle& t) {
    // // Const fractional resolution for now
    // static const double resolution = 0.03;

    // // Smear by a Gaussian centered on 1 with width given by the (fractional) resolution
    // /// @todo Is this the best way to smear? Should we preserve the energy, or pT, or direction?
    // const double fsmear = max(randnorm(1., resolution), 0.);
    // const double mass = t.mass2() > 0 ? t.mass() : 0; //< numerical carefulness...
    // return Particle(t.pid(), FourMomentum::mkXYZM(t.px()*fsmear, t.py()*fsmear, t.pz()*fsmear, mass));

    // Jet energy resolution lookup
    //   Implemented by Matthias Danninger for GAMBIT, based roughly on
    //   https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/CONFNOTES/ATLAS-CONF-2015-017/
    //   Parameterisation can be still improved, but eta dependence is minimal
    /// @todo Also need a JES uncertainty component?
    static const vector<double> binedges_pt = {0., 50., 70., 100., 150., 200., 1000., 10000.};
    static const vector<double> jer = {0.145, 0.115, 0.095, 0.075,
                                       0.07,  0.05,  0.04,  0.04}; //< note overflow value
    const int ipt = binIndex(t.pT() / GeV, binedges_pt, true);
    if (ipt < 0) return t;
    const double resolution = jer.at(ipt);

    // Smear by a Gaussian centered on 1 with width given by the (fractional) resolution
    /// @todo Is this the best way to smear? Should we preserve the energy, or pT, or direction?
    const double fsmear = max(randnorm(1., resolution), 0.);
    const double mass = t.mass2() > 0 ? t.mass() : 0; //< numerical carefulness...
    Particle rtn(PID::TAU, FourMomentum::mkXYZM(t.px() * fsmear, t.py() * fsmear, t.pz() * fsmear, mass));
    //if (deltaPhi(t, rtn) > 0.01) cout << "jdphi: " << deltaPhi(t, rtn) << endl;
    return rtn;
  }


  /// ATLAS Run 2 tau smearing
  ///
  /// @todo Currently a copy of the Run 1 version
  inline Particle TAU_SMEAR_ATLAS_RUN2(const Particle& t) {
    return TAU_SMEAR_ATLAS_RUN1(t);
  }


  /// CMS Run 1 tau efficiency
  ///
  /// @todo Needs work; this is just a copy of the Run 2 version in Delphes 3.3.2
  inline double TAU_EFF_CMS_RUN1(const Particle& t) {
    if (t.abspid() != PID::TAU) return 0;
    return (t.abspid() == PID::TAU) ? 0.6 : 0;
  }
  /// CMS Run 1 loose tau reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_CMS_RUN1_LOOSE(const Particle& t) {
    return TAU_EFF_CMS_RUN1(t);
  }
  /// CMS Run 1 medium muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_CMS_RUN1_MEDIUM(const Particle& t) {
    return TAU_EFF_CMS_RUN1(t);
  }
  /// CMS Run 1 tight muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_CMS_RUN1_TIGHT(const Particle& t) {
    return TAU_EFF_CMS_RUN1(t);
  }

  /// CMS Run 2 tau efficiency
  ///
  /// @todo Needs work; this is the dumb version from Delphes 3.3.2
  inline double TAU_EFF_CMS_RUN2(const Particle& t) {
    if (t.abspid() != PID::TAU) return 0;
    return (t.abspid() == PID::TAU) ? 0.6 : 0;
  }
  /// CMS Run 2 loose tau reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_CMS_RUN2_LOOSE(const Particle& t) {
    return TAU_EFF_CMS_RUN2(t);
  }
  /// CMS Run 2 medium muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_CMS_RUN2_MEDIUM(const Particle& t) {
    return TAU_EFF_CMS_RUN2(t);
  }
  /// CMS Run 2 tight muon reconstruction efficiency
  /// @todo Just an alias to generic: improve!
  inline double TAU_EFF_CMS_RUN2_TIGHT(const Particle& t) {
    return TAU_EFF_CMS_RUN2(t);
  }


  /// CMS Run 1 tau smearing
  ///
  /// @todo Currently a copy of the crappy ATLAS one
  inline Particle TAU_SMEAR_CMS_RUN1(const Particle& t) {
    return TAU_SMEAR_ATLAS_RUN1(t);
  }


  /// CMS Run 2 tau smearing
  ///
  /// @todo Currently a copy of the Run 1 version
  inline Particle TAU_SMEAR_CMS_RUN2(const Particle& t) {
    return TAU_SMEAR_CMS_RUN1(t);
  }

  /// @}


  /// @defgroup smearing_jet Experiment-specific jet efficiency and smearing functions
  /// @{

  /// Return the ATLAS Run 1 jet flavour tagging efficiency for the given Jet, from Delphes
  inline double JET_BTAG_ATLAS_RUN1(const Jet& j) {
    /// @todo This form drops past ~100 GeV, asymptotically to zero efficiency... really?!
    if (j.abseta() > 2.5) return 0;
    const auto ftagsel = [&](const Particle& p) {
      return p.pT() > 5 * GeV && deltaR(p, j) < 0.3;
    };
    if (j.bTagged(ftagsel)) return 0.80 * tanh(0.003 * j.pT() / GeV) * (30 / (1 + 0.0860 * j.pT() / GeV));
    if (j.cTagged(ftagsel)) return 0.20 * tanh(0.020 * j.pT() / GeV) * (1 / (1 + 0.0034 * j.pT() / GeV));
    return 0.002 + 7.3e-6 * j.pT() / GeV;
  }
  /// Alias for naming scheme
  inline double JET_BTAG_ATLAS_RUN1_XXX(const Jet& j) {
    return JET_BTAG_ATLAS_RUN1(j);
  }

  /// Return the ATLAS Run 2 MC2c20 77% WP jet flavour tagging efficiency for the given Jet
  inline double JET_BTAG_ATLAS_RUN2_MV2C20(const Jet& j) {
    if (j.abseta() > 2.5) return 0;
    if (j.bTagged(Cuts::pT > 5 * GeV)) return 0.77;
    if (j.cTagged(Cuts::pT > 5 * GeV)) return 1 / 4.5;
    return 1 / 140.;
  }

  /// Return the ATLAS Run 2 MC2c10 77% WP jet flavour tagging efficiency for the given Jet
  inline double JET_BTAG_ATLAS_RUN2_MV2C10(const Jet& j) {
    if (j.abseta() > 2.5) return 0;
    if (j.bTagged(Cuts::pT > 5 * GeV)) return 0.77;
    if (j.cTagged(Cuts::pT > 5 * GeV)) return 1 / 6.0;
    return 1 / 134.;
  }

  // pT-dependendent ATLAS Run 2 (2016 study) MV2c10 b-tagging efficiencies.
  // If high-pT b-jets are important in your analysis, be careful!
  // Based on ATL-PHYS-PUB-2016-012 fig 12
  inline double JET_BTAG_ATLAS_RUN2_2016_MV2C10_77(const Jet& j) {
    if (j.bTagged()) {
      // N.B. !!! There is no overflow bin.
      // There is a clear downward curve in efficiency as pT->inf, but the value to use for pT > 500
      // is super-unclear. The used value (0.69) is certainly a reasonable extrapolation, but it should
      // be noted that tuning this value can make a really significant difference to the bin counts O(10%)
      // HOWEVER: atlas really needs to start increasing the range of this sort of plot
      // The behaviour of jets pT>500 is much more interesting and significant than those in the range 20<pt<25.
      const static vector<double> binedges_pt = {0.00, 30.0, 40.00, 50.00, 60.0, 75.00,
                                                 90.0, 105., 150.,  200.,  500};
      const static vector<double> eff_pt = {0.63,  0.705, 0.74, 0.76, 0.775, 0.785,
                                            0.795, 0.80,  0.79, 0.75, 0.68};

      return eff_pt[binIndex(j.pt(), binedges_pt, true)];
    }
    else if (j.cTagged()) {
      //n.b. there is also a pt/eta table for c mistags, but if that's significant I'll eat my hat.
      return 1. / 5.;
    }
    else if (j.tauTagged()) {
      return 1. / 16.;
    }
    else
      return 1. / 110.;
  }

  // pT-dependendent ATLAS Run 2 DL1d b-tagging efficiencies.
  // If high-pT b-jets are important in your analysis, be careful!
  inline double JET_BTAG_ATLAS_RUN2_DL1d_77(const Jet& j) {
    if (j.bTagged()) {
      if (j.abseta() > 2.5) return 0.;

      // Original Values from FTAG-2023-01 (up to 400 GeV)
      // N.B. !!! There is no overflow bin.
      // There is a clear downward curve in efficiency as pT->inf, but the value to use for pT > 500
      // is super-unclear. The used value (0.69) is certainly a reasonable extrapolation, but it should
      // be noted that tuning this value can make a really significant difference to the bin counts O(10%)
      // HOWEVER: atlas really needs to start increasing the range of this sort of plot
      // The behaviour of jets pT>500 is much more interesting and significant than those in the range 20<pt<25.
      // N.B.2 Message above copied from my implementation of MV2c10. Plus ca change...
      // Better distributions available for DL1r, but not here.
      // I will use the DL1/DL1r plots in arXiv:2211.16345 to guess a good overflow value
      // (the consistency between DL1, DL1r hopefully makes this not crazy)
      const static vector<double> binedges_pt = {0.00, 20.,  30.,  40.,  60.,  85.,   110.,
                                                 140., 175., 250., 400., 800., 1200., 2000.};
      const static vector<double> eff_pt = {0.0,  0.68,  0.74, 0.77, 0.79, 0.8,  0.81,
                                            0.81, 0.805, 0.78, 0.75, 0.7,  0.65, 0.5};

      return eff_pt[binIndex(j.pt(), binedges_pt, true)];
    }
    else if (j.cTagged()) {
      //n.b. there is also a pt/eta table for c mistags, shouldn't be too significant
      return 0.155;
    }
    // Nothing in the paper, going to guess something small just in case.
    else if (j.tauTagged()) {
      return 1. / 36.;
    }
    else
      return 0.0038;
  }

  // Based on figs 11-12 of https://arxiv.org/pdf/2211.16345
  // As far as I can see, this is the only pre-GN2 b-tag paper
  // that includes efficiencies up to very high pt. Thankyou!!!
  // Though n.b. the 0-250 range is in ttbar and 250-3000 is in
  // simulated Z', hence the discontinuities going on.
  inline double JET_BTAG_ATLAS_RUN2_DL1r_77(const Jet& j) {
    if (j.pt() <= 20 * GeV || j.abseta() > 2.5) return 0.;

    const static vector<double> binedges_pt = {20.,   30.,   40.,   60.,    85.,   110., 140.,
                                               175.,  210.,  250.,  400.,   600.,  800., 1000.,
                                               1200., 1400., 1500., 2000.0, 3000.0};

    if (j.bTagged()) {
      // TODO: for pT < 250 we also have eta dependence... include somehow?
      const static vector<double> eff_pt = {0.667, 0.731, 0.771, 0.791, 0.801, 0.805, 0.806,
                                            0.798, 0.795, 0.825, 0.802, 0.771, 0.741, 0.706,
                                            0.679, 0.674, 0.634, 0.5,   0.5};
      // 0.5 repeated for overflow just in case.

      return eff_pt[binIndex(j.pt(), binedges_pt, true)];
    }
    else if (j.cTagged()) {
      const static vector<double> c_rej_pt = {5.30, 5.23, 5.55, 5.91,  6.13, 6.30, 6.32, 6.50, 6.10, 3.04,
                                              3.05, 3.21, 3.37, 3.616, 3.83, 3.96, 4.01, 2.90, 2.90};
      // 2.90 repeated for overflow just in case.
      return 1. / c_rej_pt[binIndex(j.pt(), binedges_pt, true)];
    }
    else {
      const static vector<double> light_rej_pt = {143,  191,  239,  261,  235,  257,  248,  189,  158, 32.8,
                                                  19.1, 14.2, 12.4, 11.2, 11.0, 11.2, 12.4, 8.27, 8.27};
      // 8.27 repeated for overflow just in case.]
      return 1. / light_rej_pt[binIndex(j.pt(), binedges_pt, true)];
    }
  }


  /// @brief ATLAS Run 1 jet smearing
  ///
  /// Implemented by Matthias Danninger for GAMBIT, based roughly on
  /// https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/CONFNOTES/ATLAS-CONF-2015-017/
  inline Jet JET_SMEAR_ATLAS_RUN1(const Jet& j) {
    // Jet energy resolution lookup
    //   Parameterisation can be still improved, but eta dependence is minimal
    /// @todo Also need a JES uncertainty component?
    static const vector<double> binedges_pt = {0., 50., 70., 100., 150., 200., 1000., 10000.};
    static const vector<double> jer = {0.145, 0.115, 0.095, 0.075,
                                       0.07,  0.05,  0.04,  0.04}; //< note overflow value
    const int ipt = binIndex(j.pT() / GeV, binedges_pt, true);
    if (ipt < 0) return j;
    const double resolution = jer.at(ipt);

    // Smear by a Gaussian centered on 1 with width given by the (fractional) resolution
    /// @todo Is this the best way to smear? Should we preserve the energy, or pT, or direction?
    const double fsmear = max(randnorm(1., resolution), 0.);
    const double mass = j.mass2() > 0 ? j.mass() : 0; //< numerical carefulness...
    Jet rtn(FourMomentum::mkXYZM(j.px() * fsmear, j.py() * fsmear, j.pz() * fsmear, mass));
    //if (deltaPhi(j, rtn) > 0.01) cout << "jdphi: " << deltaPhi(j, rtn) << endl;
    return rtn;
  }

  /// ATLAS Run 2 jet smearing
  ///
  /// @todo Just a copy of the Run 1 one: improve!!
  inline Jet JET_SMEAR_ATLAS_RUN2(const Jet& j) {
    return JET_SMEAR_ATLAS_RUN1(j);
  }

  /// CMS Run 2 jet smearing
  ///
  /// @todo Just a copy of the suboptimal ATLAS one: improve!!
  inline Jet JET_SMEAR_CMS_RUN1(const Jet& j) {
    return JET_SMEAR_ATLAS_RUN1(j);
  }

  /// CMS Run 2 jet smearing
  ///
  /// @todo Just a copy of the suboptimal ATLAS one: improve!!
  inline Jet JET_SMEAR_CMS_RUN2(const Jet& j) {
    return JET_SMEAR_CMS_RUN1(j);
  }

  /// @}


  /// @defgroup smearing_met Experiment-specific missing-ET smearing functions
  /// @{

  /// @brief ATLAS Run 1 ETmiss resolution
  ///
  /// Based on https://arxiv.org/pdf/1108.5602v2.pdf, Figs 14 and 15
  inline METSmearParams MET_SMEARPARAMS_ATLAS_RUN1(const Vector3& met, double set) {
    // Linearity offset (Fig 14)
    Vector3 smeared_met = met;
    if (met.mod() < 25 * GeV)
      smeared_met *= 1.05;
    else if (met.mod() < 40 * GeV)
      smeared_met *= (1.05 - (0.04 / 15) * (met.mod() / GeV - 25)); //< linear decrease
    else
      smeared_met *= 1.01;

    return {smeared_met, 0.45 * sqrt(set / GeV) * GeV, 0.0};
  }

  /// @brief ATLAS Run 1 ETmiss smearing
  inline Vector3 MET_SMEAR_ATLAS_RUN1(const Vector3& met, double set) {
    return MET_SMEAR_NORM(MET_SMEARPARAMS_ATLAS_RUN1(met, set));
  }


  /// ATLAS Run 2 ETmiss resolution
  ///
  /// Based on https://arxiv.org/pdf/1802.08168.pdf, Figs 6-9
  inline METSmearParams MET_SMEARPARAMS_ATLAS_RUN2(const Vector3& met, double set) {
    // Linearity offset (Fig 6):
    //
    // Expn. approx to Fig 6 tt curve, flat below 25 GeV, suppressed
    // to fall between the W and tt curves (and match the flat) at 25 GeV,
    // and to approach -2% at high-MET.
    //
    /// @todo If we could access the whole event we could switch between W and tt curves based on jet/lep activity...
    const Vector3 smeared_met = met * (1 + 0.45 * min(1.0, exp(-(met.mod() - 25 * GeV) / (10 * GeV))) - 0.02);

    // Resolution(sumEt) ~ 0.45 sqrt(sumEt) GeV above SET = 180 GeV,
    // and with linear trend from SET = 180 -> 0 to resolution = 0 (Fig 7)
    const double resolution1 = (set < 180 * GeV ? set / 180. : 1) * 0.45 * sqrt(max(set / GeV, 180)) * GeV;
    /// @todo Allow smearing function to access the whole event, since Njet also affects? Or assume encoded in SET?

    // Resolution(MET_true) (Fig 9)
    const double resolution2 = 15 * GeV + 0.5 * sqrt(met.mod() / GeV) * GeV;

    // Smearing width is given by the minimum resolution estimator (should mean low-MET events
    // with high SET do not get a large smearing, and will be dominated by the linearity effect).
    /// @todo Arguably should somehow take the max of this and the linearity... but this is re-used
    const double sigma = min(resolution1, resolution2);

    return {smeared_met, sigma, 0.0};
  }

  /// ATLAS Run 2 ETmiss smearing
  inline Vector3 MET_SMEAR_ATLAS_RUN2(const Vector3& met, double set) {
    return MET_SMEAR_NORM(MET_SMEARPARAMS_ATLAS_RUN2(met, set));
  }


  /// ATLAS Run 2 pflow ETmiss resolution
  ///
  /// @warning No explicitly encoded SET-dependence, uses average of tt, VBF H->WW, and W->munu curves at <mu>.
  ///
  /// Based on https://arxiv.org/pdf/2402.05858
  inline METSmearParams MET_SMEARPARAMS_ATLAS_RUN2_PFLOW(const Vector3& met, double /* set */) {
    // Mean response (Fig 7), expn approximation to the ttbar curve guessing 2 e-foldings in 40 GeV.
    /// @todo If we could access the whole event we could switch between W and tt curves based on jet/lep activity...
    const Vector3 smeared_met = met * (1 + 1.15 * exp(-met.mod() / (20 * GeV)) - 0.01);

    // Mean resolution ~ 15-25 GeV for mu ~ 33.7 (Run 2 avg), but significant dependence on event type (i.e. SET)
    // See Figures 4 and 5. The paper doesn't provide enough information for a general SET-dependence:
    // maybe prefer the older MET smearing. Not enough discrimination between WPs, mainly encoded vs mu or N_PV.
    const double resolution = 20 * GeV;

    return {smeared_met, resolution, 0.0};
  }

  /// ATLAS Run 2 pflow ETmiss smearing
  inline Vector3 MET_SMEAR_ATLAS_RUN2_PFLOW(const Vector3& met, double set) {
    return MET_SMEAR_NORM(MET_SMEARPARAMS_ATLAS_RUN2_PFLOW(met, set));
  }


  /// CMS Run 1 ETmiss smearing params
  ///
  /// From https://arxiv.org/pdf/1411.0511.pdf Table 2, p16 (Z channels)
  inline METSmearParams MET_SMEARPARAMS_CMS_RUN1(const Vector3& met, double set) {
    // Calculate parallel and perpendicular resolutions and combine in quadrature (?)
    const double resolution_x = (1.1 + 0.6 * sqrt(set / GeV)) * GeV;
    const double resolution_y = (1.4 + 0.6 * sqrt(set / GeV)) * GeV;
    const double resolution = sqrt(sqr(resolution_x) + sqr(resolution_y));
    return {met, resolution, 0.0};
  }

  /// CMS Run 1 ETmiss smearing
  inline Vector3 MET_SMEAR_CMS_RUN1(const Vector3& met, double set) {
    return MET_SMEAR_NORM(MET_SMEARPARAMS_CMS_RUN1(met, set));
  }


  /// @brief CMS Run 2 ETmiss smearing
  ///
  /// From http://inspirehep.net/record/1681214/files/JME-17-001-pas.pdf Table 3, p20
  inline METSmearParams MET_SMEARPARAMS_CMS_RUN2(const Vector3& met, double set) {
    // Calculate parallel and perpendicular resolutions and combine in quadrature (?)
    const double resolution_para = (2.0 + 0.64 * sqrt(set / GeV)) * GeV;
    const double resolution_perp = (-1.5 + 0.68 * sqrt(set / GeV)) * GeV;
    const double resolution = sqrt(sqr(resolution_para) + sqr(resolution_perp));
    return {met, resolution, 0.0};
  }

  /// @brief CMS Run 2 ETmiss smearing
  inline Vector3 MET_SMEAR_CMS_RUN2(const Vector3& met, double set) {
    return MET_SMEAR_NORM(MET_SMEARPARAMS_CMS_RUN2(met, set));
  }

  /// @}


  /// @defgroup smearing_trk Experiment-specific tracking efficiency and smearing functions
  /// @{

  /// ATLAS Run 1 tracking efficiency
  inline double TRK_EFF_ATLAS_RUN1(const Particle& p) {
    if (p.charge3() == 0) return 0;
    if (p.abseta() > 2.5) return 0;
    if (p.pT() < 0.1 * GeV) return 0;

    if (p.abspid() == PID::ELECTRON) {
      if (p.abseta() < 1.5) {
        if (p.pT() < 1 * GeV) return 0.73;
        if (p.pT() < 100 * GeV) return 0.95;
        return 0.99;
      }
      else {
        if (p.pT() < 1 * GeV) return 0.50;
        if (p.pT() < 100 * GeV)
          return 0.83;
        else
          return 0.90;
      }
    }
    else if (p.abspid() == PID::MUON) {
      if (p.abseta() < 1.5) {
        return (p.pT() < 1 * GeV) ? 0.75 : 0.99;
      }
      else {
        return (p.pT() < 1 * GeV) ? 0.70 : 0.98;
      }
    }
    else { // charged hadrons
      if (p.abseta() < 1.5) {
        return (p.pT() < 1 * GeV) ? 0.70 : 0.95;
      }
      else {
        return (p.pT() < 1 * GeV) ? 0.60 : 0.85;
      }
    }
  }

  /// ATLAS Run 2 tracking efficiency
  ///
  /// @todo Currently just a copy of Run 1: fix!
  inline double TRK_EFF_ATLAS_RUN2(const Particle& p) {
    return TRK_EFF_ATLAS_RUN1(p);
  }


  /// ATLAS Run 1 track smearing
  ///
  /// @todo Currently identity: fix!
  inline Particle TRK_SMEAR_ATLAS_RUN1(const Particle& t) {
    return PARTICLE_SMEAR_IDENTITY(t);
  }
  /// ATLAS Run 2 track smearing
  ///
  /// @todo Currently identity: fix!
  inline Particle TRK_SMEAR_ATLAS_RUN2(const Particle& t) {
    return PARTICLE_SMEAR_IDENTITY(t);
  }


  /// CMS Run 1 tracking efficiency
  inline double TRK_EFF_CMS_RUN1(const Particle& p) {
    if (p.charge3() == 0) return 0;
    if (p.abseta() > 2.5) return 0;
    if (p.pT() < 0.1 * GeV) return 0;

    if (p.abspid() == PID::ELECTRON) {
      if (p.abseta() < 1.5) {
        if (p.pT() < 1 * GeV) return 0.73;
        if (p.pT() < 100 * GeV) return 0.95;
        return 0.99;
      }
      else {
        if (p.pT() < 1 * GeV) return 0.50;
        if (p.pT() < 100 * GeV)
          return 0.83;
        else
          return 0.90;
      }
    }
    else if (p.abspid() == PID::MUON) {
      if (p.abseta() < 1.5) {
        return (p.pT() < 1 * GeV) ? 0.75 : 0.99;
      }
      else {
        return (p.pT() < 1 * GeV) ? 0.70 : 0.98;
      }
    }
    else { // charged hadrons
      if (p.abseta() < 1.5) {
        return (p.pT() < 1 * GeV) ? 0.70 : 0.95;
      }
      else {
        return (p.pT() < 1 * GeV) ? 0.60 : 0.85;
      }
    }
  }

  /// CMS Run 2 tracking efficiency
  ///
  /// @todo Currently just a copy of Run 1: fix!
  inline double TRK_EFF_CMS_RUN2(const Particle& p) {
    return TRK_EFF_CMS_RUN1(p);
  }


  /// CMS Run 1 track smearing
  ///
  /// @todo Currently identity: fix!
  inline Particle TRK_SMEAR_CMS_RUN1(const Particle& t) {
    return PARTICLE_SMEAR_IDENTITY(t);
  }
  /// CMS Run 2 track smearing
  ///
  /// @todo Currently identity: fix!
  inline Particle TRK_SMEAR_CMS_RUN2(const Particle& t) {
    return PARTICLE_SMEAR_IDENTITY(t);
  }

  /// @brief Return the efficiency of the ATLAS JVT tagger at > 0.2 W.P.
  ///
  /// Values taken from fig 17, https://arxiv.org/pdf/1510.03823.pdf.
  /// Shockingly, its run1, but it's still the most recent ATLAS JVT public plots
  /// And is still cited by all the Run 2 papers
  /// Note! The exact translation of weak/medium/tight varies across runs/years
  /// If possible double check the score cut off used.
  inline double ATLAS_JVT_EFF_LOOSE(const Jet& j) {
    if (j.abseta() > 2.4) return 1.0;
    // No data for jets pt < 20, hopefully not relevant:
    if (j.pt() <= 20 * GeV || j.pt() >= 60 * GeV) return 1.0;

    const static vector<double> binedges_pt = {20 * GeV, 25 * GeV, 30 * GeV, 35 * GeV, 40 * GeV,
                                               45 * GeV, 50 * GeV, 55 * GeV, 60 * GeV};
    const static vector<double> binvals = {0.9, 0.93, 0.94, 0.95, 0.96, 0.96, 0.97, 0.97};

    const size_t bini = binIndex(j.pt(), binedges_pt);
    return binvals[bini];
  }

  /// @brief Return the efficiency of the ATLAS JVT tagger at > 0.4 W.P.
  ///
  /// Values taken from fig 17, https://arxiv.org/pdf/1510.03823.pdf.
  /// Shockingly, its run1, but it's still the most recent ATLAS JVT public plots
  /// And is still cited by all the Run 2 papers
  /// Note! The exact translation of weak/medium/tight varies across runs/years
  /// If possible double check the score cut off used.
  inline double ATLAS_JVT_EFF_MEDIUM(const Jet& j) {
    if (j.abseta() > 2.4) return 1.0;
    // No data for jets pt < 20, hopefully not relevant:
    if (j.pt() <= 20 * GeV || j.pt() >= 60 * GeV) return 1.0;

    const static vector<double> binedges_pt = {20 * GeV, 25 * GeV, 30 * GeV, 35 * GeV, 40 * GeV,
                                               45 * GeV, 50 * GeV, 55 * GeV, 60 * GeV};
    const static vector<double> binvals = {0.86, 0.9, 0.92, 0.93, 0.94, 0.95, 0.95, 0.96};

    const size_t bini = binIndex(j.pt(), binedges_pt);
    return binvals[bini];
  }

  /// @brief Return the efficiency of the ATLAS JVT tagger at > 0.7 W.P.
  ///
  /// Values taken from fig 17, https://arxiv.org/pdf/1510.03823.pdf.
  /// Shockingly, its run1, but it's still the most recent ATLAS JVT public plots
  /// And is still cited by all the Run 2 papers
  /// Note! The exact translation of weak/medium/tight varies across runs/years
  /// If possible double check the score cut off used.
  inline double ATLAS_JVT_EFF_TIGHT(const Jet& j) {
    if (j.abseta() > 2.4) return 1.0;
    // No data for jets pt < 20, hopefully not relevant:
    if (j.pt() <= 20 * GeV || j.pt() >= 60 * GeV) return 1.0;

    const static vector<double> binedges_pt = {20 * GeV, 25 * GeV, 30 * GeV, 35 * GeV, 40 * GeV,
                                               45 * GeV, 50 * GeV, 55 * GeV, 60 * GeV};
    const static vector<double> binvals = {0.81, 0.84, 0.87, 0.90, 0.91, 0.92, 0.93, 0.94};

    const size_t bini = binIndex(j.pt(), binedges_pt);
    return binvals[bini];
  }

  /// @}

  /// @name A full family of identity smearing functions
  /// @{

  inline double ELECTRON_EFF_IDENTITY_LOOSE(const Particle& e) {
    return PARTICLE_EFF_ONE(e);
  }
  inline double ELECTRON_EFF_IDENTITY_MEDIUM(const Particle& e) {
    return PARTICLE_EFF_ONE(e);
  }
  inline double ELECTRON_EFF_IDENTITY_TIGHT(const Particle& e) {
    return PARTICLE_EFF_ONE(e);
  }
  inline double MUON_EFF_IDENTITY_LOOSE(const Particle& m) {
    return PARTICLE_EFF_ONE(m);
  }
  inline double MUON_EFF_IDENTITY_MEDIUM(const Particle& m) {
    return PARTICLE_EFF_ONE(m);
  }
  inline double MUON_EFF_IDENTITY_TIGHT(const Particle& m) {
    return PARTICLE_EFF_ONE(m);
  }
  inline double PHOTON_EFF_IDENTITY_LOOSE(const Particle& y) {
    return PARTICLE_EFF_ONE(y);
  }
  inline double PHOTON_EFF_IDENTITY_MEDIUM(const Particle& y) {
    return PARTICLE_EFF_ONE(y);
  }
  inline double PHOTON_EFF_IDENTITY_TIGHT(const Particle& y) {
    return PARTICLE_EFF_ONE(y);
  }
  inline double TAU_EFF_IDENTITY_LOOSE(const Particle& t) {
    return PARTICLE_EFF_ONE(t);
  }
  inline double TAU_EFF_IDENTITY_MEDIUM(const Particle& t) {
    return PARTICLE_EFF_ONE(t);
  }
  inline double TAU_EFF_IDENTITY_TIGHT(const Particle& t) {
    return PARTICLE_EFF_ONE(t);
  }

  inline Particle ELECTRON_SMEAR_IDENTITY(const Particle& e) {
    return PARTICLE_SMEAR_IDENTITY(e);
  }
  inline Particle MUON_SMEAR_IDENTITY(const Particle& m) {
    return PARTICLE_SMEAR_IDENTITY(m);
  }
  inline Particle PHOTON_SMEAR_IDENTITY(const Particle& y) {
    return PARTICLE_SMEAR_IDENTITY(y);
  }
  inline Particle TAU_SMEAR_IDENTITY(const Particle& t) {
    return PARTICLE_SMEAR_IDENTITY(t);
  }

  inline double TRK_EFF_IDENTITY_TIGHT(const Particle& trk) {
    return PARTICLE_EFF_ONE(trk);
  }
  inline Particle TRK_SMEAR_IDENTITY(const Particle& trk) {
    return PARTICLE_SMEAR_IDENTITY(trk);
  }

  inline double JET_BTAG_IDENTITY_IDENTITY(const Jet& j) {
    return JET_BTAG_IDENTITY(j);
  }

  // Already defined: JET_SMEAR_IDENTITY and MET_SMEAR_IDENTITY

  /// @}

  /// @}


}

#endif
