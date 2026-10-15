// -*- C++ -*-
//
// This file is part of YODA -- Yet more Objects for Data Analysis
// Copyright (C) 2008-2025 The YODA collaboration (see AUTHORS for details)
//
#ifndef YODA_BinnedEstimate_h
#define YODA_BinnedEstimate_h

#include "YODA/AnalysisObject.h"
#include "YODA/BinnedStorage.h"
#include "YODA/Estimate.h"
#include "YODA/Scatter.h"
#include "YODA/Transformation.h"
#include "YODA/Utils/BinnedUtils.h"
#include <regex>

#ifdef HAVE_HDF5
#include "YODA/Utils/H5Utils.h"
#endif

namespace YODA {


  /// @note Anonymous namespace to limit visibility to this file
  namespace {
    /// @brief Nullify bin uncertainty for discrete axes
    template<size_t axisN, typename BinT>
    std::pair<double, double> nullifyIfDisc(const BinT& /* b */, const double /* val */, std::false_type, const double null = 0.0) {
      return { null, null };
    }

    /// @brief Work out bin uncertainty with respect to
    /// central value for continuous axes
    template<size_t axisN, typename BinT>
    std::pair<double, double> nullifyIfDisc(const BinT& b, const double val, std::true_type, const double /* null */ = 0.0) {
      return { val - b.template min<axisN>(), b.template max<axisN>() - val };
    }

    /// @brief Unify bin interval for discrete axes
    template<size_t axisN, typename BinT>
    double unifyIfDisc(const BinT& /* b */, std::false_type, const double unity = 1.0) {
      return unity;
    }

    /// @brief Get bin width for continuous axes
    template<size_t axisN, typename BinT>
    double unifyIfDisc(const BinT& b, std::true_type, const double /* unity */ = 1.0) {
      return b.template width<axisN>();
    }

    /// @brief Return bin index for non-integral discrete axes
    template<size_t axisN, typename BinT>
    double coordPicker(const BinT& b, std::false_type, std::false_type) {
      return b.index();
    }

    /// @brief Return bin edge for integral discrete axes
    template<size_t axisN, typename BinT>
    double coordPicker(const BinT& b, std::true_type, std::false_type) {
      return b.template edge<axisN>();
    }
    /// @brief Return bin mid point for continuous axes
    template<size_t axisN, typename BinT>
    double coordPicker(const BinT& b, std::true_type, std::true_type) {
      return b.template mid<axisN>();
    }
  }


  /// Forward declaration
  template <typename... AxisT>
  class BinnedEstimate;

  /// @brief EstimateStorage convenience class based on BinnedStorage.
  ///
  /// @note We use this abstraction layer to implement the bulk once and only once.
  /// The user-facing BinnedEstimate type will inherit all its methods from this
  /// base class along with a few axis-specifc mixins.
  template<typename... AxisT>
  class EstimateStorage
      : public BinnedStorage<Estimate, AxisT...>,
        public AnalysisObject {
  public:

    using BaseT = BinnedStorage<Estimate, AxisT...>;
    using BinningT = typename BaseT::BinningT;
    using BinT = typename BaseT::BinT;
    using BinType = BinT;
    using AnalysisObject::operator =;

    /// @name Constructors
    /// @{

    /// @brief Nullary constructor for unique pointers etc.
    EstimateStorage(const std::string& path = "", const std::string& title = "")
        : BaseT(), AnalysisObject(mkTypeString<AxisT...>(), path, title) { }

    /// @brief Constructor giving explicit bin edges as rvalue reference.
    ///
    /// Discrete axes have as many edges as bins.
    /// Continuous axes have bins.size()+1 edges, the last one
    /// being the upper bound of the last bin.
    EstimateStorage(std::vector<AxisT>&&... binsEdges, const std::string& path = "", const std::string& title = "")
        : BaseT(Axis<AxisT>(std::move(binsEdges))...), AnalysisObject(mkTypeString<AxisT...>(), path, title) { }

    /// @brief Constructor giving explicit bin edges as lvalue reference.
    ///
    /// Discrete axes have as many edges as bins.
    /// Continuous axes have bins.size()+1 edges, the last one
    /// being the upper bound of the last bin.
    EstimateStorage(const std::vector<AxisT>&... binsEdges, const std::string& path = "", const std::string& title = "")
        : BaseT(Axis<AxisT>(binsEdges)...), AnalysisObject(mkTypeString<AxisT...>(), path, title) { }

    /// @brief Constructor giving explicit bin edges as initializer list.
    ///
    /// Discrete axes have as many edges as bins.
    /// Continuous axes have bins.size()+1 edges, the last one
    /// being the upper bound of the last bin.
    EstimateStorage(std::initializer_list<AxisT>&&... binsEdges, const std::string& path = "", const std::string& title = "")
        : BaseT(Axis<AxisT>(std::move(binsEdges))...), AnalysisObject(mkTypeString<AxisT...>(), path, title) { }

    /// @brief Constructor giving range and number of bins.
    template <typename EdgeT = double, typename = enable_if_all_CAxisT<EdgeT, AxisT...>>
    EstimateStorage(const std::vector<size_t>& nBins,
                    const std::vector<std::pair<EdgeT, EdgeT>>& limitsLowUp,
                    const std::string& path = "", const std::string& title = "")
        //: BaseT( BinningT(nBins, limitsLowUp, std::make_index_sequence<sizeof...(AxisT)>{}) ),
        : BaseT( _mkBinning(nBins, limitsLowUp, std::make_index_sequence<sizeof...(AxisT)>{}) ),
          AnalysisObject(mkTypeString<AxisT...>(), path, title) { }

    /// @brief Constructor given a binning type
    EstimateStorage(const BinningT& binning, const std::string& path = "", const std::string& title = "")
        : BaseT(binning), AnalysisObject(mkTypeString<AxisT...>(), path, title) { }

    /// @brief Constructor given an rvalue BinningT
    EstimateStorage(BinningT&& binning, const std::string& path = "", const std::string& title = "")
        : BaseT(std::move(binning)), AnalysisObject(mkTypeString<AxisT...>(), path, title) { }

    /// @brief Constructor given a scatter
    template <typename EdgeT = double, typename = enable_if_all_CAxisT<EdgeT, AxisT...>>
    EstimateStorage(const ScatterND<sizeof...(AxisT)+1>& s, const std::string& path = "", const std::string& title = "")
         : BaseT(_mkBinning(s, std::make_index_sequence<sizeof...(AxisT)>{})),
           AnalysisObject(mkTypeString<AxisT...>(), path, title) { }

    /// @brief Copy constructor
    ///
    /// @todo Also allow title setting from the constructor?
    EstimateStorage(const EstimateStorage& other, const std::string& path = "") : BaseT(other),
        AnalysisObject(mkTypeString<AxisT...>(), path!=""? path : other.path(), other, other.title()) { }

    /// @brief Move constructor
    ///
    /// @todo Also allow title setting from the constructor?
    EstimateStorage(EstimateStorage&& other, const std::string& path = "") : BaseT(std::move(other)),
        AnalysisObject(mkTypeString<AxisT...>(), path!=""? path : other.path(), other, other.title()) { }

    /// @brief Make a copy on the stack
    EstimateStorage clone() const noexcept {
      return EstimateStorage(*this);
    }

    /// @brief Make a copy on the heap
    EstimateStorage* newclone() const noexcept {
      return new EstimateStorage(*this);
    }

    /// @}


    /// @name I/O
    /// @{

  private:

    /// @brief Render information about this AO (private implementation)
    template<size_t... Is>
    void _renderYODA_aux(std::ostream& os, const int width, std::index_sequence<Is...>) const noexcept {

      // print bin edges
      BaseT::_binning._renderYODA(os);

      // Assemble union of error sources, as it's not guaranteed
      // that every bin has the same error breakdown
      const std::vector<std::string> labels = this->sources();
      if (labels.size()) {
        os << "ErrorLabels: [";
        for (size_t i = 0; i < labels.size(); ++i) {
          const std::string& src = labels[i];
          if (i)  os << ", ";
          os << std::quoted(src);
        }
        os << "]\n";
      }

      // column header: content types
      os << std::setw(width) << std::left << "# value" << "\t";
      const int errwidth = std::max(int(std::to_string(labels.size()).size()+7), width); // "errDn(" + src + ")"
      for (size_t i = 0; i < labels.size(); ++i) {
        const std::string& src = labels[i];
        if (src.empty()) {
          os << std::setw(errwidth) << std::left << "totalDn" << "\t"
             << std::setw(errwidth) << std::left << "totalUp" << "\t";
        }
        else {
          os << std::setw(errwidth) << std::left << ("errDn(" + std::to_string(i+1) + ")") << "\t"
             << std::setw(errwidth) << std::left << ("errUp(" + std::to_string(i+1) + ")") << "\t";
        }
      }
      os << "\n";

      for (const auto& b : BaseT::bins(true, true)) {
        os << std::setw(width) << std::left << b.val() << "\t"; // print value
        // print systs if available
        for (const std::string& src : labels) {
          if (!b.hasSource(src)) {
            os << std::setw(errwidth) << std::left << "---" << "\t"
               << std::setw(errwidth) << std::left << "---" << "\t";
            continue;
          }
          const auto& err = b.err(src);
          os << std::setw(errwidth) << std::left << err.first << "\t"
             << std::setw(errwidth) << std::left << err.second << "\t";
        }
        os << "\n";
      }
    }

  public:

    /// @brief Render information about this AO
    void _renderYODA(std::ostream& os, const int width = 13) const noexcept {
      _renderYODA_aux(os, width, std::make_index_sequence<sizeof...(AxisT)>{});
    }

    /// @brief Render scatter-like information about this AO
    void _renderFLAT(std::ostream& os, const int width = 13) const noexcept {
      const ScatterND<sizeof...(AxisT)+1> tmp = mkScatter();
      tmp._renderYODA(os, width);
    }

    #ifdef HAVE_HDF5

    /// @brief Extract error labels of this AO
    void _extractLabels(std::vector<std::string>& labels,
                        std::vector<size_t>& labelsizes) const noexcept {
      size_t nlabels = 0;
      for (const auto& b : BaseT::bins(true, true)) {
        std::vector<std::string> keys = b.sources();
        nlabels += keys.size()+1; //< +1 for length info itself
        labels.insert(std::end(labels),
                      std::make_move_iterator(std::begin(keys)),
                      std::make_move_iterator(std::end(keys)));
      }
      std::sort(labels.begin(), labels.end());
      labels.erase( std::unique(labels.begin(), labels.end()), labels.end() );
      labelsizes.emplace_back(std::move(nlabels));
    }

    /// @brief Extract axes edges of this AO into map of @a edges
    void _extractEdges(std::map<std::string, EdgeHandlerBasePtr>& edges,
                       const std::vector<std::string>& labels) const noexcept {

      using lenT = EdgeHandler<size_t>;
      using lenPtr = EdgeHandlerPtr<size_t>;
      const std::string lengthID("sizeinfo");
      lenPtr nedges = std::static_pointer_cast<lenT>(edges.find(lengthID)->second);

      auto extractEdges = [&edges, &binning = BaseT::_binning, &nedges](auto I) {

        using thisEdgeT = typename BinningT::template getEdgeT<I>;
        using thisHandlerT = EdgeHandler<thisEdgeT>;
        using thisHandlerPtr = EdgeHandlerPtr<thisEdgeT>;

        const std::string edgeID = std::string("edges_") + TypeID<thisEdgeT>::name();
        std::vector<thisEdgeT> tmp = binning.template edges<I>();
        nedges->extend({ tmp.size() });

        auto itr = edges.find(edgeID);
        if (itr != edges.cend()) {
          thisHandlerPtr edgeset = std::static_pointer_cast<thisHandlerT>(itr->second);
          edgeset->extend(std::move(tmp));
        }
        else {
          edges[edgeID] = std::make_shared<thisHandlerT>(std::move(tmp));
        }
      };
      MetaUtils::staticFor<sizeof...(AxisT)>(extractEdges);

      std::vector<size_t> masks = BaseT::_binning.maskedBins();
      nedges->extend({ masks.size() });
      nedges->extend(std::move(masks));

      const auto& itr = labels.cbegin();
      const auto& itrEnd = labels.cend();
      for (const auto& b : BaseT::bins(true, true)) {
        vector<string> keys = b.sources();
        nedges->extend({ keys.size() });
        for (const string& k : keys) {
          size_t dist = std::find(itr, itrEnd, k) - itr;
          nedges->extend({ dist });
        }
      }
    }

    #endif

    /// @}


    /// @name Transformations
    /// @{

    /// @brief Rescale as if all fill weights had been different by factor @a scalefactor.
    void scale(const double scalefactor) noexcept {
      setAnnotation("ScaledBy", annotation<double>("ScaledBy", 1.0) * scalefactor);
      for (auto& bin : BaseT::_bins) {
        bin.scale(scalefactor);
      }
    }


    /// @brief Merge every group of @a n bins, from start to end inclusive
    ///
    /// If the number of bins is not a multiple of @a n, the last @a m < @a n
    /// bins on the RHS will also be merged, as the closest possible approach to
    /// factor @n rebinning everywhere.
    ///
    /// @note Only visible bins are being rebinned. Underflow (index = 0) and
    /// overflow (index = numBins() + 1) are not included.
    ///
    /// @note Only supported for continuous axes
    template <size_t axisN, typename = std::enable_if_t<BinningT::template is_CAxis<axisN>::value>>
    void rebinBy(unsigned int n, size_t begin=1, size_t end=UINT_MAX) {
      if (n < 1)  throw UserError("Rebinning requested in groups of 0!");
      if (!begin) throw UserError("Visible bins start with index 1!");
      if (end > BaseT::numBinsAt(axisN)+1)  end = BaseT::numBinsAt(axisN) + 1;
      for (size_t m = begin; m < end; ++m) {
        if (m > BaseT::numBinsAt(axisN)+1) break; // nothing to be done
        const size_t myend = (m+n-1 < BaseT::numBinsAt(axisN)+1) ? m+n-1 : BaseT::numBinsAt(axisN);
        if (myend > m) {
          BaseT::template mergeBins<axisN>({m, myend});
          end -= myend-m; //< reduce upper index by the number of removed bins
        }
      }
    }

    /// @brief Overloaded alias for rebinBy
    ///
    /// @note Only supported for continuous axes
    template <size_t axisN, typename = std::enable_if_t<BinningT::template is_CAxis<axisN>::value>>
    void rebin(unsigned int n, size_t begin=1, size_t end=UINT_MAX) {
      rebinBy<axisN>(n, begin, end);
    }

    /// @brief Rebin to the given list of bin edges
    ///
    /// @note Only supported for continuous axes
    template <size_t axisN, typename = std::enable_if_t<BinningT::template is_CAxis<axisN>::value>>
    void rebinTo(const std::vector<typename BinningT::template getAxisT<axisN>::EdgeT>& newedges) {
      if (newedges.size() < 2)
        throw UserError("Requested rebinning to an edge list which defines no bins");
      using thisAxisT = typename BinningT::template getAxisT<axisN>;
      using thisEdgeT = typename thisAxisT::EdgeT;
      // get list of shared edges
      thisAxisT& oldAxis = BaseT::_binning.template axis<axisN>();
      const thisAxisT newAxis(std::move(newedges));
      const std::vector<thisEdgeT> eshared = oldAxis.sharedEdges(newAxis);
      if (eshared.size() != newAxis.edges().size())
        throw BinningError("Requested rebinning to incompatible edges");
      // loop over new lower bin edges (= first bin index of merge range)
      for (size_t begin = 0; begin < eshared.size() - 1; ++begin) {
        // find index of upper edge along old axis
        // (subtracting 1 gives index of last bin to be merged)
        size_t end = oldAxis.index(eshared[begin+1]) - 1;
        // if the current edge is the last visible edge before the overflow
        // merge the remaining bins into the overflow
        if (begin == newAxis.numBins(true)-1)  end = oldAxis.numBins(true)-1;
        // merge this range
        if (end > begin)  BaseT::template mergeBins<axisN>({begin, end});
        if (eshared.size() == oldAxis.edges().size())  break; // we're done
      }
    }

    /// @brief Overloaded alias for rebinTo
    ///
    /// @note Only supported for continuous axes
    template <size_t axisN, typename = std::enable_if_t<BinningT::template is_CAxis<axisN>::value>>
    void rebin(const std::vector<typename BinningT::template getAxisT<axisN>::EdgeT>& newedges) {
      rebinTo<axisN>(std::move(newedges));
    }

    /// @brief Reset the EstimateStorage
    ///
    /// Keep the binning but set all bin contents and related quantities to zero
    void reset() noexcept { BaseT::clearBins(); }

    /// @brief Copy assignment
    EstimateStorage& operator = (const EstimateStorage& est) noexcept {
      if (this != &est) {
        AnalysisObject::operator = (est);
        BaseT::operator = (est);
      }
      return *this;
    }

    /// Move assignment
    EstimateStorage& operator = (EstimateStorage&& est) noexcept {
      if (this != &est) {
        AnalysisObject::operator = (est);
        BaseT::operator = (std::move(est));
      }
      return *this;
    }

    /// @brief Add two EstimateStorages
    ///
    /// @note Adding EstimateStorages will unset any ScaledBy
    /// attribute from previous calls to scale or normalize.
    EstimateStorage& add(const EstimateStorage& est,
                         const std::string& pat_uncorr="^stat|^uncor" ) {
      if (*this != est)
        throw BinningError("Arithmetic operation requires compatible binning!");
      if (AO::hasAnnotation("ScaledBy")) AO::rmAnnotation("ScaledBy");
      for (size_t i = 0; i< BaseT::numBins(true, true); ++i) {
        BaseT::bin(i).add(est.bin(i), pat_uncorr);
      }
      BaseT::maskBins(est.maskedBins(), true);
      return *this;
    }
    //
    EstimateStorage& operator += (const EstimateStorage& est) {
      return add(est);
    }

    /// @brief Add two (rvalue) EstimateStorages
    ///
    /// @note Adding EstimateStorages will unset any ScaledBy
    /// attribute from previous calls to scale or normalize.
    EstimateStorage& add(EstimateStorage&& est,
                         const std::string& pat_uncorr="^stat|^uncor" ) {
      if (*this != est)
        throw BinningError("Arithmetic operation requires compatible binning!");
      if (AO::hasAnnotation("ScaledBy")) AO::rmAnnotation("ScaledBy");
      for (size_t i = 0; i< BaseT::numBins(true, true); ++i) {
        BaseT::bin(i).add(std::move(est.bin(i)), pat_uncorr);
      }
      BaseT::maskBins(est.maskedBins(), true);
      return *this;
    }
    //
    EstimateStorage& operator += (EstimateStorage&& est) {
      return add(std::move(est));
    }


    /// @brief Subtract one EstimateStorages from another one
    ///
    /// @note Subtracting EstimateStorages will unset any ScaledBy
    /// attribute from previous calls to scale or normalize.
    EstimateStorage& subtract(const EstimateStorage& est,
                              const std::string& pat_uncorr="^stat|^uncor" ) {
      if (*this != est)
        throw BinningError("Arithmetic operation requires compatible binning!");
      if (AO::hasAnnotation("ScaledBy")) AO::rmAnnotation("ScaledBy");
      for (size_t i = 0; i< BaseT::numBins(true, true); ++i) {
        BaseT::bin(i).subtract(est.bin(i), pat_uncorr);
      }
      BaseT::maskBins(est.maskedBins(), true);
      return *this;
    }
    //
    EstimateStorage& operator -= (const EstimateStorage& est) {
      return subtract(est);
    }

    /// @brief Subtract one (rvalue) EstimateStorages from another one
    EstimateStorage& subtract(EstimateStorage&& est,
                              const std::string& pat_uncorr="^stat|^uncor" ) {
      if (*this != est)
        throw BinningError("Arithmetic operation requires compatible binning!");
      if (AO::hasAnnotation("ScaledBy")) AO::rmAnnotation("ScaledBy");
      for (size_t i = 0; i< BaseT::numBins(true, true); ++i) {
        BaseT::bin(i) -= std::move(est.bin(i), pat_uncorr);
      }
      BaseT::maskBins(est.maskedBins(), true);
      return *this;
    }
    //
    EstimateStorage& operator -= (EstimateStorage&& est) {
      return subtract(std::move(est));
    }

    /// @}


    /// @name Binning info.
    /// @{

    /// @brief Total dimension of the object (number of axes + estimate)
    size_t dim() const noexcept { return sizeof...(AxisT) + 1; }

    /// @brief Returns the axis configuration
    std::string _config() const noexcept { return mkAxisConfig<AxisT...>(); }

    /// @}


    /// @name Whole EstimateStorage data
    /// @{

    /// @brief Get list of central values
    std::vector<double> vals(const bool includeOverflows=false,
                             const bool includeMaskedBins=false) const {
      std::vector<double> rtn;
      rtn.reserve(BaseT::numBins(includeOverflows, includeMaskedBins));
      for (const auto& b : BaseT::bins(includeOverflows, includeMaskedBins)) {
        rtn.push_back(b.val());
      }
      return rtn;
    }

    /// @brief Get list of error sources
    std::vector<std::string> sources() const {
      // Assemble union of error sources, as it's not guaranteed
      // that every bin has the same error breakdown
      std::vector<std::string> rtn;

      for (const auto& b : BaseT::bins(true)) {
        std::vector<std::string> keys = b.sources();
        rtn.insert(std::end(rtn),
                   std::make_move_iterator(std::begin(keys)),
                   std::make_move_iterator(std::end(keys)));
      }
      std::sort(rtn.begin(), rtn.end());
      rtn.erase( std::unique(rtn.begin(), rtn.end()), rtn.end() );

      return rtn;
    }

    /// @brief Calculate the volume underneath the EstimateStorage
    ///
    /// @note overflow bins have infinite bin width
    double areaUnderCurve(const bool includeBinVol=true,
                          const bool includeOverflows=false,
                          const bool includeMaskedBins=false) const {
      double ret = 0.;
      for (const auto& b : BaseT::bins(includeOverflows, includeMaskedBins)) {
        const double val = fabs(b.val());
        const double vol = includeBinVol? b.dVol() : 1.0;
        if (std::isfinite(vol))  ret += val*vol; // aggregate bin volume
      }
      return ret;
    }

    /// @brief Convenient alias for areaUnderCurve()
    double auc(const bool includeBinVol=true,
               const bool includeOverflows=false,
               const bool includeMaskedBins=false) const {
      return areaUnderCurve(includeBinVol, includeOverflows, includeMaskedBins);
    }



    /// @brief Construct a covariance matrix from the error breakdown
    std::vector<std::vector<double>> covarianceMatrix(const bool ignoreOffDiagonalTerms=false,
                                                      const bool includeOverflows=false,
                                                      const bool includeMaskedBins=false,
                                                      const std::string& pat_uncorr="^stat|^uncor") const {
      const size_t nBins = BaseT::numBins(includeOverflows,includeMaskedBins);
      std::vector<std::vector<double> > covM(nBins);

      // initialise cov matrix to be the right shape
      for (size_t i = 0; i < nBins; ++i) {
        covM[i] = std::vector<double>(nBins, 0.0);
      }

      const std::vector<std::string> error_sources = sources();

      // nominal-only case, i.e. total uncertainty, labelled as empty string
      if (error_sources.size() == 1 && error_sources[0] == "") {
        size_t i = 0;
        for (const auto& b : BaseT::bins(includeOverflows,includeMaskedBins)) {
          covM[i][i] = b.hasSource("")? sqr(0.5*(b.err("").first+b.err("").second)) : 1.0;
          ++i;
        }
        return covM;
      }

      // more interesting case where we actually have some uncertainty breakdown!
      std::smatch match;
      const std::regex re(pat_uncorr, std::regex_constants::icase);
      for (const std::string& sname : error_sources) {
        if (sname == "")  continue;
        std::vector<double> systErrs(nBins, 0.0);
        size_t k = 0;
        for (const auto& b : BaseT::bins(includeOverflows,includeMaskedBins)) {
          if (b.hasSource(sname)) {
            const auto& errs = b.err(sname); // dn-up pair
            systErrs[k] = 0.5 *( fabs(errs.first)+fabs(errs.second));
          }
          ++k;
        }
        const bool skipOffDiag = (ignoreOffDiagonalTerms
                                  || std::regex_search(sname, match, re));
        for (size_t i = 0; i < nBins; ++i) {
          for (size_t j = 0; j < nBins; ++j) {
            if (skipOffDiag && i != j)  continue;
            covM[i][j] += systErrs[i]*systErrs[j];
          }
        }
      }

      return covM;
    }

    /// @brief Alias for covarianceMatrix
    std::vector<std::vector<double>> covMat(const bool ignoreOffDiagonalTerms=false,
                                            const bool includeOverflows=false,
                                            const bool includeMaskedBins=false,
                                            const std::string& pat_uncorr="^stat|^uncor") const {
      return covarianceMatrix(ignoreOffDiagonalTerms, includeOverflows, includeMaskedBins, pat_uncorr);
    }

    /// @}

    /// @name Type reductions
    /// @{

    /// @brief Produce a ScatterND from a EstimateStorage
    auto mkScatter(const std::string& path="", const std::string& pat_match = "",
                                               const bool includeOverflows=false,
                                               const bool includeMaskedBins=false) const {

      constexpr size_t N = sizeof...(AxisT);

      ScatterND<N+1> rtn;
      for (const std::string& a : annotations()) {
        if (a != "Type")  rtn.setAnnotation(a, annotation(a));
      }
      rtn.setAnnotation("Path", path);

      const bool incOF = all_CAxes<AxisT...>::value && includeOverflows;
      for (const auto& b : BaseT::bins(incOF, includeMaskedBins)) {

        // Create the vector of coordinates
        Utils::ndarray<double, N+1> vals;
        // first fill bin centres, use bin index if axis non-arithmetic
        auto indexIfDiscrete = [&vals, &b](auto I) {
          using isContinuous = typename BinningT::template is_CAxis<I>;
          using isArithmetic = typename BinningT::template is_Arithmetic<I>;
          vals[I] = coordPicker<I>(b, std::integral_constant<bool, isArithmetic::value>{},
                                      std::integral_constant<bool, isContinuous::value>{});
        };
        MetaUtils::staticFor<BinningT::Dimension::value>(indexIfDiscrete);
        // then fill bin content
        vals[N] = b.val();

        // Create the vector of error pairs, use 0 if axis not continuous
        Utils::ndarray<std::pair<double,double>, N+1> errs;
        auto nullifyDiscrete = [&errs, &vals, &b](auto I) {
          using isContinuous = typename BinningT::template is_CAxis<I>;
          errs[I] = nullifyIfDisc<I>(b, vals[I], std::integral_constant<bool, isContinuous::value>{});
        };
        MetaUtils::staticFor<BinningT::Dimension::value>(nullifyDiscrete);
        const std::pair<double,double> tot = b.totalErr(pat_match);
        errs[N] = {fabs(tot.first), tot.second};

        // Add the PointND
        rtn.addPoint( PointND<N+1>(vals, errs) );
      }

      // Decorate output scatter with the discrete edges
      const BinningT& binning = BaseT::_binning;
      auto decorateEdges = [&rtn, &binning](auto I) {
        using isContinuous = typename BinningT::template is_CAxis<I>;
        if constexpr( !isContinuous::value ) {
          const auto& axis  = binning.template axis<I>();
          if (axis.numBins()) {
            std::stringstream ss;
            axis._renderYODA(ss);
            rtn.setAnnotation("EdgesA" + std::to_string(I+1), ss.str());
          }
        }
      };
      MetaUtils::staticFor<BinningT::Dimension::value>(decorateEdges);

      return rtn;
    }

    /// @brief Split into vector of BinnedEstimates along @a axisN
    ///
    /// The binning dimension of the returned objects are reduced by one unit.
    /// @note Requires at least two binning dimensions.
    template<size_t axisN, typename = std::enable_if_t< (axisN < sizeof...(AxisT) && sizeof...(AxisT)>=2) >>
    auto mkEstimates(const std::string& path="", const bool includeOverflows=false) const {

      // Need to provide a prescription for how to add the two bin contents
      auto how2add = [](auto& pivot, const BinType& toCopy) { pivot = toCopy; };
      auto rtn = BaseT::template mkBinnedSlices<axisN, BinnedEstimate>(how2add, includeOverflows);
      for (const std::string& a : annotations()) {
        if (a == "Type")  continue;
        for (size_t i = 0; i < rtn.size(); ++i) {
          rtn[i].setAnnotation(a, annotation(a));
        }
      }
      for (size_t i = 0; i < rtn.size(); ++i) {
        rtn[i].setAnnotation("Path", path);
      }

      return rtn;
    }


    /// @brief Method returns clone of the estimate with streamlined error source
    AnalysisObject* mkInert(const std::string& path = "",
                            const std::string& source = "") const noexcept {
      EstimateStorage* rtn = newclone();
      rtn->setPath(path);
      for (auto& b : rtn->bins(true, true)) {
        if (b.numErrs() == 1) {
          try {
            b.renameSource("", source);
          }
          catch (YODA::UserError& e) { }
        }
      }
      return rtn;
    }

    /// @}

    /// @name MPI (de-)serialisation
    /// @{

    size_t lengthContent(bool fixed_length = false) const noexcept {
      size_t rtn = 0;
      for (const auto& bin : BaseT::bins(true, true)) {
        rtn += bin._lengthContent(fixed_length);
      }
      return rtn;
    }

    std::vector<double> serializeContent(bool fixed_length = false) const noexcept {
      std::vector<double> rtn;
      const size_t nBins = BaseT::numBins(true, true);
      rtn.reserve(nBins * 4);
      for (size_t i = 0; i < nBins; ++i) {
        const auto& b = BaseT::bin(i);
        std::vector<double> bdata = b._serializeContent(fixed_length);
        rtn.insert(std::end(rtn),
                   std::make_move_iterator(std::begin(bdata)),
                   std::make_move_iterator(std::end(bdata)));
      }
      return rtn;
    }


    void deserializeContent(const std::vector<double>& data) {

      const size_t nBins = BaseT::numBins(true, true);
      const size_t minLen = 2*nBins;
      if (data.size() < minLen)
        throw UserError("Length of serialized data should be at least " + std::to_string(minLen)+"!");

      size_t i = 0;
      auto itr = data.cbegin();
      const auto itrEnd = data.cend();
      const bool fixedLen = data.size() == 2*minLen;
      while (itr != itrEnd) {
        // for estimates, the first element represents the central,
        // the subsequent value represents the number of error pairs
        const size_t nErrs = fixedLen? 1 : (*(itr + 1) + 0.5); // add 0.5 to avoid rounding issues
        auto last = itr + 2*(nErrs+1); // last element + 1
        BaseT::bin(i)._deserializeContent(std::vector<double>{itr, last}, fixedLen);
        // update for next iteration
        itr = last;
        ++i;
      }
    }

    /// @}

  private:

    /// @brief Helper function to create a BinningT from
    /// a given set @a nBins within a range @a limitsLowUp
    template<size_t... Is>
    BinningT _mkBinning(const std::vector<size_t>& nBins,
                        const std::vector<std::pair<double, double>>& limitsLowUp,
                        std::index_sequence<Is...>) const {
      return BinningT({((void)Is, Axis<AxisT>(nBins[Is], limitsLowUp[Is].first, limitsLowUp[Is].second))...});
    }

    /// @brief Helper function to create a BinningT from a scatter @a s
    template<size_t... Is>
    BinningT _mkBinning(const ScatterND<sizeof...(AxisT)+1>& s, std::index_sequence<Is...>) const {
      return BinningT({((void)Is, Axis<AxisT>(s.edges(Is)))...});
    }

  };



  /// @brief User-facing BinnedEstimate class in arbitrary dimensions
  template <typename... AxisT>
  class BinnedEstimate : public EstimateStorage<AxisT...> {
  public:
    using EstimateT = BinnedEstimate<AxisT...>;
    using BaseT = EstimateStorage<AxisT...>;
    using BinType = typename BaseT::BinT;
    using Ptr = std::shared_ptr<EstimateT>;

    /// @brief Inherit constructors.
    using BaseT::BaseT;

    BinnedEstimate(const EstimateT&) = default;
    BinnedEstimate(EstimateT&&) = default;
    BinnedEstimate& operator =(const EstimateT&) = default;
    BinnedEstimate& operator =(EstimateT&&) = default;
    using AnalysisObject::operator =;

    /// @brief Copy constructor (needed for clone functions).
    ///
    /// @note Compiler won't generate this constructor automatically.
    BinnedEstimate(const BaseT& other) : BaseT(other) {}
    //
    BinnedEstimate(const EstimateT& other, const std::string& path) : BaseT(other, path) {}

    /// @brief Move constructor.
    BinnedEstimate(BaseT&& other) : BaseT(std::move(other)) {}
    //
    BinnedEstimate(EstimateT&& other, const std::string& path) : BaseT(std::move(other), path) {}

  };


  /// @brief Specialisation of the BinnedEstimate for a 1D histogram
  template <typename AxisT>
  class BinnedEstimate<AxisT>
      : public EstimateStorage<AxisT>,
        public XAxisMixin<BinnedEstimate<AxisT>, AxisT> {
  public:
    using EstimateT = BinnedEstimate<AxisT>;
    using BaseT = EstimateStorage<AxisT>;
    using BinType = typename BaseT::BinT;
    using Ptr = std::shared_ptr<EstimateT>;

    /// @brief Inherit constructors.
    using BaseT::BaseT;

    BinnedEstimate(const EstimateT&) = default;
    BinnedEstimate(EstimateT&&) = default;
    BinnedEstimate& operator =(const EstimateT&) = default;
    BinnedEstimate& operator =(EstimateT&&) = default;
    using AnalysisObject::operator =;

    /// @brief Copy constructor (needed for clone functions).
    ///
    /// @note Compiler won't generate this constructor automatically.
    BinnedEstimate(const BaseT& other) : BaseT(other) {}
    //
    BinnedEstimate(const EstimateT& other, const std::string& path) : BaseT(other, path) {}

    /// @brief Move constructor.
    BinnedEstimate(BaseT&& other) : BaseT(std::move(other)) {}
    //
    BinnedEstimate(EstimateT&& other, const std::string& path) : BaseT(std::move(other), path) {}


    BinnedEstimate(std::vector<AxisT>&& edges, const std::string& path="", const std::string& title="")
              : BaseT(std::move(edges), path, title) {}

    BinnedEstimate(const std::vector<AxisT>& edges, const std::string& path="", const std::string& title="")
              : BaseT(edges, path, title) {}

    /// @brief Constructor with auto-setup of evenly spaced axes.
    ///
    /// The constructor argument uses double rather than EdgeT to
    /// allow for auto-conversion of int to double.
    ///
    /// @note This constructor is only supported when all axes are continuous.
    template <typename EdgeT = double, typename = enable_if_all_CAxisT<EdgeT, AxisT>>
    BinnedEstimate(size_t nbins, double lower, double upper, const std::string& path = "", const std::string& title = "")
              : BaseT({nbins}, {{lower, upper}}, path, title) {}

    /// @brief Make a copy on the stack
    EstimateT clone() const noexcept {
      return EstimateT(*this);
    }

    /// @brief Make a copy on the heap
    EstimateT* newclone() const noexcept {
      return new EstimateT(*this);
    }

    /// @brief Find bin index for given coordinates
    size_t indexAt(const AxisT xCoord) const noexcept {
      return BaseT::binAt( {xCoord} ).index();
    }

    /// @brief Mask/Unmask bin at given set of coordinates
    void maskBinAt(const AxisT xCoord, const bool status = true) noexcept {
      return BaseT::maskBin({xCoord}, status);
    }

  };



  /// @brief Specialisation of the BinnedEstimate for a 2D BinnedEstimate
  template <typename AxisT1, typename AxisT2>
  class BinnedEstimate<AxisT1, AxisT2>
      : public EstimateStorage<AxisT1, AxisT2>,
        public XAxisMixin<BinnedEstimate<AxisT1, AxisT2>, AxisT1>,
        public YAxisMixin<BinnedEstimate<AxisT1, AxisT2>, AxisT2> {
  public:
    using EstimateT = BinnedEstimate<AxisT1, AxisT2>;
    using BaseT = EstimateStorage<AxisT1, AxisT2>;
    using BinType = typename BaseT::BinT;
    using Ptr = std::shared_ptr<EstimateT>;

    /// @brief Inherit constructors.
    using BaseT::BaseT;

    BinnedEstimate(const EstimateT&) = default;
    BinnedEstimate(EstimateT&&) = default;
    BinnedEstimate& operator =(const EstimateT&) = default;
    BinnedEstimate& operator =(EstimateT&&) = default;
    using AnalysisObject::operator =;

    /// @brief Copy constructor (needed for clone functions).
    ///
    /// @note Compiler won't generate this constructor automatically.
    BinnedEstimate(const BaseT& other) : BaseT(std::move(other)) {}
    //
    BinnedEstimate(const EstimateT& other, const std::string& path) : BaseT(other, path) {}

    /// @brief Move constructor.
    BinnedEstimate(BaseT&& other) : BaseT(std::move(other)) {}
    //
    BinnedEstimate(EstimateT&& other, const std::string& path) : BaseT(std::move(other), path) {}

    BinnedEstimate(std::vector<AxisT1>&& xEdges, std::vector<AxisT2>&& yEdges,
                   const std::string& path="", const std::string& title="")
              : BaseT(std::move(xEdges), std::move(yEdges), path, title) {}

    BinnedEstimate(const std::vector<AxisT1>& xEdges, const std::vector<AxisT2>& yEdges,
                   const std::string& path="", const std::string& title="")
              : BaseT(xEdges, yEdges, path, title) {}

    /// @brief Constructor with auto-setup of evenly spaced axes.
    ///
    /// The constructor argument uses double rather than EdgeT to
    /// allow for auto-conversion of int to double.
    ///
    /// @note This constructor is only supported when all axes are continuous.
    template <typename EdgeT = double, typename = enable_if_all_CAxisT<EdgeT, AxisT1, AxisT2>>
    BinnedEstimate(size_t nbinsX, double lowerX, double upperX,
                   size_t nbinsY, double lowerY, double upperY,
                   const std::string& path = "", const std::string& title = "")
              : BaseT({nbinsX, nbinsY}, {{lowerX, upperX}, {lowerY, upperY}}, path, title) {}

    /// @brief Make a copy on the stack
    EstimateT clone() const noexcept {
      return EstimateT(*this);
    }

    /// @brief Make a copy on the heap
    EstimateT* newclone() const noexcept {
      return new EstimateT(*this);
    }

    /// @brief Bin access using global index
    BinType& bin(const size_t index) noexcept {
      return BaseT::bin(index);
    }

    /// @brief Bin access using global index (const version)
    const BinType& bin(const size_t index) const noexcept {
      return BaseT::bin(index);
    }

    /// @brief Bin access using local indices
    BinType& bin(const size_t localX, const size_t localY) noexcept {
      return BaseT::bin( {localX, localY} );
    }

    /// @brief Bin access using local indices (const version)
    const BinType& bin(const size_t localX, const size_t localY) const noexcept {
      return BaseT::bin( {localX, localY} );
    }

    /// @brief Bin access using coordinates
    BinType& binAt(const AxisT1 xCoord, const AxisT2 yCoord) noexcept {
      return BaseT::binAt( {xCoord, yCoord} );
    }

    /// @brief Bin access using coordinates (const version)
    const BinType& binAt(const AxisT1 xCoord, const AxisT2 yCoord) const noexcept {
      return BaseT::binAt( {xCoord, yCoord} );
    }

    /// @brief Find bin index for given coordinates
    size_t indexAt(const AxisT1 xCoord, const AxisT2 yCoord) const noexcept {
      return BaseT::binAt( {xCoord, yCoord} ).index();
    }

    /// @brief Mask/Unmask bin at given set of coordinates
    void maskBinAt(const AxisT1 xCoord, const AxisT2 yCoord, const bool status = true) noexcept {
      return BaseT::maskBin({xCoord, yCoord}, status);
    }

  };


  /// @brief Specialisation of the BinnedEstimate for a 3D BinnedEstimate
  template <typename AxisT1, typename AxisT2, typename AxisT3>
  class BinnedEstimate<AxisT1, AxisT2, AxisT3>
      : public EstimateStorage<AxisT1, AxisT2, AxisT3>,
        public XAxisMixin<BinnedEstimate<AxisT1, AxisT2, AxisT3>, AxisT1>,
        public YAxisMixin<BinnedEstimate<AxisT1, AxisT2, AxisT3>, AxisT2>,
        public ZAxisMixin<BinnedEstimate<AxisT1, AxisT2, AxisT3>, AxisT3> {
  public:
    using EstimateT = BinnedEstimate<AxisT1, AxisT2, AxisT3>;
    using BaseT = EstimateStorage<AxisT1, AxisT2, AxisT3>;
    using BinType = typename BaseT::BinT;
    using Ptr = std::shared_ptr<EstimateT>;

    /// @brief Inherit constructors.
    using BaseT::BaseT;

    BinnedEstimate(const EstimateT&) = default;
    BinnedEstimate(EstimateT&&) = default;
    BinnedEstimate& operator =(const EstimateT&) = default;
    BinnedEstimate& operator =(EstimateT&&) = default;
    using AnalysisObject::operator =;

    /// @brief Copy constructor (needed for clone functions).
    ///
    /// @note Compiler won't generate this constructor automatically.
    BinnedEstimate(const BaseT& other) : BaseT(other) {}
    //
    BinnedEstimate(const EstimateT& other, const std::string& path) : BaseT(other, path) {}

    /// @brief Move constructor.
    BinnedEstimate(BaseT&& other) : BaseT(std::move(other)) {}
    //
    BinnedEstimate(EstimateT&& other, const std::string& path) : BaseT(std::move(other), path) {}

    /// @brief Constructor with auto-setup of evenly spaced axes.
    ///
    /// The constructor argument uses double rather than EdgeT to
    /// allow for auto-conversion of int to double.
    ///
    /// @note This constructor is only supported when all axes are continuous.
    template <typename EdgeT = double, typename = enable_if_all_CAxisT<EdgeT, AxisT1, AxisT2, AxisT3>>
    BinnedEstimate(size_t nbinsX, double lowerX, double upperX,
                   size_t nbinsY, double lowerY, double upperY,
                   size_t nbinsZ, double lowerZ, double upperZ,
                   const std::string& path = "", const std::string& title = "")
              : BaseT({nbinsX, nbinsY, nbinsZ}, {{lowerX, upperX}, {lowerY, upperY},
                      {lowerZ, upperZ}}, path, title) {}

    /// @brief Make a copy on the stack
    EstimateT clone() const noexcept {
      return EstimateT(*this);
    }

    /// @brief Make a copy on the heap
    EstimateT* newclone() const noexcept {
      return new EstimateT(*this);
    }

    /// @brief Bin access using global index
    BinType& bin(const size_t index) noexcept {
      return BaseT::bin(index);
    }

    /// @brief Bin access using global index (const version)
    const BinType& bin(const size_t index) const noexcept {
      return BaseT::bin(index);
    }

    /// @brief Bin access using local indices
    BinType& bin(const size_t localX, const size_t localY, const size_t localZ) noexcept {
      return BaseT::bin( {localX, localY, localZ} );
    }

    /// @brief Bin access using local indices
    const BinType& bin(const size_t localX, const size_t localY, const size_t localZ) const noexcept {
      return BaseT::bin( {localX, localY, localZ} );
    }

    /// @brief Bin access using coordinates
    BinType& binAt(const AxisT1 xCoord, const AxisT2 yCoord, const AxisT3 zCoord) noexcept {
      return BaseT::binAt( {xCoord, yCoord, zCoord} );
    }

    /// @brief Bin access using coordinates (const version)
    const BinType& binAt(const AxisT1 xCoord, const AxisT2 yCoord, const AxisT3 zCoord) const noexcept {
      return BaseT::binAt( {xCoord, yCoord, zCoord} );
    }

    /// @brief Find bin index for given coordinates
    size_t indexAt(const AxisT1 xCoord, const AxisT2 yCoord, const AxisT3 zCoord) const noexcept {
      return BaseT::binAt( {xCoord, yCoord, zCoord} ).index();
    }

    /// @brief Mask/Unmask bin at given set of coordinates
    void maskBinAt(const AxisT1 xCoord, const AxisT2 yCoord, const AxisT3 zCoord, const bool status = true) noexcept {
      return BaseT::maskBin({xCoord, yCoord, zCoord}, status);
    }

  };

  /// @name Combining BinnedEstimates: global operators
  /// @{

  /// @brief Add two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator + (BinnedEstimate<AxisT...> first, const BinnedEstimate<AxisT...>& second) {
    first += second;
    return first;
  }


  /// @brief Add two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator + (BinnedEstimate<AxisT...> first, BinnedEstimate<AxisT...>&& second) {
    first += std::move(second);
    return first;
  }


  /// @brief Subtract two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate< AxisT...>
  operator - (BinnedEstimate<AxisT...> first, const BinnedEstimate<AxisT...>& second) {
    first -= second;
    return first;
  }

  /// @brief Subtract two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate< AxisT...>
  operator - (BinnedEstimate<AxisT...> first, BinnedEstimate<AxisT...>&& second) {
    first -= std::move(second);
    return first;
  }

  /// @brief Divide two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  divide(const BinnedEstimate<AxisT...>& numer, const BinnedEstimate<AxisT...>& denom,
         const std::string& pat_uncorr="^stat|^uncor" ) {
    if (numer != denom) {
      throw BinningError("Arithmetic operation requires compatible binning!");
    }

    BinnedEstimate<AxisT...> rtn(numer.binning());
    if (numer.path() == denom.path())  rtn.setPath(numer.path());
    if (rtn.hasAnnotation("ScaledBy")) rtn.rmAnnotation("ScaledBy");

    for (const auto& b_num : numer.bins(true, true)) {
      const size_t idx = b_num.index();
      rtn.bin(idx) = divide(b_num, denom.bin(idx), pat_uncorr);
    }
    rtn.maskBins(denom.maskedBins(), true);

    return rtn;
  }

  /// @brief Divide two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (const BinnedEstimate<AxisT...>& numer, const BinnedEstimate<AxisT...>& denom) {
    return divide(numer, denom);
  }

  /// @brief Divide two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (BinnedEstimate<AxisT...>&& numer, const BinnedEstimate<AxisT...>& denom) {
    return divide(std::move(numer), denom);
  }

  /// @brief Divide two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (const BinnedEstimate<AxisT...>& numer, BinnedEstimate<AxisT...>&& denom) {
    return divide(numer, std::move(denom));
  }

  /// @brief Divide two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (BinnedEstimate<AxisT...>&& numer, BinnedEstimate<AxisT...>&& denom) {
    return divide(std::move(numer), std::move(denom));
  }


  /// @brief Calculate a binned efficiency ratio of two BinnedEstimate objects
  ///
  /// @note An efficiency is not the same thing as a standard division of two
  /// BinnedEstimate objects: the errors are treated as correlated via binomial statistics.
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  efficiency(const BinnedEstimate<AxisT...>& accepted, const BinnedEstimate<AxisT...>& total,
             const std::string& pat_uncorr="^stat|^uncor" ) {

    if (accepted != total) {
      throw BinningError("Arithmetic operation requires compatible binning!");
    }

    BinnedEstimate<AxisT...> rtn(accepted.binning());

    for (const auto& b_acc : accepted.bins(true, true)) {
      Estimate est;
      const size_t idx = b_acc.index();
      try {
        est = efficiency(b_acc, total.bin(idx), pat_uncorr);
      } catch (const UserError& e) { }
      rtn.bin(idx) = est;
    }
    return rtn;
  }


  /// @brief Calculate the asymmetry (a-b)/(a+b) of two BinnedDbn objects
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  asymm(const BinnedEstimate<AxisT...>& a,
        const BinnedEstimate<AxisT...>& b,
        const std::string& pat_uncorr="^stat|^uncor" ) {
    return divde(subtract(a-b, pat_uncorr), add(a+b, pat_uncorr), pat_uncorr);
  }


  /// @brief Multiply two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  multiply(const BinnedEstimate<AxisT...>& lhs, const BinnedEstimate<AxisT...>& rhs,
           const std::string& pat_uncorr="^stat|^uncor" ) {
    if (lhs != rhs) {
      throw BinningError("Arithmetic operation requires compatible binning!");
    }

    BinnedEstimate<AxisT...> rtn(lhs.binning());
    if (lhs.path() == rhs.path())  rtn.setPath(lhs.path());
    if (rtn.hasAnnotation("ScaledBy")) rtn.rmAnnotation("ScaledBy");

    for (const auto& b_lhs : lhs.bins(true, true)) {
      const size_t idx = b_lhs.index();
      rtn.bin(idx) = multiply(b_lhs, rhs.bin(idx), pat_uncorr);
    }
    rtn.maskBins(rhs.maskedBins(), true);

    return rtn;
  }

  /// @brief Multiply two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator * (const BinnedEstimate<AxisT...>& lhs, const BinnedEstimate<AxisT...>& rhs) {
    return multiply(lhs, rhs);
  }

  /// @brief Multiply two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator * (BinnedEstimate<AxisT...>&& lhs, const BinnedEstimate<AxisT...>& rhs) {
    return multiply(std::move(lhs), rhs);
  }

  /// @brief Multiply two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator * (const BinnedEstimate<AxisT...>& lhs, BinnedEstimate<AxisT...>&& rhs) {
    return multiply(lhs, std::move(rhs));
  }

  /// @brief Multiply two BinnedEstimates
  template <typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator * (BinnedEstimate<AxisT...>&& lhs, BinnedEstimate<AxisT...>&& rhs) {
    return multiply(std::move(lhs), std::move(rhs));
  }


  /// @}


  /// @name Generalised transformations
  /// @{

  template <typename... AxisT>
  inline void transform(BinnedEstimate<AxisT...>& est, const Trf<1>& fn) {
    for (auto& b : est.bins(true, true)) {
      b.transform(fn);
    }
  }

  template <typename... AxisT, typename FN>
  inline void transform(BinnedEstimate<AxisT...>& est, const FN& fn) {
    transform(est, Trf<1>(fn));
  }

  /// @}


  /// @name Convenience aliases
  /// @{

  /// Define dimension-specific short-hands (Cython sugar)
  template<typename A1>
  using BinnedEstimate1D = BinnedEstimate<A1>;

  template <typename A1, typename A2>
  using BinnedEstimate2D = BinnedEstimate<A1, A2>;

  template <typename A1, typename A2, typename A3>
  using BinnedEstimate3D = BinnedEstimate<A1, A2, A3>;

  /// Anonymous namespace to limit visibility
  namespace {
    template <class T>
    struct EstimateMaker;

    template<size_t... Is>
    struct EstimateMaker<std::index_sequence<Is...>> {
      using type = BinnedEstimate< std::decay_t<decltype((void)Is, std::declval<double>())>... >;
    };
  }

  template<size_t N>
  using EstimateND = typename EstimateMaker<std::make_index_sequence<N>>::type;


  // User-friendly names (continuous axes only)
  using Estimate1D = BinnedEstimate<double>;
  using Estimate2D = BinnedEstimate<double,double>;
  using Estimate3D = BinnedEstimate<double,double,double>;

  /// @}

}

#endif
