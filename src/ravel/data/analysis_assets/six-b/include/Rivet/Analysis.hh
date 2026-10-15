// -*- C++ -*-
#ifndef RIVET_Analysis_HH
#define RIVET_Analysis_HH

#include "Rivet/AnalysisInfo.hh"
#include "Rivet/AnalysisLoader.hh"
#include "Rivet/Event.hh"
#include "Rivet/Projection.hh"
#include "Rivet/ProjectionApplier.hh"
#include "Rivet/ProjectionHandler.hh"
#include "Rivet/Config/RivetCommon.hh"
#include "Rivet/Tools/Cuts.hh"
#include "Rivet/Tools/Logging.hh"
#include "Rivet/Tools/ParticleUtils.hh"
#ifdef HAVE_H5
  #include "Rivet/Tools/RivetHDF5.hh"
#endif
#include "Rivet/Projections/CentralityProjection.hh"
#include "Rivet/Projections/FastJets.hh"
#include "Rivet/Tools/Cutflow.hh"
#include "Rivet/Tools/HistoGroup.hh"
#include "Rivet/Tools/Percentile.hh"
#include "Rivet/Tools/RivetMT2.hh"
#include "Rivet/Tools/RivetPaths.hh"
#include "Rivet/Tools/RivetYODA.hh"
#include <tuple>


/// @def vetoEvent
/// Preprocessor define for vetoing events, including the log message and return.
#define vetoEvent                                                       \
  do { MSG_DEBUG("Vetoing event on line " << __LINE__ << " of " << __FILE__); return; } while(0)

namespace Rivet {


  // Convenience for analysis writers
  using std::cerr;
  using std::cout;
  using std::endl;
  using std::numeric_limits;
  using std::stringstream;
  using std::swap;
  using std::tuple;


  // Forward declaration
  class AnalysisHandler;


  /// @brief This is the base class of all analysis classes in Rivet.
  ///
  /// There are
  /// three virtual functions which should be implemented in base classes:
  ///
  /// void init() is called by Rivet before a run is started. Here the
  /// analysis class should book necessary histograms. The needed
  /// projections should probably rather be constructed in the
  /// constructor.
  ///
  /// void analyze(const Event&) is called once for each event. Here the
  /// analysis class should apply the necessary Projections and fill the
  /// histograms.
  ///
  /// void finalize() is called after a run is finished. Here the analysis
  /// class should do whatever manipulations are necessary on the
  /// histograms. Writing the histograms to a file is, however, done by
  /// the AnalysisHandler class.
  class Analysis : public ProjectionApplier {
  public:

    /// The AnalysisHandler is a friend.
    friend class AnalysisHandler;


    /// Constructor
    Analysis(const std::string& name);

    /// The destructor
    virtual ~Analysis() { }

    /// The assignment operator is private and must be deleted, so it can never be called.
    Analysis& operator=(const Analysis&) = delete;


  public:

    /// @name Main analysis methods
    /// @{

    /// Initialize this analysis object. A concrete class should here
    /// book all necessary histograms. An overridden function must make
    /// sure it first calls the base class function.
    virtual void init() { }

    /// Analyze one event. A concrete class should here apply the
    /// necessary projections on the \a event and fill the relevant
    /// histograms. An overridden function must make sure it first calls
    /// the base class function.
    virtual void analyze(const Event& event) = 0;

    /// Finalize this analysis object. A concrete class should here make
    /// all necessary operations on the histograms. Writing the
    /// histograms to a file is, however, done by the Rivet class. An
    /// overridden function must make sure it first calls the base class
    /// function.
    virtual void finalize() { }

    /// @}


    /// @name Power-user analysis methods
    /// @{

    /// A method called before init(), for cleaner subclassing
    virtual void preInit() { }
    /// A method called after init(), for cleaner subclassing
    virtual void postInit() { }
    /// A method called before analyze(), for cleaner subclassing
    virtual void preAnalyze(const Event&) { }
    /// A method called after analyze(), for cleaner subclassing
    virtual void postAnalyze(const Event&) { }
    /// A method called before finalize(), for cleaner subclassing
    virtual void preFinalize() { }
    /// A method called after finalize(), for cleaner subclassing
    virtual void postFinalize() { }

    /// Call the projection applier _syncDeclQueue() method.
    ///
    /// @note It should be hidden for all projection appliers other than analyses.
    void syncDeclQueue() {
      this->_syncDeclQueue();
      this->markAsOwned();
    }

    /// @}


  public:

    /// @name Metadata
    ///
    /// Metadata is used for querying from the command line and also for
    /// building web pages and the analysis pages in the Rivet manual.
    /// @{

    /// Get the AnalysisInfo object to parse its info file in which the metadata is stored.
    void loadInfo() {
      info().parseInfoFile();
    }

    /// Get the actual AnalysisInfo object in which all this metadata is stored.
    const AnalysisInfo& info() const {
      if (!_info) throw Error("No AnalysisInfo object :-O");
      return *_info;
    }

    /// @brief Get the name of the analysis.
    ///
    /// By default this is computed by combining the results of the
    /// experiment, year and Spires ID metadata methods and you should
    /// only override it if there's a good reason why those won't
    /// work. If options has been set for this instance, a
    /// corresponding string is appended at the end.
    virtual std::string name() const {
      return ((info().name().empty()) ? _defaultname : info().name()) + _optstring;
    }

    /// @brief Get the path to a data file associated with this analysis
    ///
    /// The searched-for filename will be \<ANANAME\>.\<extn\> of suffix is empty/unspecified,
    /// or \<ANANAME\>-\<suffix\>.\<extn\> if a non-zero suffix is specified.
    std::string analysisDataPath(const std::string& extn, const std::string& suffix = "") {
      string filename = name() + (suffix.empty() ? "" : "-") + suffix + "." + extn;
      return findAnalysisDataFile(filename);
    }

    /// Get the Inspire ID code for this analysis.
    virtual std::string inspireID() const {
      return info().inspireID();
    }

    /// Get the SPIRES ID code for this analysis (~deprecated).
    virtual std::string spiresID() const {
      return info().spiresID();
    }

    /// @brief Names & emails of paper/analysis authors.
    ///
    /// Names and email of authors in 'NAME \<EMAIL\>' format. The first
    /// name in the list should be the primary contact person.
    virtual std::vector<std::string> authors() const {
      return info().authors();
    }

    /// @brief Get a short description of the analysis.
    ///
    /// Short (one sentence) description used as an index entry.
    /// Use @a description() to provide full descriptive paragraphs
    /// of analysis details.
    virtual std::string summary() const {
      return info().summary();
    }

    /// @brief Get a full description of the analysis.
    ///
    /// Full textual description of this analysis, what it is useful for,
    /// what experimental techniques are applied, etc. Should be treated
    /// as a chunk of restructuredText (http://docutils.sourceforge.net/rst.html),
    /// with equations to be rendered as LaTeX with amsmath operators.
    virtual std::string description() const {
      return info().description();
    }

    /// @brief Information about the events needed as input for this analysis.
    ///
    /// Event types, energies, kinematic cuts, particles to be considered
    /// stable, etc. etc. Should be treated as a restructuredText bullet list
    /// (http://docutils.sourceforge.net/rst.html)
    virtual std::string runInfo() const {
      return info().runInfo();
    }

    /// Experiment which performed and published this analysis.
    virtual std::string experiment() const {
      return info().experiment();
    }

    /// Collider on which the experiment ran.
    virtual std::string collider() const {
      return info().collider();
    }

    /// When the original experimental analysis was published.
    virtual std::string year() const {
      return info().year();
    }

    /// The integrated luminosity in inverse femtobarn
    virtual double luminosityfb() const {
      return info().luminosityfb();
    }
    /// The integrated luminosity in inverse picobarn
    virtual double luminosity() const {
      return info().luminosity();
    }
    /// The integrated luminosity in inverse picobarn
    double luminositypb() const {
      return luminosity();
    }

    /// Journal, and preprint references.
    virtual std::vector<std::string> references() const {
      return info().references();
    }

    /// BibTeX citation key for this article.
    virtual std::string bibKey() const {
      return info().bibKey();
    }

    /// BibTeX citation entry for this article.
    virtual std::string bibTeX() const {
      return info().bibTeX();
    }

    /// Whether this analysis is trusted (in any way!)
    virtual std::string status() const {
      return (info().status().empty()) ? "UNVALIDATED" : info().status();
    }

    /// A warning message from the info file, if there is one
    virtual std::string warning() const {
      return info().warning();
    }

    /// Any work to be done on this analysis.
    virtual std::vector<std::string> todos() const {
      return info().todos();
    }

    /// make-style commands for validating this analysis.
    virtual std::vector<std::string> validation() const {
      return info().validation();
    }

    /// Does this analysis have a reentrant finalize()?
    virtual bool reentrant() const {
      return info().reentrant();
    }

    /// Get vector of analysis keywords
    virtual const std::vector<std::string>& keywords() const {
      return info().keywords();
    }

    /// Positive filtering regex for ref-data HepData sync
    virtual std::string refMatch() const {
      return info().refMatch();
    }

    /// Negative filtering regex for ref-data HepData sync
    virtual std::string refUnmatch() const {
      return info().refUnmatch();
    }

    /// Positive filtering regex for setting double precision in Writer
    virtual std::string writerDoublePrecision() const {
      return info().writerDoublePrecision();
    }

    /// Return the allowed pairs of incoming beams required by this analysis.
    virtual const std::vector<PdgIdPair>& requiredBeamIDs() const {
      return info().beamIDs();
    }
    /// Declare the allowed pairs of incoming beams required by this analysis.
    virtual Analysis& setRequiredBeamIDs(const std::vector<PdgIdPair>& beamids) {
      info().setBeamIDs(beamids);
      return *this;
    }

    /// Sets of valid beam energy pairs, in GeV
    virtual const std::vector<std::pair<double, double>>& requiredBeamEnergies() const {
      return info().energies();
    }
    /// Declare the list of valid beam energy pairs, in GeV
    virtual Analysis& setRequiredBeamEnergies(const std::vector<std::pair<double, double>>& energies) {
      info().setEnergies(energies);
      return *this;
    }


    /// Location of reference data YODA file
    virtual std::string refFile() const {
      return info().refFile();
    }
    /// Get name of reference data file, which could be different from plugin name
    virtual std::string refDataName() const {
      return (info().getRefDataName().empty()) ? _defaultname : info().getRefDataName();
    }
    /// Set name of reference data file, which could be different from plugin name
    virtual void setRefDataName(const std::string& ref_data = "") {
      info().setRefDataName(!ref_data.empty() ? ref_data : name());
    }


    /// @brief Get the actual AnalysisInfo object in which all this metadata is stored (non-const).
    ///
    /// @note For *internal* use!
    AnalysisInfo& info() {
      if (!_info) throw Error("No AnalysisInfo object :-O");
      return *_info;
    }

    /// @}


    /// @name Run conditions
    /// @{

    /// Check if we are running rivet-merge
    bool merging() const {
      return sqrtS() <= 0.0;
    }

    /// Check if the given conditions are compatible with this analysis' declared constraints
    bool compatibleWithRun() const;

    /// Raise BeamError if @a condition not met and not in merging mode
    void raiseBeamErrorIf(const bool condition) const;

    /// @}


    /// @name Analysis / beam compatibility testing
    ///
    /// @{

    /// Incoming beams for this run
    const ParticlePair& beams() const;

    /// Incoming beam IDs for this run
    PdgIdPair beamIDs() const;

    /// Incoming beam energies for this run
    pair<double, double> beamEnergies() const;

    /// Allowed centre-of-mass energies (in GeV) for this routine
    vector<double> allowedEnergies() const;

    /// Centre of mass energy for this run
    double sqrtS() const;

    /// Check if analysis is compatible with the provided beam particle IDs and energies
    bool beamsMatch(const ParticlePair& beams) const;

    /// Check if analysis is compatible with the provided beam particle IDs and energies
    bool beamsMatch(PdgId beam1, PdgId beam2, double e1, double e2) const;

    /// Check if analysis is compatible with the provided beam particle IDs and energies in GeV
    bool beamsMatch(const PdgIdPair& beams, const std::pair<double, double>& energies) const;

    /// Check if analysis is compatible with the provided beam particle IDs
    bool beamIDsMatch(PdgId beam1, PdgId beam2) const;

    /// Check if analysis is compatible with the provided beam particle IDs
    bool beamIDsMatch(const PdgIdPair& beamids) const;

    /// Check if analysis is compatible with the provided beam energies
    bool beamEnergiesMatch(double e1, double e2) const;

    /// Check if analysis is compatible with the provided beam energies
    bool beamEnergiesMatch(const std::pair<double, double>& energies) const;

    /// Check if analysis is compatible with the provided CoM energy
    bool beamEnergyMatch(const std::pair<double, double>& energies) const;

    /// Check if analysis is compatible with the provided CoM energy
    bool beamEnergyMatch(double sqrts) const;

    /// Check if sqrtS is compatible with provided value
    bool isCompatibleWithSqrtS(double energy, double tolerance = 1e-5) const;

    /// @}


    /// Access the controlling AnalysisHandler object.
    AnalysisHandler& handler() const {
      return *_analysishandler;
    }

    /// Access the current event
    const Event& currentEvent() const {
      if (!_currentevent) {
        throw Error("No current event set: did you try to access it in init() or finalize()?");
      }
      return *_currentevent;
    }


  protected:

    /// Get a Log object based on the name() property of the calling analysis object.
    Log& getLog() const;

    /// Get the process cross-section in pb. Throws if this hasn't been set.
    double crossSection() const;

    /// Get the process cross-section per generated event in pb. Throws if this
    /// hasn't been set.
    double crossSectionPerEvent() const;

    /// Get the process cross-section error in pb. Throws if this hasn't been set.
    double crossSectionError() const;

    /// Get the process cross-section error per generated event in
    /// pb. Throws if this hasn't been set.
    double crossSectionErrorPerEvent() const;

    /// @brief Get the number of events seen (via the analysis handler).
    ///
    /// @note Use in the finalize phase only.
    size_t numEvents() const;

    /// @brief Get the effective number of events seen (via the analysis handler).
    ///
    /// @note Use in the finalize phase only.
    double effNumEvents() const;

    /// @brief Get the sum of event weights seen (via the analysis handler).
    ///
    /// @note Use in the finalize phase only.
    double sumW() const;
    /// Alias
    double sumOfWeights() const {
      return sumW();
    }

    /// @brief Get the sum of squared event weights seen (via the analysis handler).
    ///
    /// @note Use in the finalize phase only.
    double sumW2() const;


  protected:

    /// @defgroup analysis_histopaths Histogram paths
    ///
    /// @todo Add "tmp" flags to return /ANA/TMP/foo/bar paths
    ///
    /// @{

    /// Get the canonical histogram "directory" path for this analysis.
    const std::string histoDir() const;

    /// Get the canonical histogram path for the named histogram in this analysis.
    const std::string histoPath(const std::string& hname) const;

    /// Get the canonical histogram path for the numbered histogram in this analysis.
    const std::string histoPath(unsigned int datasetID, unsigned int xAxisID, unsigned int yAxisID) const;

    /// Get the internal histogram name for given d, x and y (cf. HepData)
    const std::string mkAxisCode(unsigned int datasetID, unsigned int xAxisID, unsigned int yAxisID) const;

    /// @}


#ifdef HAVE_H5
    /// @name Auxiliary HDF5 reference data
    /// @{

    /// Read in an aux data HDF5 file
    H5::File auxFile() const {
      return H5::readFile(name() + ".h5");
    }

    /// Read HDF5 file @a filename
    template <typename T>
    bool auxData(const string& dsname, T& rtndata) {
      /// @todo Cache loading the H5 files? On MPI?
      return H5::readData(name() + ".h5", dsname, rtndata);
    }

    template <typename T>
    T auxData(const string& dsname) {
      /// @todo Cache loading the H5 files? On MPI?
      return H5::readData<T>(name() + ".h5", dsname);
    }

      /// @}

#endif


    /// @name Histogram reference data
    /// @{

    /// Get all reference data objects for this analysis
    const std::map<std::string, YODA::AnalysisObjectPtr>& refData() const {
      _cacheRefData();
      return _refdata;
    }

    /// Check if reference data object exists for a specific histo name
    bool hasRefData(const string& hname) const {
      _cacheRefData();
      return _refdata.count(hname);
    }

    /// Check if a reference data object exists for a numbered histo
    bool hasRefData(unsigned int datasetId, unsigned int xAxisId, unsigned int yAxisId) const {
      return hasRefData(mkAxisCode(datasetId, xAxisId, yAxisId));
    }


    /// Get reference data for a named histo
    ///
    /// @todo SFINAE to ensure that the type inherits from YODA::AnalysisObject?
    template <typename T = YODA::Estimate1D>
    const T& refData(const string& hname) const {
      _cacheRefData();
      MSG_TRACE("Using histo bin edges for " << name() << ":" << hname);
      if (!_refdata[hname]) {
        MSG_ERROR("Can't find reference histogram " << hname);
        throw Exception("Reference data " + hname + " not found.");
      }
      try {
        return dynamic_cast<T&>(*_refdata[hname]);
      }
      catch (...) {
        throw Exception("Expected type " + _refdata[hname]->type() + " for reference data \"" + hname
                        + "\".\n");
      }
    }


    /// Get reference data for a numbered histo
    ///
    /// @todo SFINAE to ensure that the type inherits from YODA::AnalysisObject?
    template <typename T = YODA::Estimate1D>
    const T& refData(unsigned int datasetId, unsigned int xAxisId, unsigned int yAxisId) const {
      const string hname = mkAxisCode(datasetId, xAxisId, yAxisId);
      return refData<T>(hname);
    }

    /// @}


    /// @defgroup analysis_cbook Counter booking
    ///
    /// @todo Add "tmp" flags to book in standard temporary paths
    ///
    /// @{

    /// Book a counter.
    CounterPtr& book(CounterPtr&, const std::string& name);

    /// Book a counter, using a path generated from the dataset and axis ID codes
    ///
    /// The paper, dataset and x/y-axis IDs will be used to build the histo name in the HepData standard way.
    CounterPtr& book(CounterPtr&, unsigned int datasetID, unsigned int xAxisID, unsigned int yAxisID);

    /// @}


    /// @name Estimate booking
    /// @{

    /// Book an estimate.
    Estimate0DPtr& book(Estimate0DPtr&, const std::string& name);

    /// Book an estimate, using a path generated from the dataset and axis ID codes
    ///
    /// The paper, dataset and x/y-axis IDs will be used to build the histo name in the HepData standard way.
    Estimate0DPtr& book(Estimate0DPtr&, unsigned int datasetID, unsigned int xAxisID, unsigned int yAxisID);


    /// @}

    /// @name BinnedDbn booking
    /// @{

    /// Book a ND histogram with @a nbins uniformly distributed across the range @a lower - @a upper .
    template <size_t DbnN, typename... AxisT, typename = YODA::enable_if_all_CAxisT<AxisT...>>
    BinnedDbnPtr<DbnN, AxisT...>& book(BinnedDbnPtr<DbnN, AxisT...>& ao,
                                       const std::string& name,
                                       const std::vector<size_t>& nbins,
                                       const std::vector<std::pair<double, double>>& loUpPairs) {
      if (nbins.size() != loUpPairs.size()) {
        throw RangeError("Vectors should have the same size!");
      }
      const string path = histoPath(name);

      YODA::BinnedDbn<DbnN, AxisT...> yao(nbins, loUpPairs, path);
      _setWriterPrecision(path, yao);

      return ao = registerAO(yao);
    }

    // Specialiation for 1D
    Histo1DPtr& book(Histo1DPtr& ao,
                     const std::string& name,
                     const size_t nbins,
                     const double lower,
                     const double upper) {
      return book(ao, name, vector<size_t>{nbins}, vector<pair<double, double>>{{lower, upper}});
    }
    //
    Profile1DPtr& book(Profile1DPtr& ao,
                       const std::string& name,
                       const size_t nbins,
                       const double lower,
                       const double upper) {
      return book(ao, name, vector<size_t>{nbins}, vector<pair<double, double>>{{lower, upper}});
    }

    // Specialiation for 2D
    Histo2DPtr& book(Histo2DPtr& ao,
                     const std::string& name,
                     const size_t nbinsX,
                     const double lowerX,
                     const double upperX,
                     const size_t nbinsY,
                     const double lowerY,
                     const double upperY) {
      return book(ao, name, vector<size_t>{nbinsX, nbinsY},
                  vector<pair<double, double>>{{lowerX, upperX}, {lowerY, upperY}});
    }
    //
    Profile2DPtr& book(Profile2DPtr& ao,
                       const std::string& name,
                       const size_t nbinsX,
                       const double lowerX,
                       const double upperX,
                       const size_t nbinsY,
                       const double lowerY,
                       const double upperY) {
      return book(ao, name, vector<size_t>{nbinsX, nbinsY},
                  vector<pair<double, double>>{{lowerX, upperX}, {lowerY, upperY}});
    }

    // Specialiation for 3D
    Histo3DPtr& book(Histo3DPtr& ao,
                     const std::string& name,
                     const size_t nbinsX,
                     const double lowerX,
                     const double upperX,
                     const size_t nbinsY,
                     const double lowerY,
                     const double upperY,
                     const size_t nbinsZ,
                     const double lowerZ,
                     const double upperZ) {
      return book(ao, name, vector<size_t>{nbinsX, nbinsY, nbinsZ},
                  vector<pair<double, double>>{{lowerX, upperX}, {lowerY, upperY}, {lowerZ, upperZ}});
    }
    //
    Profile3DPtr& book(Profile3DPtr& ao,
                       const std::string& name,
                       const size_t nbinsX,
                       const double lowerX,
                       const double upperX,
                       const size_t nbinsY,
                       const double lowerY,
                       const double upperY,
                       const size_t nbinsZ,
                       const double lowerZ,
                       const double upperZ) {
      return book(ao, name, vector<size_t>{nbinsX, nbinsY, nbinsZ},
                  vector<pair<double, double>>{{lowerX, upperX}, {lowerY, upperY}, {lowerZ, upperZ}});
    }

    /// Book a ND histogram with non-uniform bins defined by the vector of bin edges @a binedges .
    template <size_t DbnN, typename... AxisT>
    BinnedDbnPtr<DbnN, AxisT...>& book(BinnedDbnPtr<DbnN, AxisT...>& ao,
                                       const std::string& name,
                                       const std::vector<AxisT>&... binedges) {
      const string path = histoPath(name);
      YODA::BinnedDbn<DbnN, AxisT...> yao(binedges..., path);
      _setWriterPrecision(path, yao);

      return ao = registerAO(yao);
    }

    /// Book a ND histogram with non-uniform bins defined by the vector of bin edges @a binedges .
    template <size_t DbnN, typename... AxisT>
    BinnedDbnPtr<DbnN, AxisT...>& book(BinnedDbnPtr<DbnN, AxisT...>& ao,
                                       const std::string& name,
                                       const std::initializer_list<AxisT>&... binedges) {
      return book(ao, name, vector<AxisT>{binedges}...);
    }

    /// Book a ND histogram with binning from a reference scatter.
    template <size_t DbnN, typename... AxisT>
    BinnedDbnPtr<DbnN, AxisT...>& book(BinnedDbnPtr<DbnN, AxisT...>& ao,
                                       const std::string& name,
                                       const YODA::BinnedEstimate<AxisT...>& refest) {
      const string path = histoPath(name);

      YODA::BinnedDbn<DbnN, AxisT...> yao(refest.binning(), path);
      for (const string& a : yao.annotations()) {
        if (a != "Path") yao.rmAnnotation(a);
      }
      _setWriterPrecision(path, yao);
      return ao = registerAO(yao);
    }

    /// Book a ND histogram, using the binnings in the reference data histogram.
    template <size_t DbnN, typename... AxisT>
    BinnedDbnPtr<DbnN, AxisT...>& book(BinnedDbnPtr<DbnN, AxisT...>& ao, const std::string& name) {
      return book(ao, name, refData<YODA::BinnedEstimate<AxisT...>>(name));
    }

    /// Book a ND histogram, using the binnings in the reference data histogram.
    ///
    /// The paper, dataset and x/y-axis IDs will be used to build the histo name in the HepData standard way.
    template <size_t DbnN, typename... AxisT>
    BinnedDbnPtr<DbnN, AxisT...>& book(BinnedDbnPtr<DbnN, AxisT...>& ao,
                                       const unsigned int datasetID,
                                       const unsigned int xAxisID,
                                       const unsigned int yAxisID) {
      const string name = mkAxisCode(datasetID, xAxisID, yAxisID);
      return book(ao, name);
    }

    /// @}

    /// @name HistoGroup booking
    /// @{

    template <typename GroupAxisT, typename... AxisT>
    HistoGroupPtr<GroupAxisT, AxisT...>& book(HistoGroupPtr<GroupAxisT, AxisT...>& ao,
                                              const std::vector<GroupAxisT>& edges,
                                              const std::vector<std::string>& names) {
      ao = make_shared<HistoGroup<GroupAxisT, AxisT...>>(edges);
      if (ao->numBins() != names.size()) {
        throw RangeError("Binning and reference-data names don't match!");
      }
      for (auto& b : ao->bins()) {
        const string& refname = names[b.index() - 1];
        book(b, refname, refData<YODA::BinnedEstimate<AxisT...>>(refname));
      }
      return ao;
    }

    template <typename GroupAxisT, typename... AxisT>
    HistoGroupPtr<GroupAxisT, AxisT...>& book(HistoGroupPtr<GroupAxisT, AxisT...>& ao,
                                              const std::vector<GroupAxisT>& edges) {
      return ao = make_shared<HistoGroup<GroupAxisT, AxisT...>>(edges);
    }

    template <typename GroupAxisT, typename... AxisT>
    HistoGroupPtr<GroupAxisT, AxisT...>& book(HistoGroupPtr<GroupAxisT, AxisT...>& ao,
                                              std::initializer_list<GroupAxisT>&& edges) {
      return ao = make_shared<HistoGroup<GroupAxisT, AxisT...>>(std::move(edges));
    }

    /// @}

    /// @name BinnedEstimate booking
    /// @{

    /// Book a ND estimate with @a nbins uniformly distributed across the range @a lower - @a upper .
    template <typename... AxisT, typename = YODA::enable_if_all_CAxisT<AxisT...>>
    BinnedEstimatePtr<AxisT...>& book(BinnedEstimatePtr<AxisT...>& ao,
                                      const std::string& name,
                                      const std::vector<size_t>& nbins,
                                      const std::vector<std::pair<double, double>>& loUpPairs) {
      if (nbins.size() != loUpPairs.size()) {
        throw RangeError("Vectors should have the same size!");
      }
      const string path = histoPath(name);

      YODA::BinnedEstimate<AxisT...> yao(nbins, loUpPairs, path);
      _setWriterPrecision(path, yao);

      return ao = registerAO(yao);
    }


    // Specialiation for 1D
    Estimate1DPtr& book(Estimate1DPtr& ao,
                        const std::string& name,
                        const size_t nbins,
                        const double lower,
                        const double upper) {
      return book(ao, name, vector<size_t>{nbins}, vector<pair<double, double>>{{lower, upper}});
    }

    // Specialiation for 2D
    Estimate2DPtr& book(Estimate2DPtr& ao,
                        const std::string& name,
                        const size_t nbinsX,
                        const double lowerX,
                        const double upperX,
                        const size_t nbinsY,
                        const double lowerY,
                        const double upperY) {
      return book(ao, name, vector<size_t>{nbinsX, nbinsY},
                  vector<pair<double, double>>{{lowerX, upperX}, {lowerY, upperY}});
    }

    // Specialiation for 3D
    Estimate3DPtr& book(Estimate3DPtr& ao,
                        const std::string& name,
                        const size_t nbinsX,
                        const double lowerX,
                        const double upperX,
                        const size_t nbinsY,
                        const double lowerY,
                        const double upperY,
                        const size_t nbinsZ,
                        const double lowerZ,
                        const double upperZ) {
      return book(ao, name, vector<size_t>{nbinsX, nbinsY, nbinsZ},
                  vector<pair<double, double>>{{lowerX, upperX}, {lowerY, upperY}, {lowerZ, upperZ}});
    }

    /// Book a ND estimate with non-uniform bins defined by the vector of bin edges @a binedges .
    template <typename... AxisT>
    BinnedEstimatePtr<AxisT...>& book(BinnedEstimatePtr<AxisT...>& ao,
                                      const std::string& name,
                                      const std::vector<AxisT>&... binedges) {
      const string path = histoPath(name);
      YODA::BinnedEstimate<AxisT...> yao(binedges..., path);
      _setWriterPrecision(path, yao);

      return ao = registerAO(yao);
    }

    /// Book a ND estimate with non-uniform bins defined by the vector of bin edges @a binedges .
    template <typename... AxisT>
    BinnedEstimatePtr<AxisT...>& book(BinnedEstimatePtr<AxisT...>& ao,
                                      const std::string& name,
                                      const std::initializer_list<AxisT>&... binedges) {
      return book(ao, name, vector<AxisT>{binedges}...);
    }

    /// Book a ND estimate, using the binnings in the reference data histogram.
    template <typename... AxisT>
    BinnedEstimatePtr<AxisT...>& book(BinnedEstimatePtr<AxisT...>& ao, const std::string& name) {

      const string path = histoPath(name);
      YODA::BinnedEstimate<AxisT...> yao;
      try {
        yao = YODA::BinnedEstimate<AxisT...>(refData<YODA::BinnedEstimate<AxisT...>>(name).binning());
      }
      catch (...) {
        MSG_DEBUG("Couldn't retrieve reference binning, continue with nullary AO constructor.");
      }
      yao.setPath(path);
      _setWriterPrecision(path, yao);
      return ao = registerAO(yao);
    }

    /// Book a ND estimate, using the binnings in the reference data histogram.
    ///
    /// The paper, dataset and x/y-axis IDs will be used to build the histo name in the HepData standard way.
    template <typename... AxisT>
    BinnedEstimatePtr<AxisT...>& book(BinnedEstimatePtr<AxisT...>& ao,
                                      const unsigned int datasetID,
                                      const unsigned int xAxisID,
                                      const unsigned int yAxisID) {
      const string name = mkAxisCode(datasetID, xAxisID, yAxisID);
      return book(ao, name);
    }

    /// @}


    /// @name Scatter booking
    /// @{

    /// @brief Book a N-dimensional data point set with the given name.
    ///
    /// @note Unlike histogram booking, scatter booking by default makes no
    /// attempt to use reference data to pre-fill the data object. If you want
    /// this, which is sometimes useful e.g. when the x-position is not really
    /// meaningful and can't be extracted from the data, then set the @a
    /// copy_pts parameter to true. This creates points to match the reference
    /// data's x values and errors, but with the y values and errors zeroed...
    /// assuming that there is a reference histo with the same name: if there
    /// isn't, an exception will be thrown.
    template <size_t N>
    ScatterNDPtr<N>& book(ScatterNDPtr<N>& snd, const string& name, const bool copy_pts = false) {
      const string path = histoPath(name);
      YODA::ScatterND<N> scat(path);
      if (copy_pts) {
        const YODA::ScatterND<N> ref = refData<YODA::EstimateND<N - 1>>(name).mkScatter();
        for (YODA::PointND<N> p : ref.points()) {
          p.setVal(N - 1, 0.0);
          p.setErr(N - 1, 0.0);
          scat.addPoint(std::move(p));
        }
      }
      _setWriterPrecision(path, scat);
      return snd = registerAO(scat);
    }

    /// @brief Book a N-dimensional data point set, using the binnings in the reference data histogram.
    ///
    /// The paper, dataset and x/y-axis IDs will be used to build the histo name in the HepData standard way.
    ///
    /// @note Unlike histogram booking, scatter booking by default makes no
    /// attempt to use reference data to pre-fill the data object. If you want
    /// this, which is sometimes useful e.g. when the x-position is not really
    /// meaningful and can't be extracted from the data, then set the @a
    /// copy_pts parameter to true. This creates points to match the reference
    /// data's x values and errors, but with the y values and errors zeroed.
    template <size_t N>
    ScatterNDPtr<N>& book(ScatterNDPtr<N>& snd,
                          const unsigned int datasetID,
                          const unsigned int xAxisID,
                          const unsigned int yAxisID,
                          const bool copy_pts = false) {
      const string axisCode = mkAxisCode(datasetID, xAxisID, yAxisID);
      return book(snd, axisCode, copy_pts);
    }

    /// @brief Book a N-dimensional data point set with equally spaced x-points in a range.
    ///
    /// The y values and errors will be set to 0.
    ///
    /// @todo Remove this when we switch to BinnedEstimates
    Scatter2DPtr& book(Scatter2DPtr& snd,
                       const string& name,
                       const size_t npts,
                       const double lower,
                       const double upper) {
      const string path = histoPath(name);

      Scatter2D scat(path);
      const double binwidth = (upper - lower) / npts;
      for (size_t pt = 0; pt < npts; ++pt) {
        const double bincentre = lower + (pt + 0.5) * binwidth;
        scat.addPoint(bincentre, 0, binwidth / 2.0, 0);
      }
      _setWriterPrecision(path, scat);

      return snd = registerAO(scat);
    }
    //
    Scatter3DPtr& book(Scatter3DPtr& snd,
                       const string& name,
                       const size_t nptsX,
                       const double lowerX,
                       const double upperX,
                       const size_t nptsY,
                       const double lowerY,
                       const double upperY) {
      const string path = histoPath(name);

      Scatter3D scat(path);
      const double xbinwidth = (upperX - lowerX) / nptsX;
      const double ybinwidth = (upperY - lowerY) / nptsY;
      for (size_t xpt = 0; xpt < nptsX; ++xpt) {
        const double xbincentre = lowerX + (xpt + 0.5) * xbinwidth;
        for (size_t ypt = 0; ypt < nptsY; ++ypt) {
          const double ybincentre = lowerY + (ypt + 0.5) * ybinwidth;
          scat.addPoint(xbincentre, ybincentre, 0, 0.5 * xbinwidth, 0.5 * ybinwidth, 0);
        }
      }
      _setWriterPrecision(path, scat);

      return snd = registerAO(scat);
    }

    /// @brief Book a 2-dimensional data point set based on provided contiguous "bin edges".
    ///
    /// The y values and errors will be set to 0.
    ///
    /// @todo Remove this when we switch to BinnedEstimates
    Scatter2DPtr& book(Scatter2DPtr& snd, const string& name, const std::vector<double>& binedges) {
      const string path = histoPath(name);

      Scatter2D scat(path);
      for (size_t pt = 0; pt < binedges.size() - 1; ++pt) {
        const double bincentre = (binedges[pt] + binedges[pt + 1]) / 2.0;
        const double binwidth = binedges[pt + 1] - binedges[pt];
        scat.addPoint(bincentre, 0, binwidth / 2.0, 0);
      }
      _setWriterPrecision(path, scat);

      return snd = registerAO(scat);
    }
    //
    Scatter3DPtr& book(Scatter3DPtr& snd,
                       const string& name,
                       const std::vector<double>& binedgesX,
                       const std::vector<double>& binedgesY) {
      const string path = histoPath(name);

      Scatter3D scat(path);
      for (size_t xpt = 0; xpt < binedgesX.size() - 1; ++xpt) {
        const double xbincentre = (binedgesX[xpt] + binedgesX[xpt + 1]) / 2.0;
        const double xbinwidth = binedgesX[xpt + 1] - binedgesX[xpt];
        for (size_t ypt = 0; ypt < binedgesY.size() - 1; ++ypt) {
          const double ybincentre = (binedgesY[ypt] + binedgesY[ypt + 1]) / 2.0;
          const double ybinwidth = binedgesY[ypt + 1] - binedgesY[ypt];
          scat.addPoint(xbincentre, ybincentre, 0, 0.5 * xbinwidth, 0.5 * ybinwidth, 0);
        }
      }
      _setWriterPrecision(path, scat);

      return snd = registerAO(scat);
    }

    /// Book a 2-dimensional data point set with x-points from an existing scatter and a new path.
    template <size_t N>
    ScatterNDPtr<N>& book(ScatterNDPtr<N>& snd, const string& name, const YODA::ScatterND<N>& refscatter) {
      const string path = histoPath(name);

      YODA::ScatterND<N> scat(refscatter, path);
      for (const string& a : scat.annotations()) {
        if (a != "Path") scat.rmAnnotation(a);
      }
      _setWriterPrecision(path, scat);

      return snd = registerAO(scat);
    }

    /// @}

    /// @defgroup Cutflow booking
    /// @{

    /// Book a Cutflow object defined by the vector of @a edges
    CutflowPtr& book(CutflowPtr& ao, const string& name, const std::vector<std::string>& edges) {
      const string path = histoPath(name);
      Cutflow yao(edges, path);
      _setWriterPrecision(path, yao);
      return ao = registerAO(yao);
    }

    /// Book a Cutflow object defined by the vector of @a edges
    CutflowPtr& book(CutflowPtr& ao, const string& name, const std::initializer_list<std::string>& edges) {
      return book(ao, name, vector<std::string>{edges});
    }

    /// @}

    /// @name Cutflows booking
    /// @{

    CutflowsPtr& book(CutflowsPtr& ao,
                      const std::vector<std::string>& edges,
                      const std::vector<std::vector<std::string>>& innerEdges) {
      ao = make_shared<Cutflows>(edges);
      if (ao->numBins() != innerEdges.size()) {
        throw RangeError("Outer and Inner edges don't match");
      }
      for (auto& b : ao->bins()) {
        book(b, b.xEdge(), innerEdges[b.index() - 1]);
      }
      return ao;
    }

    CutflowsPtr& book(CutflowsPtr& ao, const std::vector<std::string>& edges) {
      return ao = make_shared<Cutflows>(edges);
    }

    CutflowsPtr& book(CutflowsPtr& ao, std::initializer_list<std::string>&& edges) {
      return ao = make_shared<Cutflows>(std::move(edges));
    }

    /// @}


    /// @name Virtual helper function to allow classes deriving
    /// from Analysis (e.g. CumulantAnalysis) to load external
    /// raw AOs into their local AOs (needed in heavy-ion land).
    virtual void rawHookIn(YODA::AnalysisObjectPtr yao) {
      (void)yao; // suppress unused variable warning
    }

    /// @name Virtual helper function to allow classes deriving from
    /// Analysis (e.g. CumulantAnalysis) to fiddle with raw AOs
    /// post-finalize/before writing them out (needed in heavy-ion land).
    virtual void rawHookOut(const vector<MultiplexAOPtr>& raos, size_t iW) {
      (void)raos; // suppress unused variable warning
      (void)iW;   // suppress unused variable warning
    }


  public:

    /// @name Accessing options for this Analysis instance.
    /// @{

    /// Return the map of all options given to this analysis.
    const std::map<std::string, std::string>& options() const {
      return _options;
    }

    /// Get an option for this analysis instance as a string.
    std::string getOption(std::string optname, string def = "") const {
      if (_options.find(optname) != _options.end()) return _options.find(optname)->second;
      return def;
    }

    /// @brief Sane overload for literal character strings (which don't play well with stringstream)
    ///
    /// Note this isn't a template specialisation, because we can't return a non-static
    /// char*, and T-as-return-type is built into the template function definition.
    std::string getOption(std::string optname, const char* def) {
      return getOption<std::string>(optname, def);
    }

    /// @brief Get an option for this analysis instance converted to a specific type
    ///
    /// The return type is given by the specified @a def value, or by an explicit template
    /// type-argument, e.g. getOption<double>("FOO", 3).
    ///
    /// @warning To avoid accidents, strings not convertible to the requested
    /// type will throw a Rivet::ReadError exception.
    template <typename T>
    T getOption(std::string optname, T def) const {
      if (_options.find(optname) == _options.end()) return def;
      std::stringstream ss;
      ss.exceptions(std::ios::failbit);
      T ret;
      ss << _options.find(optname)->second;
      try {
        ss >> ret;
      }
      catch (...) {
        throw ReadError("Could not read user-provided option into requested type");
      }
      return ret;
    }

    /// @brief Get an option for this analysis instance converted to a bool
    ///
    /// Specialisation for bool, to allow use of "yes/no", "true/false"
    /// and "on/off" strings, with fallback casting to bool based on int
    /// value. An empty value will be treated as false.
    ///
    /// @warning To avoid accidents, strings not matching one of the above
    /// patterns will throw a Rivet::ReadError exception.
    ///
    /// @todo Make this a template-specialisation... needs to be outside the class body?
    // template<>
    // bool getOption<bool>(std::string optname, bool def) const {
    bool getOption(std::string optname, bool def) const {
      if (_options.find(optname) == _options.end()) return def;
      const std::string val = getOption(optname);
      const std::string lval = toLower(val);
      if (lval.empty()) return false;
      if (lval == "true" || lval == "yes" || lval == "on") return true;
      if (lval == "false" || lval == "no" || lval == "off") return false;
      return bool(getOption<int>(optname, 0));
    }

    /// @}


    /// @name Booking heavy ion features
    /// @{

    /// @brief Book a CentralityProjection
    ///
    /// Using a SingleValueProjection, @a proj, giving the value of an
    /// experimental observable to be used as a centrality estimator,
    /// book a CentralityProjection based on the experimentally
    /// measured pecentiles of this observable (as given by the
    /// reference data for the @a calHistName histogram in the @a
    /// calAnaName analysis. If a preloaded file with the output of a
    /// run using the @a calAnaName analysis contains a valid
    /// generated @a calHistName histogram, it will be used as an
    /// optional percentile binning. Also if this preloaded file
    /// contains a histogram with the name @a calHistName with an
    /// appended "_IMP" This histogram will be used to add an optional
    /// centrality percentile based on the generated impact
    /// parameter. If @a increasing is true, a low (high) value of @a proj
    /// is assumed to correspond to a more peripheral (central) event.
    const CentralityProjection& declareCentrality(const SingleValueProjection& proj,
                                                  string calAnaName,
                                                  string calHistName,
                                                  const string projName,
                                                  PercentileOrder pctorder = PercentileOrder::DECREASING);


    /// @brief Book a Percentile Multiplexer around AnalysisObjects.
    ///
    /// Based on a previously registered CentralityProjection named @a
    /// projName book one AnalysisObject for each @a centralityBin and
    /// name them according to the corresponding code in the @a ref
    /// vector.
    template <typename T>
    Percentile<T> book(const string& projName,
                       const vector<pair<double, double>>& centralityBins,
                       const vector<tuple<size_t, size_t, size_t>>& ref) {

      using RefT = typename ReferenceTraits<T>::RefT;
      using WrapT = MultiplexPtr<Multiplexer<T>>;

      Percentile<T> pctl(this, projName);

      const size_t nCent = centralityBins.size();
      for (size_t iCent = 0; iCent < nCent; ++iCent) {
        const string axisCode = mkAxisCode(std::get<0>(ref[iCent]), std::get<1>(ref[iCent]),
                                           std::get<2>(ref[iCent]));
        const RefT& refscatter = refData<RefT>(axisCode);

        WrapT wtf(_weightNames(), T(refscatter, histoPath(axisCode)));
        wtf = addAnalysisObject(wtf);

        CounterPtr cnt(_weightNames(), Counter(histoPath("TMP/COUNTER/" + axisCode)));
        cnt = addAnalysisObject(cnt);

        pctl.add(wtf, cnt, centralityBins[iCent]);
      }
      return pctl;
    }


    // /// @brief Book Percentile Multiplexers around AnalysisObjects.
    // ///
    // /// Based on a previously registered CentralityProjection named @a
    // /// projName book one (or several) AnalysisObject(s) named
    // /// according to @a ref where the x-axis will be filled according
    // /// to the percentile output(s) of the @projName.
    // ///
    // /// @todo Convert to just be called book() cf. others
    // template <class T>
    // PercentileXaxis<T> bookPercentileXaxis(string projName,
    //                                        tuple<int, int, int> ref) {

    //   typedef typename ReferenceTraits<T>::RefT RefT;
    //   typedef MultiplexPtr<Multiplexer<T>> WrapT;

    //   PercentileXaxis<T> pctl(this, projName);

    //   const string axisCode = mkAxisCode(std::get<0>(ref),
    //                                      std::get<1>(ref),
    //                                      std::get<2>(ref));
    //   const RefT & refscatter = refData<RefT>(axisCode);

    //   WrapT wtf(_weightNames(), T(refscatter, histoPath(axisCode)));
    //   wtf = addAnalysisObject(wtf);

    //   CounterPtr cnt(_weightNames(), Counter());
    //   cnt = addAnalysisObject(cnt);

    //   pctl.add(wtf, cnt);
    //   return pctl;
    // }

    /// @}


  private:

    // Functions that have to be defined in the .cc file to avoid circular #includes

    /// Get the list of weight names from the handler
    vector<string> _weightNames() const;

    /// Get the list of weight names from the handler
    YODA::AnalysisObjectPtr _getPreload(const string& name) const;

    /// Get an AO from another analysis
    MultiplexAOPtr _getOtherAnalysisObject(const std::string& ananame, const std::string& name);

    /// Check that analysis objects aren't being booked/registered outside the init stage
    void _checkBookInit() const;

    /// Check if we are in the init stage.
    bool _inInit() const;

    /// Check if we are in the finalize stage.
    bool _inFinalize() const;

    /// Set DP annotation
    template <typename YODAT>
    void _setWriterPrecision(const string& path, YODAT& yao) {
      const string re = _info->writerDoublePrecision();
      if (re != "") {
        std::smatch match;
        const bool needsDP = std::regex_search(path, match, std::regex(re));
        if (needsDP) yao.setAnnotation("WriterDoublePrecision", "1");
      }
    }


  private:

    /// To be used in finalize context only
    class CounterAdapter {
    public:

      CounterAdapter(double x)
          : x_(x) { }

      CounterAdapter(const YODA::Counter& c)
          : x_(c.val()) { }

      CounterAdapter(const YODA::Estimate& e)
          : x_(e.val()) { }

      CounterAdapter(const YODA::Scatter1D& s)
          : x_(s.points()[0].x()) {
        if (s.numPoints() != 1) throw RangeError("Can only scale by a single value.");
      }

      operator double() const {
        return x_;
      }

    private:

      double x_;
    };


  public:

    double dbl(double x) {
      return x;
    }
    double dbl(const YODA::Counter& c) {
      return c.val();
    }
    double dbl(const YODA::Estimate0D& e) {
      return e.val();
    }
    double dbl(const YODA::Scatter1D& s) {
      if (s.numPoints() != 1) throw RangeError("Only scatter with single value supported.");
      return s.points()[0].x();
    }


  protected:

    /// @name Analysis object manipulation
    ///
    /// @{

    /// Multiplicatively scale the given AnalysisObject, @a ao, by factor @a factor.
    template <typename T>
    void scale(MultiplexPtr<Multiplexer<T>>& ao, CounterAdapter factor) {
      if (!ao) {
        MSG_WARNING("Failed to scale AnalysisObject=NULL in analysis "
                    << name() << " (scale=" << double(factor) << ")");
        return;
      }
      if (std::isnan(double(factor)) || std::isinf(double(factor))) {
        MSG_WARNING("Failed to scale AnalysisObject=" << ao->path() << " in analysis: " << name()
                                                      << " (invalid scale factor = " << double(factor)
                                                      << ")");
        factor = 0;
      }
      MSG_TRACE("Scaling AnalysisObject " << ao->path() << " by factor " << double(factor));
      try {
        if constexpr (isFillable<T>::value) {
          ao->scaleW(factor);
        }
        else {
          ao->scale(factor);
        }
      }
      catch (YODA::Exception& we) {
        MSG_WARNING("Could not scale AnalysisObject " << ao->path());
        return;
      }
    }

    /// Multiplicatively scale the given histogram group, @a group, by factor @a factor.
    template <typename GroupAxisT, typename... AxisT>
    void scale(HistoGroupPtr<GroupAxisT, AxisT...>& group, CounterAdapter factor) {
      if (!group) {
        MSG_WARNING("Failed to scale AnalysisObject=NULL in analysis "
                    << name() << " (scale=" << double(factor) << ")");
        return;
      }
      if (std::isnan(double(factor)) || std::isinf(double(factor))) {
        MSG_WARNING("Failed to scale histo group in analysis: " << name() << " (invalid scale factor = "
                                                                << double(factor) << ")");
        factor = 0;
      }
      MSG_TRACE("Scaling histo group by factor " << double(factor));
      try {
        group->scaleW(factor);
      }
      catch (YODA::Exception& we) {
        MSG_WARNING("Could not scale histo group.");
        return;
      }
    }

    /// Multiplicatively scale the given histogram group, @a group, by factors @a factors.
    template <typename GroupAxisT, typename... AxisT>
    void scale(HistoGroupPtr<GroupAxisT, AxisT...>& group, const vector<double>& factors) {
      if (!group) {
        MSG_WARNING("Failed to scale AnalysisObject=NULL in analysis " << name());
        return;
      }
      if (group->numBins(true) != factors.size()) {
        throw RangeError(name() + ": Number of scale factors does not match group binning");
        return;
      }
      for (auto& b : group->bins(true)) {
        if (!b.get()) continue;
        double factor = factors[b.index()];
        if (std::isnan(factor) || std::isinf(factor)) {
          MSG_WARNING("Failed to scale componment of histo group in analysis: "
                      << name() << " (invalid scale factor = " << factor << ")");
          factor = 0;
        }
        MSG_TRACE("Scaling histo group element by factor " << factor);
        try {
          b->scaleW(factor);
        }
        catch (YODA::Exception& we) {
          MSG_WARNING("Could not scale component of histo group.");
        }
      }
    }

    /// Multiplicatively scale the cutflow group, @a group, by factor @a factor.
    void scale(CutflowsPtr& group, CounterAdapter factor) {
      if (!group) {
        MSG_WARNING("Failed to scale AnalysisObject=NULL in analysis "
                    << name() << " (scale=" << double(factor) << ")");
        return;
      }
      if (std::isnan(double(factor)) || std::isinf(double(factor))) {
        MSG_WARNING("Failed to scale histo group in analysis: " << name() << " (invalid scale factor = "
                                                                << double(factor) << ")");
        factor = 0;
      }
      MSG_TRACE("Scaling histo group by factor " << double(factor));
      try {
        group->scale(factor);
      }
      catch (YODA::Exception& we) {
        MSG_WARNING("Could not scale histo group.");
        return;
      }
    }

    /// Iteratively scale the AOs in the map @a aos, by factor @a factor.
    template <typename T, typename U>
    void scale(std::map<T, U>& aos, CounterAdapter factor) {
      for (auto& item : aos) scale(item.second, factor);
    }

    /// Iteratively scale the AOs in the iterable @a aos, by factor @a factor.
    template <typename AORange, typename = std::enable_if_t<YODA::isIterable<AORange>>>
    void scale(AORange& aos, CounterAdapter factor) {
      for (auto& ao : aos) scale(ao, factor);
    }

    /// Iteratively scale the AOs in the initialiser list @a aos, by factor @a factor.
    template <typename T>
    void scale(std::initializer_list<T> aos, CounterAdapter factor) {
      for (auto& ao : std::vector<T>{aos}) scale(ao, factor);
    }

    /// Iteratively scale the AOs in the map @a aos, by factors @a factors.
    template <typename T, typename U>
    void scale(std::map<T, U>& aos, const vector<double>& factors) {
      for (auto& item : aos) scale(item.second, factors);
    }

    /// Iteratively scale the AOs in the iterable @a aos, by factors @a factors.
    template <typename AORange, typename = std::enable_if_t<YODA::isIterable<AORange>>>
    void scale(AORange& aos, const vector<double>& factors) {
      for (auto& ao : aos) scale(ao, factors);
    }

    /// Iteratively scale the AOs in the initialiser list @a aos, by factors @a factors.
    template <typename T>
    void scale(std::initializer_list<T> aos, const vector<double>& factors) {
      for (auto& ao : std::vector<T>{aos}) scale(ao, factors);
    }

    /// Scale the given histogram group, @a group, by the group axis width
    template <typename GroupAxisT, typename... AxisT>
    void divByGroupWidth(HistoGroupPtr<GroupAxisT, AxisT...>& group) {
      if (!group) {
        MSG_WARNING("Failed to scale HistoGroup=NULL in analysis " << name() << " by group axis width");
        return;
      }
      group->divByGroupWidth();
    }

    /// Iteratively scale the HistoGroups in the map @a aos, by the group axis width
    template <typename T, typename U>
    void divByGroupWidth(std::map<T, U>& aos) {
      for (auto& item : aos) divByGroupWidth(item.second);
    }

    /// Iteratively scale the HistoGroups in the iterable @a aos, by the group axis width
    template <typename AORange, typename = std::enable_if_t<YODA::isIterable<AORange>>>
    void divByGroupWidth(AORange& aos) {
      for (auto& ao : aos) divByGroupWidth(ao);
    }

    /// Iteratively scale the HistoGroups in the initialiser list @a aos, by the group axis width
    template <typename T>
    void divByGroupWidth(std::initializer_list<T> aos) {
      for (auto& ao : std::vector<T>{aos}) divByGroupWidth(ao);
    }


    /// Normalize the given analysis object, @a ao to a target @a norm.
    template <size_t DbnN, typename... AxisT>
    void normalize(BinnedDbnPtr<DbnN, AxisT...> ao,
                   const CounterAdapter norm = 1.0,
                   const bool includeoverflows = true) {
      if (!ao) {
        MSG_WARNING("Failed to normalize histo=NULL in analysis " << name() << " (norm=" << double(norm)
                                                                  << ")");
        return;
      }
      MSG_TRACE("Normalizing histo " << ao->path() << " to " << double(norm));
      try {
        const double hint = ao->integral(includeoverflows);
        if (hint == 0) {
          MSG_DEBUG("Skipping histo with null area " << ao->path());
        }
        else {
          ao->normalize(norm, includeoverflows);
        }
      }
      catch (YODA::Exception& we) {
        MSG_WARNING("Could not normalize histo " << ao->path());
        return;
      }
    }

    /// Normalize each AO in the given histogram group, @a group to a target @a norm.
    template <typename GroupAxisT, typename... AxisT>
    void normalize(HistoGroupPtr<GroupAxisT, AxisT...> group,
                   const CounterAdapter norm = 1.0,
                   const bool includeoverflows = true) {
      if (!group) {
        MSG_WARNING("Failed to normalize histo=NULL in analysis " << name() << " (norm=" << double(norm)
                                                                  << ")");
        return;
      }
      MSG_TRACE("Normalizing histo group  to " << double(norm));
      try {
        const double hint = group->integral(includeoverflows);
        if (hint == 0) {
          MSG_DEBUG("Skipping histo group with null area.");
        }
        else {
          group->normalize(norm, includeoverflows);
        }
      }
      catch (YODA::Exception& we) {
        MSG_WARNING("Could not normalize histo group.");
        return;
      }
    }


    /// Iteratively normalise the AOs in the iterable @a iter, by factor @a factor.
    template <typename AORange, typename = std::enable_if_t<YODA::isIterable<AORange>>>
    void normalize(AORange& aos, const CounterAdapter norm = 1.0, const bool includeoverflows = true) {
      for (auto& ao : aos) normalize(ao, norm, includeoverflows);
    }

    /// Iteratively normalise the AOs in the initialiser list @a iter to a target @a norm.
    template <typename T>
    void normalize(std::initializer_list<T>&& aos,
                   const CounterAdapter norm = 1.0,
                   const bool includeoverflows = true) {
      for (auto& ao : aos) normalize(ao, norm, includeoverflows);
    }

    /// Iteratively normalise the AOs in the map @a aos to a target @a norm.
    template <typename T, typename U>
    void normalize(std::map<T, U>& aos, //BinnedDbnPtr<DbnN, AxisT...>>& aos,
                   const CounterAdapter norm = 1.0,
                   const bool includeoverflows = true) {
      for (auto& item : aos) normalize(item.second, norm, includeoverflows);
    }

    /// Normalize the given histogram group, @a group to a target @a norm.
    template <typename GroupAxisT, typename... AxisT>
    void normalizeGroup(HistoGroupPtr<GroupAxisT, AxisT...> group,
                        const CounterAdapter norm = 1.0,
                        const bool includeoverflows = true) {
      if (!group) {
        MSG_WARNING("Failed to normalize histo=NULL in analysis " << name() << " (norm=" << double(norm)
                                                                  << ")");
        return;
      }
      MSG_TRACE("Normalizing histo group  to " << double(norm));
      try {
        const double hint = group->integral(includeoverflows);
        if (hint == 0) {
          MSG_DEBUG("Skipping histo group with null area.");
        }
        else {
          group->normalizeGroup(norm, includeoverflows);
        }
      }
      catch (YODA::Exception& we) {
        MSG_WARNING("Could not normalize histo group.");
        return;
      }
    }

    /// Iteratively normalise the HistoGroups in the iterable @a iter, by factor @a factor.
    template <typename AORange, typename = std::enable_if_t<YODA::isIterable<AORange>>>
    void normalizeGroup(AORange& aos, const CounterAdapter norm = 1.0, const bool includeoverflows = true) {
      for (auto& ao : aos) normalizeGroup(ao, norm, includeoverflows);
    }

    /// Iteratively normalise the HistoGroups in the initialiser list @a iter to a target @a norm.
    template <typename T>
    void normalizeGroup(std::initializer_list<T>&& aos,
                        const CounterAdapter norm = 1.0,
                        const bool includeoverflows = true) {
      for (auto& ao : aos) normalizeGroup(ao, norm, includeoverflows);
    }

    /// Iteratively normalise the HistoGroups in the map @a aos to a target @a norm.
    template <typename T, typename U>
    void normalizeGroup(std::map<T, U>& aos, //BinnedDbnPtr<DbnN, AxisT...>>& aos,
                        const CounterAdapter norm = 1.0,
                        const bool includeoverflows = true) {
      for (auto& item : aos) normalizeGroup(item.second, norm, includeoverflows);
    }


    /// Helper for histogram conversion to an inert estimate type
    ///
    /// @note Assigns to the (already registered) output estimate, @a est.
    /// Preserves the path information of the target.
    template <size_t DbnN, typename... AxisT>
    void barchart(BinnedDbnPtr<DbnN, AxisT...> ao, BinnedEstimatePtr<AxisT...> est) const {
      const string path = est->path();
      *est = ao->mkEstimate(path, "stats",
                            false); //< do NOT divide by bin area cf. a differential dsigma/dX histogram
    }

    /// Helper for counter division.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    void divide(CounterPtr c1, CounterPtr c2, Estimate0DPtr est) const;

    /// Helper for histogram division with raw YODA objects.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    void divide(const YODA::Counter& c1, const YODA::Counter& c2, Estimate0DPtr est) const;

    /// Helper for counter division.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    void divide(Estimate0DPtr e1, Estimate0DPtr e2, Estimate0DPtr est) const;

    /// Helper for estimate division with raw YODA objects.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    void divide(const YODA::Estimate0D& e1, const YODA::Estimate0D& e2, Estimate0DPtr est) const;


    /// Helper for histogram division.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    template <size_t DbnN, typename... AxisT>
    void divide(const YODA::BinnedDbn<DbnN, AxisT...>& h1,
                const YODA::BinnedDbn<DbnN, AxisT...>& h2,
                BinnedEstimatePtr<AxisT...> est) const {
      const string path = est->path();
      *est = h1 / h2;
      est->setPath(path);
    }
    //
    template <size_t DbnN, typename... AxisT>
    void divide(BinnedDbnPtr<DbnN, AxisT...> h1,
                BinnedDbnPtr<DbnN, AxisT...> h2,
                BinnedEstimatePtr<AxisT...> est) const {
      return divide(*h1, *h2, est);
    }

    /// Helper for binned estimate division.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    template <typename... AxisT>
    void divide(const YODA::BinnedEstimate<AxisT...>& e1,
                const YODA::BinnedEstimate<AxisT...>& e2,
                BinnedEstimatePtr<AxisT...> est) const {
      const string path = est->path();
      *est = e1 / e2;
      est->setPath(path);
    }
    //
    template <typename... AxisT>
    void divide(BinnedEstimatePtr<AxisT...> e1,
                BinnedEstimatePtr<AxisT...> e2,
                BinnedEstimatePtr<AxisT...> est) const {
      return divide(*e1, *e2, est);
    }


    /// Helper for counter efficiency calculation.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    void efficiency(CounterPtr c1, CounterPtr c2, Estimate0DPtr est) const {
      efficiency(*c1, *c2, est);
    }

    /// Helper for counter efficiency calculation.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    void efficiency(const YODA::Counter& c1, const YODA::Counter& c2, Estimate0DPtr est) const {
      const string path = est->path();
      *est = YODA::efficiency(c1, c2);
      est->setPath(path);
    }


    /// Helper for histogram efficiency calculation.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    template <size_t DbnN, typename... AxisT>
    void efficiency(const YODA::BinnedDbn<DbnN, AxisT...>& h1,
                    const YODA::BinnedDbn<DbnN, AxisT...>& h2,
                    BinnedEstimatePtr<AxisT...> est) const {
      const string path = est->path();
      *est = YODA::efficiency(h1, h2);
      est->setPath(path);
    }
    //
    template <size_t DbnN, typename... AxisT>
    void efficiency(BinnedDbnPtr<DbnN, AxisT...> h1,
                    BinnedDbnPtr<DbnN, AxisT...> h2,
                    BinnedEstimatePtr<AxisT...> est) const {
      efficiency(*h1, *h2, est);
    }


    /// Helper for estimate efficiency calculation.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    template <typename... AxisT>
    void efficiency(const YODA::BinnedEstimate<AxisT...>& e1,
                    const YODA::BinnedEstimate<AxisT...>& e2,
                    BinnedEstimatePtr<AxisT...> est) const {
      const string path = est->path();
      *est = YODA::efficiency(e1, e2);
      est->setPath(path);
    }
    //
    template <typename... AxisT>
    void efficiency(BinnedEstimatePtr<AxisT...> e1,
                    BinnedEstimatePtr<AxisT...> e2,
                    BinnedEstimatePtr<AxisT...> est) const {
      efficiency(*e1, *e2, est);
    }


    /// Helper for histogram asymmetry calculation.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    template <size_t DbnN, typename... AxisT>
    void asymm(const YODA::BinnedDbn<DbnN, AxisT...>& h1,
               const YODA::BinnedDbn<DbnN, AxisT...>& h2,
               BinnedEstimatePtr<AxisT...> est) const {
      const string path = est->path();
      *est = YODA::asymm(h1, h2);
      est->setPath(path);
    }
    //
    template <size_t DbnN, typename... AxisT>
    void asymm(BinnedDbnPtr<DbnN, AxisT...> h1,
               BinnedDbnPtr<DbnN, AxisT...> h2,
               BinnedEstimatePtr<AxisT...> est) const {
      asymm(*h1, *h2, est);
    }

    /// Helper for estimate asymmetry calculation.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    template <typename... AxisT>
    void asymm(const YODA::BinnedEstimate<AxisT...>& e1,
               const YODA::BinnedEstimate<AxisT...>& e2,
               BinnedEstimatePtr<AxisT...> est) const {
      const string path = est->path();
      *est = YODA::asymm(e1, e2);
      est->setPath(path);
    }
    //
    template <typename... AxisT>
    void asymm(BinnedEstimatePtr<AxisT...> e1,
               BinnedEstimatePtr<AxisT...> e2,
               BinnedEstimatePtr<AxisT...> est) const {
      asymm(*e1, *e2, est);
    }

    /// Helper for converting a differential histo to an integral one.
    ///
    /// @note Assigns to the (already registered) output estimate, @a est. Preserves the path information of the target.
    template <size_t DbnN, typename... AxisT>
    void integrate(const YODA::BinnedDbn<DbnN, AxisT...>& h, BinnedEstimatePtr<AxisT...> est) const {
      const string path = est->path();
      *est = mkIntegral(h);
      est->setPath(path);
    }
    //
    template <size_t DbnN, typename... AxisT>
    void integrate(BinnedDbnPtr<DbnN, AxisT...>& h, BinnedEstimatePtr<AxisT...> est) const {
      integrate(*h, est);
    }

    /// @}


  public:

    /// List of registered analysis data objects
    const vector<MultiplexAOPtr>& analysisObjects() const {
      return _analysisobjects;
    }


  protected:

    /// @name Data object registration, retrieval, and removal
    /// @{

    /// Get the default/nominal weight index
    size_t defaultWeightIndex() const;

    /// Get a preloaded YODA object.
    template <typename YODAT>
    shared_ptr<YODAT> getPreload(const string& path) const {
      return dynamic_pointer_cast<YODAT>(_getPreload(path));
    }


    /// Register a new data object, optionally read in preloaded data.
    template <typename YODAT>
    MultiplexPtr<Multiplexer<YODAT>> registerAO(const YODAT& yao) {
      using MultiplexerT = Multiplexer<YODAT>;
      using YODAPtrT = shared_ptr<YODAT>;
      using RAOT = MultiplexPtr<MultiplexerT>;

      if (!_inInit() && !_inFinalize()) {
        MSG_ERROR("Can't book objects outside of init() or finalize()");
        throw UserError(name() + ": Can't book objects outside of init() or finalize().");
      }

      // First check that we haven't booked this before.
      // This is allowed when booking in finalize: just warn in that case.
      // If in init(), throw an exception: it's 99.9% never going to be intentional.
      for (auto& waold : analysisObjects()) {
        if (yao.path() == waold.get()->basePath()) {
          const string msg = "Found double-booking of " + yao.path() + " in " + name();
          if (_inInit()) {
            MSG_ERROR(msg);
            throw LookupError(msg);
          }
          else {
            MSG_DEBUG(msg + ". Keeping previous booking");
          }
          return RAOT(dynamic_pointer_cast<MultiplexerT>(waold.get()));
        }
      }

      shared_ptr<MultiplexerT> wao = make_shared<MultiplexerT>();
      wao->_basePath = yao.path();
      YODAPtrT yaop = make_shared<YODAT>(yao);

      for (const string& weightname : _weightNames()) {
        // Create two YODA objects for each weight. Copy from
        // preloaded YODAs if present. First the finalized yoda:
        string finalpath = yao.path();
        if (weightname != "") finalpath += "[" + weightname + "]";
        YODAPtrT preload = getPreload<YODAT>(finalpath);
        if (preload) {
          if (!bookingCompatible(preload, yaop)) {
            /// @todo What about if/when we want to make the final objects the Scatter or binned persistent type?
            MSG_WARNING("Found incompatible pre-existing data object with same base path "
                        << finalpath << " for " << name());
            preload = nullptr;
          }
          else {
            MSG_TRACE("Using preloaded " << finalpath << " in " << name());
            wao->_final.push_back(make_shared<YODAT>(*preload));
          }
        }
        else {
          wao->_final.push_back(make_shared<YODAT>(yao));
          wao->_final.back()->setPath(finalpath);
        }

        // Then the raw filling yodas.
        string rawpath = "/RAW" + finalpath;
        preload = getPreload<YODAT>(rawpath);
        if (preload) {
          if (!bookingCompatible(preload, yaop)) {
            MSG_WARNING("Found incompatible pre-existing data object with same base path "
                        << rawpath << " for " << name());
            preload = nullptr;
          }
          else {
            MSG_TRACE("Using preloaded " << rawpath << " in " << name());
            wao->_persistent.push_back(make_shared<YODAT>(*preload));
          }
        }
        else {
          wao->_persistent.push_back(make_shared<YODAT>(yao));
          wao->_persistent.back()->setPath(rawpath);
        }
      }
      MultiplexPtr<MultiplexerT> ret(wao);

      ret.get()->unsetActiveWeight();
      if (_inFinalize()) {
        // If booked in finalize() we assume it is the first time
        // finalize is run.
        ret.get()->pushToFinal();
        ret.get()->setActiveFinalWeightIdx(0);
      }
      _analysisobjects.push_back(ret);

      return ret;
    }


    /// Register a data object in the histogram system
    template <typename AO = MultiplexAOPtr>
    AO addAnalysisObject(const AO& aonew) {
      _checkBookInit();

      for (const MultiplexAOPtr& ao : analysisObjects()) {

        // Check AO base-name first
        ao.get()->setActiveWeightIdx(defaultWeightIndex());
        aonew.get()->setActiveWeightIdx(defaultWeightIndex());
        if (ao->path() != aonew->path()) continue;

        // If base-name matches, check compatibility
        // NB. This evil is because dynamic_ptr_cast can't work on MultiplexPtr directly
        AO aoold = AO(dynamic_pointer_cast<typename AO::value_type>(ao.get())); //< OMG
        if (!aoold || !bookingCompatible(aonew, aoold)) {
          MSG_WARNING("Found incompatible pre-existing data object with same base path "
                      << aonew->path() << " for " << name());
          throw LookupError(
              "Found incompatible pre-existing data object with same base path during AO booking");
        }

        // Finally, check all weight variations
        for (size_t weightIdx = 0; weightIdx < _weightNames().size(); ++weightIdx) {
          aoold.get()->setActiveWeightIdx(weightIdx);
          aonew.get()->setActiveWeightIdx(weightIdx);
          if (aoold->path() != aonew->path()) {
            MSG_WARNING("Found incompatible pre-existing data object with different weight-path "
                        << aonew->path() << " for " << name());
            throw LookupError(
                "Found incompatible pre-existing data object with same weight-path during AO booking");
          }
        }

        // They're fully compatible: bind and return
        aoold.get()->unsetActiveWeight();
        MSG_TRACE("Bound pre-existing data object " << aoold->path() << " for " << name());
        return aoold;
      }

      // No equivalent found
      MSG_TRACE("Registered " << aonew->annotation("Type") << " " << aonew->path() << " for " << name());
      aonew.get()->unsetActiveWeight();

      _analysisobjects.push_back(aonew);
      return aonew;
    }

    /// Unregister a data object from the histogram system (by name)
    void removeAnalysisObject(const std::string& path);

    /// Unregister a data object from the histogram system (by pointer)
    void removeAnalysisObject(const MultiplexAOPtr& ao);

    /// Get a Rivet data object from the histogram system
    template <typename AO = MultiplexAOPtr>
    const AO getAnalysisObject(const std::string& aoname) const {
      for (const MultiplexAOPtr& ao : analysisObjects()) {
        ao.get()->setActiveWeightIdx(defaultWeightIndex());
        if (ao->path() == histoPath(aoname)) {
          // return dynamic_pointer_cast<AO>(ao);
          return AO(dynamic_pointer_cast<typename AO::value_type>(ao.get()));
        }
      }
      throw LookupError("Data object " + histoPath(aoname) + " not found");
    }


    // /// Get a data object from the histogram system
    // template <typename AO=YODA::AnalysisObject>
    // const std::shared_ptr<AO> getAnalysisObject(const std::string& name) const {
    //   foreach (const AnalysisObjectPtr& ao, analysisObjects()) {
    //     if (ao->path() == histoPath(name)) return dynamic_pointer_cast<AO>(ao);
    //   }
    //   throw LookupError("Data object " + histoPath(name) + " not found");
    // }

    // /// Get a data object from the histogram system (non-const)
    // template <typename AO=YODA::AnalysisObject>
    // std::shared_ptr<AO> getAnalysisObject(const std::string& name) {
    //   foreach (const AnalysisObjectPtr& ao, analysisObjects()) {
    //     if (ao->path() == histoPath(name)) return dynamic_pointer_cast<AO>(ao);
    //   }
    //   throw LookupError("Data object " + histoPath(name) + " not found");
    // }


    /// Get a data object from another analysis (e.g. preloaded
    /// calibration histogram).
    template <typename AO = MultiplexAOPtr>
    AO getAnalysisObject(const std::string& ananame, const std::string& aoname) {
      MultiplexAOPtr ao = _getOtherAnalysisObject(ananame, aoname);
      // return dynamic_pointer_cast<AO>(ao);
      return AO(dynamic_pointer_cast<typename AO::value_type>(ao.get()));
    }

    /// @}

    /// @defgroup Utility functions
    /// @{

    /// Avoid `FastJet::` scoping prefix
    template <typename... Args,
              typename CONTAINER,
              typename = std::enable_if_t<is_citerable_v<CONTAINER>, Jet>>
    static CONTAINER reclusterJets(const CONTAINER& jetsIn, Args&&... args) {
      return FastJets::reclusterJets(jetsIn, std::forward<Args>(args)...);
    }

    template <typename T, typename U, typename... Args>
    static std::map<T, U> reclusterJets(const std::map<T, U>& jetsMap, Args&&... args) {
      return FastJets::reclusterJets(jetsMap, std::forward<Args>(args)...);
    }

    template <JetAlg JETALG,
              typename... Args,
              typename CONTAINER,
              typename = std::enable_if_t<is_citerable_v<CONTAINER>, Jet>>
    static CONTAINER reclusterJets(const CONTAINER& jetsIn, Args&&... args) {
      return FastJets::reclusterJets<JETALG>(jetsIn, std::forward<Args>(args)...);
    }

    template <JetAlg JETALG, typename T, typename U, typename... Args>
    static std::map<T, U> reclusterJets(const std::map<T, U>& jetsMap, Args&&... args) {
      return FastJets::reclusterJets<JETALG>(jetsMap, std::forward<Args>(args)...);
    }

    /// @}


  private:

    /// Name passed to constructor (used to find .info analysis data file, and as a fallback)
    string _defaultname;

    /// Pointer to analysis metadata object
    unique_ptr<AnalysisInfo> _info;

    /// Storage of all plot objects
    /// @todo Make this a map for fast lookup by path?
    vector<MultiplexAOPtr> _analysisobjects;

    /// @name Cross-section variables
    /// @{
    double _crossSection;
    bool _gotCrossSection;
    /// @}

    /// The controlling AnalysisHandler object.
    AnalysisHandler* _analysishandler;

    /// The current event.
    const Event* _currentevent = nullptr;

    /// Collection of cached refdata to speed up many autobookings: the
    /// reference data file should only be read once.
    mutable std::map<std::string, YODA::AnalysisObjectPtr> _refdata;

    /// Options the (this instance of) the analysis
    map<string, string> _options;

    /// The string of options.
    string _optstring;


  private:

    /// @name Utility functions
    /// @{

    /// Get the reference data for this paper and cache it.
    void _cacheRefData() const;

    /// @}
  };


  // // Template specialisation for literal character strings (which don't play well with stringstream)
  // template<>
  // inline std::string Analysis::getOption(std::string optname, const char* def) {
  //   return getOption<std::string>(optname, def); //.c_str();
  // }


}


// Include definition of analysis plugin system so that analyses automatically see it when including Analysis.hh
#include "Rivet/AnalysisBuilder.hh"


/// @defgroup anamacros Analysis macros
/// @{

/// @def RIVET_DECLARE_PLUGIN
/// Preprocessor define to prettify the global-object plugin hook mechanism
#define RIVET_DECLARE_PLUGIN(clsname) ::Rivet::AnalysisBuilder<clsname> plugin_ ## clsname

/// @def RIVET_DECLARE_ALIASED_PLUGIN
/// Preprocessor define to prettify the global-object plugin hook mechanism, with an extra alias name for this analysis
#define RIVET_DECLARE_ALIASED_PLUGIN(clsname, alias) RIVET_DECLARE_PLUGIN(clsname)( #alias )

/// @def RIVET_DEFAULT_ANALYSIS_CTOR
/// Preprocessor define to prettify the awkward constructor, with a name-string argument
#define RIVET_DEFAULT_ANALYSIS_CTOR(clsname) clsname() : Analysis(# clsname) {}

/// @def RIVET_REGISTER_TYPE
/// Preprocessor define to prettify on-the-fly type registration
#define RIVET_REGISTER_TYPE(...) handler().registerType<__VA_ARGS__>()

/// @def RIVET_REGISTER_BINNED_SET
/// Preprocessor define to prettify on-the-fly type registration
#define RIVET_REGISTER_BINNED_SET(...) { \
    RIVET_REGISTER_TYPE(YODA::BinnedHisto<__VA_ARGS__>); \
    RIVET_REGISTER_TYPE(YODA::BinnedProfile<__VA_ARGS__>); \
    RIVET_REGISTER_TYPE(YODA::BinnedEstimate<__VA_ARGS__>); }

/// @}


#endif
