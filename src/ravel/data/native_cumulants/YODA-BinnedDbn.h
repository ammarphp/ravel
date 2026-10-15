// -*- C++ -*-
//
// This file is part of YODA -- Yet more Objects for Data Analysis
// Copyright (C) 2008-2025 The YODA collaboration (see AUTHORS for details)
//
#ifndef YODA_BinnedDbn_h
#define YODA_BinnedDbn_h

#include "YODA/AnalysisObject.h"
#include "YODA/Fillable.h"
#include "YODA/FillableStorage.h"
#include "YODA/Dbn.h"
#include "YODA/BinnedEstimate.h"
#include "YODA/Scatter.h"

#ifdef HAVE_HDF5
#include "YODA/Utils/H5Utils.h"
#endif

#include <memory>
#include <utility>
#include <iostream>
#include <iomanip>

namespace YODA {


  /// All histograms can be instantiated through this alias.
  /*
  ///               BinnedStorage                : Introduces binning backend.
  ///                     |
  ///              FillableStorage               : Introduces FillAdapterT
  ///                     |
  ///                 DbnStorage                 : Hooks up with AnalysisObject
  ///                     /\
  ///                    /  \
  ///    BinnedDbn<1>___/    \___ BinnedDbn<2>   : Introduces dimension specific
  ///          \                     /           : utility aliases
  ///           \_______     _______/            : (xMin(), yMax(), etc.)
  ///                   \   /
  ///                    \ /
  ///                     |
  ///         BinnedHisto/BinnedProfile          : Convenience alias
  */
  /// Since objects with continuous axes are by far the most commonly used type
  /// in practice, we define convenient short-hand aliases HistoND/ProfileND for
  /// with only continuous axes, along with the familar types Histo1D, Profile2D, etc.


  template <size_t DbnN, typename... AxisT>
  class DbnStorage;

  /// @brief User-facing BinnedDbn class in arbitrary dimension
  template <size_t DbnN, typename... AxisT>
  class BinnedDbn : public DbnStorage<DbnN, AxisT...> {
  public:
    using HistoT = BinnedDbn<DbnN, AxisT...>;
    using BaseT = DbnStorage<DbnN, AxisT...>;
    using FillType = typename BaseT::FillType;
    using BinType = typename BaseT::BinT;
    using Ptr = std::shared_ptr<HistoT>;

    /// @brief Inherit constructors.
    using BaseT::BaseT;

    BinnedDbn() = default;
    BinnedDbn(const HistoT&) = default;
    BinnedDbn(HistoT&&) = default;
    BinnedDbn& operator =(const HistoT&) = default;
    BinnedDbn& operator =(HistoT&&) = default;
    using AnalysisObject::operator =;

    /// @brief Copy constructor (needed for clone functions).
    ///
    /// @note Compiler won't generate this constructor automatically.
    BinnedDbn(const BaseT& other) : BaseT(other) {}
    //
    BinnedDbn(const HistoT& other, const std::string& path) : BaseT(other, path) {}

    /// @brief Move constructor
    BinnedDbn(BaseT&& other) : BaseT(std::move(other)) {}
    //
    BinnedDbn(HistoT&& other, const std::string& path) : BaseT(std::move(other), path) {}

    /// @brief Make a copy on the stack
    HistoT clone() const noexcept {
      return HistoT(*this);
    }

    /// @brief Make a copy on the heap
    HistoT* newclone() const noexcept {
      return new HistoT(*this);
    }

  };


  /// @name Define dimension-specific short-hands
  /// @{

  template <typename... AxisTypes>
  using BinnedHisto = BinnedDbn<sizeof...(AxisTypes), AxisTypes...>;

  template <typename... AxisTypes>
  using BinnedProfile = BinnedDbn<sizeof...(AxisTypes)+1, AxisTypes...>;

  /// @}


  /// @brief Histogram convenience class based on FillableStorage.
  ///
  /// @note We use this abstraction layer to implement the bulk once and only once.
  /// The user-facing BinnedDbn type(s) will inherit all their methods from this
  /// base class along with a few axis-specifc mixins.
  ///
  /// @note Alias generates index sequence later used to create
  /// a parameter pack consisting of axis types to instantiate
  /// the Binning template.
  template <size_t DbnN, typename... AxisT>
  class DbnStorage : public FillableStorage<DbnN, Dbn<DbnN>, AxisT...>,
                     public AnalysisObject, public Fillable {
  public:

    using BaseT = FillableStorage<DbnN, Dbn<DbnN>, AxisT...>;
    using BinningT = typename BaseT::BinningT;
    using BinT = typename BaseT::BinT;
    using BinType = typename BaseT::BinT;
    using FillType = typename BaseT::FillType;
    using AnalysisObject::operator =;

    /// @name Constructors
    /// @{

    /// @brief Nullary constructor for unique pointers etc.
    ///
    /// @note The setting of optional path/title is not possible here in order
    /// to avoid overload ambiguity for brace-initialised constructors.
    DbnStorage() : BaseT(), AnalysisObject(mkTypeString<DbnN, AxisT...>(), "") { }

    /// @brief Constructor giving explicit bin edges as rvalue reference.
    ///
    /// Discrete axes have as many edges as bins.
    /// Continuous axes have number of edges = number of bins + 1,
    /// the last one being the upper bound of the last bin.
    DbnStorage(std::vector<AxisT>&&... binsEdges,
               const std::string& path = "", const std::string& title = "")
         : BaseT(Axis<AxisT>(std::move(binsEdges))...),
           AnalysisObject(mkTypeString<DbnN, AxisT...>(), path, title) { }

    /// @brief Constructor giving explicit bin edges as lvalue const reference.
    ///
    /// Discrete axes have as many edges as bins.
    /// Continuous axes have bins.size()+1 edges, the last one
    /// being the upper bound of the last bin.
    DbnStorage(const std::vector<AxisT>&... binsEdges,
               const std::string& path = "", const std::string& title = "")
         : BaseT(Axis<AxisT>(binsEdges)...),
           AnalysisObject(mkTypeString<DbnN, AxisT...>(), path, title) { }

    /// @brief Constructor giving explicit bin edges as initializer list
    ///
    /// Discrete axes have as many edges as bins.
    /// Continuous axes have number of edges = number of bins + 1,
    /// the last one being the upper bound of the last bin.
    DbnStorage(std::initializer_list<AxisT>&&... binsEdges,
               const std::string& path = "", const std::string& title = "")
         : BaseT(Axis<AxisT>(std::move(binsEdges))...),
           AnalysisObject(mkTypeString<DbnN, AxisT...>(), path, title) { }

    /// @brief Constructor giving range and number of bins.
    ///
    /// @note This constructor is only supported for objects with purely continous axes.
    /// It is also the only place where the index sequence sequence is actually needed.
    template <typename EdgeT = double, typename = enable_if_all_CAxisT<EdgeT, AxisT...>>
    DbnStorage(const std::vector<size_t>& nBins, const std::vector<std::pair<EdgeT, EdgeT>>& limitsLowUp,
               const std::string& path = "", const std::string& title = "")
         : BaseT( _mkBinning(nBins, limitsLowUp, std::make_index_sequence<sizeof...(AxisT)>{}) ),
           AnalysisObject(mkTypeString<DbnN, AxisT...>(), path, title) { }

    /// @brief Constructor given a sequence of axes
    DbnStorage(const Axis<AxisT>&... axes, const std::string& path = "", const std::string& title = "")
         : BaseT(axes...), AnalysisObject(mkTypeString<DbnN, AxisT...>(), path, title) { }

    /// @brief Constructor given a sequence of rvalue axes
    DbnStorage(Axis<AxisT>&&... axes, const std::string& path = "", const std::string& title = "")
         : BaseT(std::move(axes)...), AnalysisObject(mkTypeString<DbnN, AxisT...>(), path, title) { }

    /// @brief Constructor given a BinningT (needed for type reductions)
    DbnStorage(const BinningT& binning, const std::string& path = "", const std::string& title = "")
         : BaseT(binning), AnalysisObject(mkTypeString<DbnN, AxisT...>(), path, title) { }

    /// @brief Constructor given an rvalue BinningT
    DbnStorage(BinningT&& binning, const std::string& path = "", const std::string& title = "")
         : BaseT(std::move(binning)), AnalysisObject(mkTypeString<DbnN, AxisT...>(), path, title) { }

    /// @brief Constructor given a scatter
    template <typename EdgeT = double, typename = enable_if_all_CAxisT<EdgeT, AxisT...>>
    DbnStorage(const ScatterND<sizeof...(AxisT)+1>& s, const std::string& path = "", const std::string& title = "")
         : BaseT(_mkBinning(s, std::make_index_sequence<sizeof...(AxisT)>{})),
           AnalysisObject(mkTypeString<DbnN, AxisT...>(), path, title) { }

    /// @brief Copy constructor
    ///
    /// @todo Also allow title setting from the constructor?
    DbnStorage(const DbnStorage& other, const std::string& path = "") : BaseT(other),
         AnalysisObject(mkTypeString<DbnN, AxisT...>(), path!=""? path : other.path(), other, other.title()) { }

    /// @brief Move constructor
    ///
    /// @todo Also allow title setting from the constructor?
    DbnStorage(DbnStorage&& other, const std::string& path = "") : BaseT(std::move(other)),
         AnalysisObject(mkTypeString<DbnN, AxisT...>(), path!=""? path : other.path(), other, other.title()) {  }

    /// @brief Make a copy on the stack
    DbnStorage clone() const noexcept {
      return DbnStorage(*this);
    }

    /// @brief Make a copy on the heap
    DbnStorage* newclone() const noexcept {
      return new DbnStorage(*this);
    }

    /// @}


    /// @name Transformations
    /// @{

    /// @brief Triggers fill adapter on the bin corresponding to coords.
    ///
    /// @note Accepts coordinates only as rvalue tuple. The tuple members
    /// are then moved (bringing tuple member to unspecified state) later in adapters.
    virtual int fill(FillType&& coords, const double weight = 1.0, const double fraction = 1.0) {
      return BaseT::fill(std::move(coords), std::make_index_sequence<sizeof...(AxisT)>{}, weight, fraction);
    }

    /// @brief Rescale as if all fill weights had been different by factor @a scalefactor.
    void scaleW(const double scalefactor) noexcept {
      setAnnotation("ScaledBy", annotation<double>("ScaledBy", 1.0) * scalefactor);
      for (auto& bin : BaseT::_bins) {
        bin.scaleW(scalefactor);
      }
    }

    /// @brief Rescale as if all fill weights had been different by factor @a scalefactor along dimension @a i.
    void scale(const size_t i, const double scalefactor) noexcept {
      setAnnotation("ScaledBy", annotation<double>("ScaledBy", 1.0) * scalefactor);
      for (auto& bin : BaseT::_bins) {
        bin.scale(i, scalefactor);
      }
    }


    /// @brief Normalize the (visible) histo "volume" to the @a normto value.
    ///
    /// If @a includeoverflows is true, the original normalisation is computed with
    /// the overflow bins included, so that the resulting visible normalisation can
    /// be less than @a normto. This is probably what you want.
    void normalize(const double normto=1.0, const bool includeOverflows=true) {
      const double oldintegral = integral(includeOverflows);
      if (oldintegral == 0) throw WeightError("Attempted to normalize a histogram with null area");
      scaleW(normto / oldintegral);
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
      const thisAxisT newAxis(newedges);
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
      rebinTo<axisN>(newedges);
    }

    /// Copy assignment
    DbnStorage& operator = (const DbnStorage& dbn) noexcept {
      if (this != &dbn) {
        AnalysisObject::operator = (dbn);
        BaseT::operator = (dbn);
      }
      return *this;
    }

    /// Move assignment
    DbnStorage& operator = (DbnStorage&& dbn) noexcept {
      if (this != &dbn) {
        AnalysisObject::operator = (dbn);
        BaseT::operator = (std::move(dbn));
      }
      return *this;
    }


    /// @brief Add two DbnStorages
    ///
    /// @note Adding DbnStorages will unset any ScaledBy
    /// attribute from previous calls to scale or normalize.
    ///
    /// @todo What happens if two storages disagree on masked bins?
    DbnStorage& operator += (const DbnStorage& dbn) {
      if (*this != dbn)
        throw BinningError("Arithmetic operation requires compatible binning!");
      if (AO::hasAnnotation("ScaledBy")) AO::rmAnnotation("ScaledBy");
      for (size_t i = 0; i < BaseT::numBins(true, true); ++i) {
        BaseT::bin(i) += dbn.bin(i);
      }
      BaseT::maskBins(dbn.maskedBins(), true);
      return *this;
    }
    //
    DbnStorage& operator += (DbnStorage&& dbn) {
      if (*this != dbn)
        throw BinningError("Arithmetic operation requires compatible binning!");
      if (AO::hasAnnotation("ScaledBy")) AO::rmAnnotation("ScaledBy");
      for (size_t i = 0; i < BaseT::numBins(true, true); ++i) {
        BaseT::bin(i) += std::move(dbn.bin(i));
      }
      BaseT::maskBins(dbn.maskedBins(), true);
      return *this;
    }


    /// @brief Subtract one DbnStorages from another one
    ///
    /// @note Subtracting DbnStorages will unset any ScaledBy
    /// attribute from previous calls to scale or normalize.
    DbnStorage& operator -= (const DbnStorage& dbn) {
      if (*this != dbn)
        throw BinningError("Arithmetic operation requires compatible binning!");
      if (AO::hasAnnotation("ScaledBy")) AO::rmAnnotation("ScaledBy");
      for (size_t i = 0; i < BaseT::numBins(true, true); ++i) {
        BaseT::bin(i) -= dbn.bin(i);
      }
      BaseT::maskBins(dbn.maskedBins(), true);
      return *this;
    }
    //
    DbnStorage& operator -= (DbnStorage&& dbn) {
      if (*this != dbn)
        throw BinningError("Arithmetic operation requires compatible binning!");
      if (AO::hasAnnotation("ScaledBy")) AO::rmAnnotation("ScaledBy");
      for (size_t i = 0; i < BaseT::numBins(true, true); ++i) {
        BaseT::bin(i) -= std::move(dbn.bin(i));
      }
      BaseT::maskBins(dbn.maskedBins(), true);
      return *this;
    }

    /// @}

    /// @name Reset methods
    /// @{

    /// @brief Reset the histogram.
    ///
    /// Keep the binning but set all bin contents and related quantities to zero
    void reset() noexcept { BaseT::reset(); }

    /// @}


    /// @name Binning info.
    /// @{

    size_t fillDim() const noexcept { return BaseT::fillDim(); }

    /// @brief Total dimension of the object (number of axes + filled value)
    size_t dim() const noexcept { return sizeof...(AxisT) + 1; }

    /// @brief Returns the axis configuration
    std::string _config() const noexcept { return mkAxisConfig<AxisT...>(); }

    /// @}


    /// @name Whole histo data
    /// @{

    /// @brief Get the total volume of the histogram.
    double integral(const bool includeOverflows=true) const noexcept {
      return sumW(includeOverflows);
    }

    /// @brief Get the total volume error of the histogram.
    double integralError(const bool includeOverflows=true) const noexcept {
      return sqrt(sumW2(includeOverflows));
    }

    /// @brief Get the total volume of the histogram.
    double integralTo(const size_t binIndex) const noexcept {
      return integralRange(0, binIndex);
    }

    /// @brief Calculates the integrated volume of the histogram between
    /// global bins @a binindex1 and @a binIndex2.
    double integralRange(const size_t binIndex1, size_t binIndex2) const {
      assert(binIndex2 >= binIndex1);
      if (binIndex1 >= BaseT::numBins(true)) throw RangeError("binindex1 is out of range");
      if (binIndex2 >= BaseT::numBins(true)) throw RangeError("binindex2 is out of range");
      double sumw = 0;
      for (size_t idx = binIndex1; idx <= binIndex2; ++idx) {
        if (BaseT::bin(idx).isMasked())  continue;
        sumw += BaseT::bin(idx).sumW();
      }
      return sumw;
    }

    /// @brief Calculates the integrated volume error of the histogram between
    /// global bins @a binindex1 and @a binIndex2.
    double integralRangeError(const size_t binIndex1, size_t binIndex2) const {
      assert(binIndex2 >= binIndex1);
      if (binIndex1 >= BaseT::numBins(true)) throw RangeError("binindex1 is out of range");
      if (binIndex2 >= BaseT::numBins(true)) throw RangeError("binindex2 is out of range");
      double sumw2 = 0;
      for (size_t idx = binIndex1; idx <= binIndex2; ++idx) {
        if (BaseT::bin(idx).isMasked())  continue;
        sumw2 += BaseT::bin(idx).sumW2();
      }
      return sumw2;
    }

    /// @brief Get the number of fills (fractional fills are possible).
    double numEntries(const bool includeOverflows=true) const noexcept {
      double n = 0;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        n += b.numEntries();
      }
      return n;
    }

    /// @brief Calculates sum of weights in histo.
    double sumW(const bool includeOverflows=true) const noexcept {
      double sumw = 0;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        sumw += b.sumW();
      }
      return sumw;
    }

    /// @brief Calculates sum of squared weights in histo.
    double sumW2(const bool includeOverflows=true) const noexcept {
      double sumw2 = 0;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        sumw2 += b.sumW2();
      }
      return sumw2;
    }

    /// @brief Calculates first moment along axis @a dim in histo.
    double sumWA(const size_t dim, const bool includeOverflows=true) const {
      if (dim >= DbnN)  throw RangeError("Invalid axis int, must be in range 0..dim-1");
      double sumwa = 0;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        sumwa += b.sumW(dim+1);
      }
      return sumwa;
    }

    /// @brief Calculates second moment along axis @a dim in histo.
    double sumWA2(const size_t dim, const bool includeOverflows=true) const {
      if (dim >= DbnN)  throw RangeError("Invalid axis int, must be in range 0..dim-1");
      double sumwa2 = 0;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        sumwa2 += b.sumW2(dim+1);
      }
      return sumwa2;
    }

    /// @brief Calculates cross-term along axes @a A1 and @a A2 in histo.
    template<size_t dim = DbnN, typename = std::enable_if_t<(dim >= 2)>>
    double crossTerm(const size_t A1, const size_t A2, const bool includeOverflows=true) const {
      if (A1 >= DbnN || A2 >= DbnN)  throw RangeError("Invalid axis int, must be in range 0..dim-1");
      if (A1 >= A2)  throw RangeError("Indices need to be different for cross term");
      double sumw = 0;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        sumw += b.crossTerm(A1, A2);
      }
      return sumw;
    }

    /// @brief Get the effective number of fills.
    double effNumEntries(const bool includeOverflows=true) const noexcept {
      if (isZero(sumW2(includeOverflows))) return 0;
      return sqr(sumW(includeOverflows)) / sumW2(includeOverflows);
    }

    /// @brief List of mean values at axis @a axisN.
    std::vector<double> means(size_t axisN, const bool includeOverflows=true) const noexcept {
      std::vector<double> rtn;
      rtn.reserve( BaseT::numBins(includeOverflows) );
      for (const auto& b : BaseT::bins(includeOverflows)) {
        rtn.push_back(b.mean(axisN+1));
      }
      return rtn;
    }

    /// @brief Calculates the mean value at axis @a axisN.
    double mean(size_t axisN, const bool includeOverflows=true) const noexcept {
      Dbn<DbnN> dbn;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        dbn += b;
      }
      return dbn.mean(axisN+1);
    }

    /// @brief Calculates the variance at axis @a axisN.
    double variance(size_t axisN, const bool includeOverflows=true) const noexcept {
      Dbn<DbnN> dbn;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        dbn += b;
      }
      return dbn.variance(axisN+1);
    }

    /// @brief Calculates the standard deviation at axis @a axisN.
    double stdDev(size_t axisN, const bool includeOverflows=true) const noexcept {
      return std::sqrt(variance(axisN, includeOverflows));
    }

    /// @brief Calculates the standard error at axis @a axisN.
    double stdErr(size_t axisN, const bool includeOverflows=true) const noexcept {
      Dbn<DbnN> dbn;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        dbn += b;
      }
      return dbn.stdErr(axisN+1);
    }

    /// @brief Calculates the RMS at axis @a axisN.
    double rms(size_t axisN, const bool includeOverflows=true) const noexcept {
      Dbn<DbnN> dbn;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        dbn += b;
      }
      return dbn.RMS(axisN+1);
    }

    /// @brief Calculates the total volume element covered by the binning.
    double dVol(const bool includeOverflows=true) const noexcept {
      double vol = 0.0;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        vol += b.dVol();
      }
      return vol;
    }

    /// @brief Get the total density of the histogram.
    double density(const bool includeOverflows=true) const noexcept {
      const double vol = dVol(includeOverflows);
      if (vol)  return integral(includeOverflows) / vol;
      return std::numeric_limits<double>::quiet_NaN();
    }

    /// @brief Get the total density error of the histogram.
    double densityError(const bool includeOverflows=true) const noexcept {
      const double vol = dVol(includeOverflows);
      if (vol)  return integralError(includeOverflows) / vol;
      return std::numeric_limits<double>::quiet_NaN();
    }

    /// @brief Returns the sum of the bin densities
    double densitySum(const bool includeOverflows=true) const noexcept {
      double rho = 0.0;
      for (const auto& b : BaseT::bins(includeOverflows)) {
        rho += b.sumW() / b.dVol();
      }
      return rho;
    }

    /// @brief Returns the largest density in any of the bins
    double maxDensity(const bool includeOverflows=true) const noexcept {
      std::vector<double> vals;
      for (auto& b : BaseT::bins(includeOverflows)) {
        vals.emplace_back(b.sumW() / b.dVol());
      }
      return *max_element(vals.begin(), vals.end());
    }

    /// @}

    /// @name I/O
    /// @{

  private:

    /// @brief Render information about this AO (private implementation)
    template<size_t... Is>
    void _renderYODA_aux(std::ostream& os, const int width, std::index_sequence<Is...>) const noexcept {

      // YODA1-style metadata
      if ( effNumEntries(true) > 0 ) {
        os << "# Mean: ";
        if (DbnN > 1) {  os << "("; }
        (( os <<  std::string(Is? ", " : "") << mean(Is, true)), ...);
        if (DbnN > 1) {  os << ")"; }
        os << "\n# Integral: " << integral(true) << "\n";
      }

      // render bin edges
      BaseT::_binning._renderYODA(os);

      // column header: content types
      os << std::setw(width) << std::left << "# sumW" << "\t";
      os << std::setw(width) << std::left << "sumW2" << "\t";
      (( os << std::setw(width) << std::left << ("sumW(A"  + std::to_string(Is+1) + ")") << "\t"
            << std::setw(width) << std::left << ("sumW2(A" + std::to_string(Is+1) + ")") << "\t"), ...);
      if constexpr (DbnN >= 2) {
        for (size_t i = 0; i < (DbnN-1); ++i) {
          for (size_t j = i+1; j < DbnN; ++j) {
            const std::string scross = "sumW(A" + std::to_string(i+1) + ",A" + std::to_string(j+1) + ")";
            os << std::setw(width) << std::left << scross << "\t";
          }
        }
      }
      os << "numEntries\n";
      // now write one row per bin
      for (const auto& b : BaseT::bins(true, true)) {
        os << std::setw(width) << std::left << b.sumW() << "\t"; // renders sumW
        os << std::setw(width) << std::left << b.sumW2() << "\t"; // renders sumW2
        ((os << std::setw(width) << std::left << b.sumW( Is+1) << "\t"
             << std::setw(width) << std::left << b.sumW2(Is+1) << "\t"), ...); // renders first moments
        if constexpr (DbnN >= 2) {
          for (size_t i = 0; i < (DbnN-1); ++i) {
            for (size_t j = i+1; j < DbnN; ++j) {
              os << std::setw(width) << std::left << b.crossTerm(i,j) << "\t";
            }
          }
        }
        os << std::setw(width) << std::left << b.numEntries() << "\n"; // renders raw event count
      }
    }

  public:

    /// @brief Render information about this AO (public API)
    void _renderYODA(std::ostream& os, const int width = 13) const noexcept {
      _renderYODA_aux(os, width, std::make_index_sequence<DbnN>{});
    }

    /// @brief Render scatter-like information about this AO
    void _renderFLAT(std::ostream& os, const int width = 13) const noexcept {
      const ScatterND<sizeof...(AxisT)+1> tmp = mkScatter();
      tmp._renderYODA(os, width);
    }

    #ifdef HAVE_HDF5
    /// @brief Extract axes edges of this AO into map of @a edges
    void _extractEdges(std::map<std::string, EdgeHandlerBasePtr>& edges,
                       const std::vector<std::string>&) const noexcept {

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

    };
    #endif

    /// @}

    /// @name MPI (de-)serialisation
    /// @{

    size_t lengthContent(bool = false) const noexcept {
      return BaseT::numBins(true, true) * Dbn<DbnN>::DataSize::value;
    }

    std::vector<double> serializeContent(bool = false) const noexcept {
      std::vector<double> rtn;
      const size_t nBins = BaseT::numBins(true, true);
      rtn.reserve(nBins * Dbn<DbnN>::DataSize::value);
      for (size_t i = 0; i < nBins; ++i) {
        std::vector<double> bdata = BaseT::bin(i)._serializeContent();
        rtn.insert(std::end(rtn),
                   std::make_move_iterator(std::begin(bdata)),
                   std::make_move_iterator(std::end(bdata)));
      }
      return rtn;
    }

    void deserializeContent(const std::vector<double>& data) {

      constexpr size_t dbnSize = Dbn<DbnN>::DataSize::value;
      const size_t nBins = BaseT::numBins(true, true);
      if (data.size() != nBins * dbnSize)
        throw UserError("Length of serialized data should be "
                        + std::to_string(nBins * dbnSize)+"!");

      const auto itr = data.cbegin();
      for (size_t i = 0; i < nBins; ++i) {
        auto first = itr + i*dbnSize;
        auto last = first + dbnSize;
        BaseT::bin(i)._deserializeContent(std::vector<double>{first, last});
      }

    }

    /// @}

    /// @name Type reductions
    /// @{

    /// @brief Produce a BinnedEstimate from a DbnStorage
    ///
    /// The binning remains unchanged.
    ///
    /// @note The @a overflowsWidth argument will be applied
    /// to all bins outside the visible bin range.
    BinnedEstimate<AxisT...> mkEstimate(const std::string& path = "",
                                        const std::string& source = "",
                       [[maybe_unused]] const bool divbyvol = true,
                                        const double overflowsWidth = -1.0) const {

      /// @todo Should we check BaseT::nanCount() and report?
      BinnedEstimate<AxisT...> rtn(BaseT::_binning);
      for (const std::string& a : annotations()) {
        if (a != "Type")  rtn.setAnnotation(a, annotation(a));
      }
      rtn.setAnnotation("Path", path);

      if (BaseT::nanCount()) {
        const double nanc = BaseT::nanCount();
        const double nanw = BaseT::nanSumW();
        const double frac = nanc / (nanc + numEntries());
        const double wtot = nanw + effNumEntries();
        rtn.setAnnotation("NanFraction", frac);
        if (wtot)  rtn.setAnnotation("WeightedNanFraction", nanw/wtot);
      }

      for (const auto& b : BaseT::bins(true, true)) {
        if (overflowsWidth <= 0. && !b.isVisible())  continue;
        if constexpr(DbnN > sizeof...(AxisT)) {
          rtn.bin(b.index()).setVal(b.mean(DbnN));
          if (b.numEntries()) { // only set uncertainty for filled Dbns
            rtn.bin(b.index()).setErr(b.stdErr(DbnN), source);
          }
        }
        else {
          const double scale = divbyvol? (b.isVisible()? b.dVol() : overflowsWidth) : 1.0;
          rtn.bin(b.index()).setVal(b.sumW() / scale);
          if (b.numEntries()) { // only set uncertainty for filled Dbns
            rtn.bin(b.index()).setErr(b.errW() / scale, source);
          }
        }
      }

      return rtn;
    }

    /// @brief Produce a BinnedEstimate for each bin along axis @a axisN
    /// and return as a vector.
    ///
    /// The binning dimension is reduced by one unit.
    ///
    /// @note The @a overflowsWidth argument will be applied
    /// to all bins outside the visible bin range.
    template<size_t axisN, typename = std::enable_if_t< (axisN < sizeof...(AxisT)) >>
    auto mkEstimates(const std::string& path = "", const std::string source = "",
                     const bool divbyvol = true, const bool includeOverflows = false,
                     const double overflowsWidth = -1.0) {

      BinnedEstimate<AxisT...> est = mkEstimate(path, source, divbyvol, overflowsWidth);
      return est.template mkEstimates<axisN>(path, includeOverflows);
    }


    /// @brief Produce a ScatterND from a DbnStorage
    ///
    /// @note The @a overflowsWidth argument will be applied
    /// to all bins outside the visible bin range.
    auto mkScatter(const std::string& path="", const bool divbyvol = true,
                                               const bool usefocus = false,
                                               const bool includeOverflows = false,
                                               const bool includeMaskedBins = false,
                                               const double overflowsWidth = -1.0) const {
      const BinnedEstimate<AxisT...> est = mkEstimate("", "", divbyvol, overflowsWidth);
      ScatterND<sizeof...(AxisT)+1> rtn = est.mkScatter(path, "", includeOverflows, includeMaskedBins);
      if (usefocus) {
        size_t idx = 0;
        for (const auto& b : BaseT::bins(includeOverflows, includeMaskedBins)) {
          auto shiftIfContinuous = [&rtn, &b, &idx](auto I) {
            using isContinuous = typename BinningT::template is_CAxis<I>;
            if constexpr (isContinuous::value) {
              const double oldMax = rtn.point(idx).max(I);
              const double oldMin = rtn.point(idx).min(I);
              const double newVal = b.mean(I+1);
              rtn.point(idx).set(I, newVal, newVal - oldMin, oldMax - newVal);
            }
          };
          MetaUtils::staticFor<BinningT::Dimension::value>(shiftIfContinuous);
          ++idx;
        }
      }
      return rtn;
    }

    /// @brief Produce a BinnedHisto from BinnedProfile.
    ///
    /// The binning remains unchanged, but the fill
    /// dimension is reduced by one unit.
    template<size_t N = DbnN, typename = std::enable_if_t< (N == sizeof...(AxisT)+1) >>
    BinnedHisto<AxisT...> mkHisto(const std::string& path="") const {

      BinnedHisto<AxisT...> rtn(BaseT::_binning);
      rtn.setNanLog(BaseT::nanCount(), BaseT::nanSumW(), BaseT::nanSumW2());
      for (const std::string& a : annotations()) {
        if (a != "Type")  rtn.setAnnotation(a, annotation(a));
      }
      rtn.setAnnotation("Path", path);

      for (const auto& b : BaseT::bins(true)) {
        rtn.bin(b.index()) += b.template reduce<N-1>();
      }

      return rtn;
    }

    /// @brief Produce a BinnedProfile from a DbnStorage
    ///
    /// Case 1: BinnedHisto(N+1)D -> BinnedProfileND
    /// The fill dimension remains the same, but the
    /// binning is reduced by one dimension.
    ///
    /// Case 2: BinnedProfile(N+1)D -> BinnedProfileND
    /// Both fill and binning dimmensions are reduced
    /// by one unit.
    ///
    /// @todo use a parameter pack and allow marginalising over multiple axes?
    template<size_t axisN, typename = std::enable_if_t< (axisN < sizeof...(AxisT)) >>
    auto mkMarginalProfile(const std::string& path="") const {

      auto rtn = BaseT::template _mkBinnedT<BinnedProfile>(BaseT::_binning.template _getAxesExcept<axisN>());
      rtn.setNanLog(BaseT::nanCount(), BaseT::nanSumW(), BaseT::nanSumW2());
      for (const std::string& a : annotations()) {
        if (a != "Type")  rtn.setAnnotation(a, annotation(a));
      }
      rtn.setAnnotation("Path", path);

      auto collapseStorageBins =
        [&oldBinning = BaseT::_binning, &oldBins = BaseT::_bins, &rtn](auto I, auto dbnRed) {

        auto collapse = [&oldBins, &rtn](const auto& binsIndicesToMerge, auto axis) {
          assert(rtn.numBins(true) == binsIndicesToMerge.size());

          // for any given pivot, add the content
          // from the old slice to the new slice
          for (size_t i = 0; i < rtn.numBins(true); ++i) {
            auto& pivotBin = rtn.bin(i);
            auto& binToAppend = oldBins[binsIndicesToMerge[i]];
            pivotBin += binToAppend.template reduce<axis>();
          }
        };

        // get bin slice for any given bin along the axis that is to be
        // collapsed, then copy the values into the new binning
        ssize_t nBinRowsToBeMerged = oldBinning.numBinsAt(I);
        while (nBinRowsToBeMerged--) {
          /// @note Binning iteratively shrinks, so the next bin slice
          /// to merge will always be the next.
          collapse(oldBinning.sliceIndices(I, nBinRowsToBeMerged), dbnRed);
        }
      };
      /// If the calling object is a histogram, we can just copy the Dbn<N>,
      /// otherwise we need to collapse an axis first in order to produce a Dbn<N-1>.
      /// @note Dbn axes are 0-indexed, so asking to reduce DbnN doesn't reduce anything.
      auto dbnRed = std::integral_constant<size_t, (sizeof...(AxisT) == DbnN)? DbnN : axisN>();
      (void)collapseStorageBins(std::integral_constant<std::size_t, axisN>(), dbnRed);

      return rtn;
    }

    /// @brief Produce a BinnedHisto from a DbnStorage
    ///
    /// Case 1: BinnedProfile(N+1)D -> BinnedHistoND
    /// The binning dimension is reduced by one unit,
    /// and the fill dimension is reduced by two units.
    ///
    /// Case 2: BinnedHisto(N+1)D -> BinnedHisto
    /// Both fill and binning dimension are reduced
    /// by one unit.
    ///
    /// @todo use a parameter pack and allow marginalising over multiple axes?
    template<size_t axisN, typename = std::enable_if_t< (axisN < sizeof...(AxisT)) >>
    auto mkMarginalHisto(const std::string& path="") const {

      if constexpr (DbnN != sizeof...(AxisT)) {
        // Case 1: BP(N+1) -> BH(N+1) -> BHN
        return mkHisto().template mkMarginalHisto<axisN>(path);
      }
      else {
        // Case 2: BH(N+1) -> BHN

        auto rtn = BaseT::template _mkBinnedT<BinnedHisto>(BaseT::_binning.template _getAxesExcept<axisN>());
        rtn.setNanLog(BaseT::nanCount(), BaseT::nanSumW(), BaseT::nanSumW2());
        for (const std::string& a : annotations()) {
          if (a != "Type")  rtn.setAnnotation(a, annotation(a));
        }
        rtn.setAnnotation("Path", path);

        auto collapseStorageBins =
          [&oldBinning = BaseT::_binning, &oldBins = BaseT::_bins, &rtn](auto I, auto dbnRed) {

          auto collapse = [&oldBins, &rtn](const auto& binsIndicesToMerge, auto axis) {
            assert(rtn.numBins(true) == binsIndicesToMerge.size());

            // for any given pivot, add the content
            // from the old slice to the new slice
            for (size_t i = 0; i < rtn.numBins(true); ++i) {
              auto& pivotBin = rtn.bin(i);
              auto& binToAppend = oldBins[binsIndicesToMerge[i]];
              pivotBin += binToAppend.template reduce<axis>();
            }
          };

          // get bin slice for any given bin along the axis that is to be
          // collapsed, then copy the values into the new binning
          ssize_t nBinRowsToBeMerged = oldBinning.numBinsAt(I);
          while (nBinRowsToBeMerged--) {
            /// @note Binning iteratively shrinks, so the next bin slice
            /// to merge will always be the next.
            collapse(oldBinning.sliceIndices(I, nBinRowsToBeMerged), dbnRed);
          }
        };
        // collapse Dbn along axisN
        auto dbnRed = std::integral_constant<size_t, axisN>();
        (void)collapseStorageBins(std::integral_constant<std::size_t, axisN>(), dbnRed);

        return rtn;
      }
    }


    /// @brief Split into vector of BinnedProfile along axis @a axisN
    ///
    /// The binning dimension of the returned objects are reduced by one unit.
    /// @note Requires at least two binning dimensions.
    template<size_t axisN, typename = std::enable_if_t< (axisN < sizeof...(AxisT) &&
                                                         sizeof...(AxisT)>=2 &&
                                                         DbnN > sizeof...(AxisT)) >>
    auto mkProfiles(const std::string& path="", const bool includeOverflows=false) const {

      // Need to provide a prescription for how to add the two bin contents
      auto how2add = [](auto& pivot, const BinType& toCopy) { pivot = toCopy.template reduce<axisN>(); };
      auto rtn = BaseT::template mkBinnedSlices<axisN, BinnedProfile>(how2add, includeOverflows);
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


    /// @brief Split into vector of BinnedHisto along axis @a axisN
    ///
    /// The binning dimension of the returned ojects are reduced by one unit.
    /// @note Requires at least two binning dimensions.
    template<size_t axisN, typename = std::enable_if_t< (axisN < sizeof...(AxisT) && sizeof...(AxisT)>=2) >>
    auto mkHistos(const std::string& path="", const bool includeOverflows=false) const {

      if constexpr (DbnN != sizeof...(AxisT)) {
        // Case 1: BP(N+1) -> BH(N+1) -> BHN
        return mkHisto().template mkHistos<axisN>(path, includeOverflows);
      }
      else {
        // Case 2: BH(N+1) -> BHN

        // Need to provide a prescription for how to add the two bin contents
        auto how2add = [](auto& pivot, const BinType& toCopy) { pivot = toCopy.template reduce<axisN>(); };
        auto rtn = BaseT::template mkBinnedSlices<axisN,BinnedHisto>(how2add, includeOverflows);
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
    }


    /// @brief Convert the BinnedDbn to a BinnedEstimate representing
    /// the effective number of entries in each bin
    ///
    /// @note The @a overflowsWidth argument will be applied
    /// to all bins outside the visible bin range.
    BinnedEstimate<AxisT...> mkBinnedEffNumEntries(const std::string& path="",
                                                   const std::string& source = "",
                                                   const bool includeOverflows = true,
                                                   const bool divbyvol = true,
                                                   const double overflowsWidth = -1.0) {

      BinnedEstimate<AxisT...> rtn = mkEstimate(path);

      for (const auto& b : BaseT::bins(includeOverflows)) {
        double scale = 1.0;
        if (divbyvol) {
          scale = (overflowsWidth > 0. && !b.isVisible())? overflowsWidth : b.dVol();
        }
        const double effN = b.effNumEntries() / scale;
        const double err = effN * b.relErrW() / scale;
        rtn.bin(b.index()).set(effN, {-err, err}, source);
      }

      return rtn;
    }


    /// @brief Return an inert version of the analysis object (e.g. scatter, estimate)
    AnalysisObject* mkInert(const std::string& path = "",
                            const std::string& source = "") const noexcept {
      return mkEstimate(path, source).newclone();
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
      return BinningT(Axis<AxisT>(s.edges(Is))...);
    }

  };



  /// @name Combining BinnedDbn objects: global operators
  /// @{

  /// @brief Add two BinnedDbn objects
  template<size_t DbnN, typename... AxisT>
  inline BinnedDbn<DbnN, AxisT...>
  operator + (BinnedDbn<DbnN, AxisT...> first, BinnedDbn<DbnN, AxisT...>&& second) {
    first += std::move(second);
    return first;
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedDbn<DbnN, AxisT...>
  operator + (BinnedDbn<DbnN, AxisT...> first, const BinnedDbn<DbnN, AxisT...>& second) {
    first += second;
    return first;
  }


  /// @brief Subtract one BinnedDbn object from another
  template <size_t DbnN, typename... AxisT>
  inline BinnedDbn<DbnN, AxisT...>
  operator - (BinnedDbn<DbnN, AxisT...> first, BinnedDbn<DbnN, AxisT...>&& second) {
    first -= std::move(second);
    return first;
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedDbn<DbnN, AxisT...>
  operator - (BinnedDbn<DbnN, AxisT...> first, const BinnedDbn<DbnN, AxisT...>& second) {
    first -= second;
    return first;
  }


  /// @brief Divide two BinnedDbn objects
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  divide(const BinnedDbn<DbnN, AxisT...>& numer, const BinnedDbn<DbnN, AxisT...>& denom) {

    if (numer != denom) {
      throw BinningError("Arithmetic operation requires compatible binning!");
    }

    BinnedEstimate<AxisT...> rtn = numer.mkEstimate();
    if (numer.path() == denom.path())  rtn.setPath(numer.path());
    if (rtn.hasAnnotation("ScaledBy")) rtn.rmAnnotation("ScaledBy");

    for (const auto& b_num : numer.bins(true, true)) {
      const size_t idx = b_num.index();
      const auto& b_den = denom.bin(idx);
      double v, e;
      if (isZero(b_den.effNumEntries())) {
        v = std::numeric_limits<double>::quiet_NaN();
        e = std::numeric_limits<double>::quiet_NaN();
      }
      else {
        if constexpr(DbnN > sizeof...(AxisT)) {
          v = b_num.mean(DbnN) / b_den.mean(DbnN);
          const double e_num = isZero(b_num.effNumEntries())? 0 : b_num.relStdErr(DbnN);
          const double e_den = isZero(b_den.effNumEntries())? 0 : b_den.relStdErr(DbnN);
          e = fabs(v) * sqrt(sqr(e_num) + sqr(e_den));
        }
        else {
          v = b_num.sumW() / b_den.sumW();
          const double e_num = isZero(b_num.effNumEntries())? 0 : b_num.relErrW();
          const double e_den = isZero(b_den.effNumEntries())? 0 : b_den.relErrW();
          e = fabs(v) * sqrt(sqr(e_num) + sqr(e_den));
        }
      }
      rtn.bin(idx).set(v, {-e, e}); ///< @todo put "stats" as source?
    }
    rtn.maskBins(denom.maskedBins(), true);

    return rtn;
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (const BinnedDbn<DbnN, AxisT...>& numer, const BinnedDbn<DbnN, AxisT...>& denom) {
    return divide(numer, denom);
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (const BinnedDbn<DbnN, AxisT...>& numer, BinnedDbn<DbnN, AxisT...>&& denom) {
    return divide(numer, std::move(denom));
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (BinnedDbn<DbnN, AxisT...>&& numer, const BinnedDbn<DbnN, AxisT...>& denom) {
    return divide(std::move(numer), denom);
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (BinnedDbn<DbnN, AxisT...>&& numer, BinnedDbn<DbnN, AxisT...>&& denom) {
    return divide(std::move(numer), std::move(denom));
  }


  /// @brief Multiply two BinnedDbn objects
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  multiply(const BinnedDbn<DbnN, AxisT...>& lhs, const BinnedDbn<DbnN, AxisT...>& rhs) {

    if (lhs != rhs) {
      throw BinningError("Arithmetic operation requires compatible binning!");
    }

    BinnedEstimate<AxisT...> rtn = lhs.mkEstimate();
    if (lhs.path() == rhs.path())  rtn.setPath(lhs.path());
    if (rtn.hasAnnotation("ScaledBy")) rtn.rmAnnotation("ScaledBy");

    for (const auto& b_lhs : lhs.bins(true, true)) {
      const size_t idx = b_lhs.index();
      const auto& b_rhs = rhs.bin(idx);
      double v, e;
      if constexpr(DbnN > sizeof...(AxisT)) {
        v = b_lhs.mean(DbnN) * b_lhs.mean(DbnN);
        const double e_lhs = isZero(b_lhs.effNumEntries())? 0 : b_lhs.relStdErr(DbnN);
        const double e_rhs = isZero(b_rhs.effNumEntries())? 0 : b_rhs.relStdErr(DbnN);
       e = fabs(v) * add_quad(e_lhs, e_rhs);
      }
      else {
        v = b_lhs.sumW() * b_rhs.sumW();
        const double e_lhs = isZero(b_lhs.effNumEntries())? 0 : b_lhs.relErrW();
        const double e_rhs = isZero(b_rhs.effNumEntries())? 0 : b_rhs.relErrW();
        e = fabs(v) * add_quad(e_lhs, e_rhs);
      }
      rtn.bin(idx).set(v, {-e, e}); ///< @todo put "stats" as source?
    }
    rtn.maskBins(rhs.maskedBins(), true);

    return rtn;
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator * (const BinnedDbn<DbnN, AxisT...>& lhs, const BinnedDbn<DbnN, AxisT...>& rhs) {
    return multiply(lhs, rhs);
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator * (const BinnedDbn<DbnN, AxisT...>& lhs, BinnedDbn<DbnN, AxisT...>&& rhs) {
    return multiply(lhs, std::move(rhs));
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator * (BinnedDbn<DbnN, AxisT...>&& lhs, const BinnedDbn<DbnN, AxisT...>& rhs) {
    return multiply(std::move(lhs), rhs);
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator * (BinnedDbn<DbnN, AxisT...>&& lhs, BinnedDbn<DbnN, AxisT...>&& rhs) {
    return multiply(std::move(lhs), std::move(rhs));
  }


  /// @brief Calculate a binned efficiency ratio of two BinnedDbn objects
  ///
  /// @note An efficiency is not the same thing as a standard division of two
  /// BinnedDbn objects: the errors are treated as correlated via binomial statistics.
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  efficiency(const BinnedDbn<DbnN, AxisT...>& accepted, const BinnedDbn<DbnN, AxisT...>& total) {

    if (accepted != total) {
      throw BinningError("Arithmetic operation requires compatible binning!");
    }

    BinnedEstimate<AxisT...> rtn = divide(accepted, total);

    for (const auto& b_acc : accepted.bins(true, true)) {
      const auto& b_tot = total.bin(b_acc.index());
      auto& b_rtn = rtn.bin(b_acc.index());

      // Check that the numerator is consistent with being a subset of the denominator
      /// @note Neither effNumEntries nor sumW are guaranteed to satisfy num <= den for general weights!
      if (b_acc.numEntries() > b_tot.numEntries())
        throw UserError("Attempt to calculate an efficiency when the numerator is not a subset of the denominator: "
                        + Utils::toStr(b_acc.numEntries()) + " entries / " + Utils::toStr(b_tot.numEntries()) + " entries");

      // If no entries on the denominator, set eff = err = 0 and move to the next bin
      double eff = std::numeric_limits<double>::quiet_NaN();
      double err = std::numeric_limits<double>::quiet_NaN();
      if (!isZero(b_tot.effNumEntries())) {
        eff = b_rtn.val();
        err = sqrt(fabs( add((1.0-2.0*eff)*b_acc.sumW2(), sqr(eff)*b_tot.sumW2()) / sqr(b_tot.sumW()) ));
      }
      b_rtn.setErr({-err, err}); ///< @todo put "stats" as source?
    }
    return rtn;
  }


  /// @brief Calculate the asymmetry (a-b)/(a+b) of two BinnedDbn objects
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  asymm(const BinnedDbn<DbnN, AxisT...>& a, const BinnedDbn<DbnN, AxisT...>& b) {
    return (a-b) / (a+b);
  }


  /// @brief Convert a BinnedDbn to a BinnedEstimate representing the integral of the histogram
  ///
  /// @note The integral histo errors are calculated as sqrt(binvalue), as if they
  /// are uncorrelated. This is not in general true for integral histograms, so if you
  /// need accurate errors you should explicitly monitor bin-to-bin correlations.
  ///
  /// The includeunderflow param chooses whether the underflow bin is included
  /// in the integral numbers as an offset.
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  mkIntegral(const BinnedDbn<DbnN, AxisT...>& histo, const bool includeOverflows = true) {

    BinnedEstimate<AxisT...> rtn = histo.mkEstimate();

    double sumW = 0.0, sumW2 = 0.0;
    for (const auto& b : histo.bins(includeOverflows)) {
      sumW  += b.sumW();
      sumW2 += b.sumW2();
      const double e = sqrt(sumW2);
      rtn.bin(b.index()).set(sumW, {-e, e});
    }

    return rtn;
  }


  /// @brief Convert a BinnedDbn to a BinnedEstimate where each bin is a fraction of the total
  ///
  /// @note This sounds weird: let's explain a bit more! Sometimes we want to
  /// take a histo h, make an integral histogram H from it, and then divide H by
  /// the total integral of h, such that every bin in H represents the
  /// cumulative efficiency of that bin as a fraction of the total. I.e. an
  /// integral histo, scaled by 1/total_integral and with binomial errors.
  ///
  /// The includeunderflow param behaves as for toIntegral, and applies to both
  /// the initial integration and the integral used for the scaling. The
  /// includeoverflow param applies only to obtaining the scaling factor.
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  mkIntegralEff(const BinnedDbn<DbnN, AxisT...>& histo, const bool includeOverflows = true) {

    BinnedEstimate<AxisT...> rtn = mkIntegral(histo, includeOverflows);
    const double integral = histo.integral(includeOverflows);

    // If the integral is empty, the (integrated) efficiency values may as well all be zero, so return here
    /// @todo Or throw a LowStatsError exception if h.effNumEntries() == 0?
    /// @todo Provide optional alt behaviours
    /// @todo Need to check that bins are all positive? Integral could be zero due to large +ve/-ve in different bins :O
    if (!integral) return rtn;

    const double integral_err = histo.integralError(includeOverflows);
    for (const auto& b : rtn.bins(includeOverflows)) {
      const double eff = b.val() / integral;
      const double err = sqrt(std::abs( ((1-2*eff)*sqr(b.relTotalErrAvg()) + sqr(eff)*sqr(integral_err)) / sqr(integral) ));
      b.set(eff, {-err,err});
    }

    return rtn;
  }


  /// @brief Calculate the addition of a BinnedDbn with a BinnedEstimate
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  add(const BinnedDbn<DbnN, AxisT...>& dbn, const BinnedEstimate<AxisT...>& est) {
    return dbn.mkEstimate() + est;
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator + (const BinnedDbn<DbnN, AxisT...>& dbn, const BinnedEstimate<AxisT...>& est) {
    return add(dbn, est);
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator + (BinnedDbn<DbnN, AxisT...>&& dbn, const BinnedEstimate<AxisT...>& est) {
    return add(std::move(dbn), est);
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator + (const BinnedDbn<DbnN, AxisT...>& dbn, BinnedEstimate<AxisT...>&& est) {
    return add(dbn, std::move(est));
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator + (BinnedDbn<DbnN, AxisT...>&& dbn, BinnedEstimate<AxisT...>&& est) {
    return add(std::move(dbn), std::move(est));
  }


  /// @brief Calculate the subtraction of a BinnedEstimate from a BinnedDbn
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  subtract(const BinnedDbn<DbnN, AxisT...>& dbn, const BinnedEstimate<AxisT...>& est) {
    return dbn.mkEstimate() - est;
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator - (const BinnedDbn<DbnN, AxisT...>& dbn, const BinnedEstimate<AxisT...>& est) {
    return subtract(dbn, est);
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator - (BinnedDbn<DbnN, AxisT...>&& dbn, const BinnedEstimate<AxisT...>& est) {
    return subtract(std::move(dbn), est);
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator - (const BinnedDbn<DbnN, AxisT...>& dbn, BinnedEstimate<AxisT...>&& est) {
    return subtract(dbn, std::move(est));
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator - (BinnedDbn<DbnN, AxisT...>&& dbn, BinnedEstimate<AxisT...>&& est) {
    return subtract(std::move(dbn), std::move(est));
  }


  /// @brief Calculate the division of a BinnedDbn and a BinnedEstimate
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  divide(const BinnedDbn<DbnN, AxisT...>& dbn, const BinnedEstimate<AxisT...>& est) {
    return dbn.mkEstimate() / est;
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (const BinnedDbn<DbnN, AxisT...>& dbn, const BinnedEstimate<AxisT...>& est) {
    return divide(dbn, est);
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (BinnedDbn<DbnN, AxisT...>&& dbn, const BinnedEstimate<AxisT...>& est) {
    return divide(std::move(dbn), est);
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (const BinnedDbn<DbnN, AxisT...>& dbn, BinnedEstimate<AxisT...>&& est) {
    return divide(dbn, std::move(est));
  }
  //
  template <size_t DbnN, typename... AxisT>
  inline BinnedEstimate<AxisT...>
  operator / (BinnedDbn<DbnN, AxisT...>&& dbn, BinnedEstimate<AxisT...>&& est) {
    return divide(std::move(dbn), std::move(est));
  }


  /// @brief Zip profile objects of the same type into a combined scatter object
  ///
  /// The resulting object has as many points as profile bins and whose central
  /// values are given by the means along the unbinned profile axes with means
  /// of first profile corresponding to x-coordinate, means of second profile
  /// corresponding to y-coordinate etc.
  ///
  /// @note The BinnedDbn objects must be profiles and have the same axis config.
  template<size_t DbnN, typename... AxisT, typename... Args,
           typename = std::enable_if_t<(DbnN == sizeof...(AxisT)+1 &&
                                       (std::is_same_v<BinnedDbn<DbnN, AxisT...>, Args> && ...))>>
  ScatterND<sizeof...(Args)+1> zipProfiles(const BinnedDbn<DbnN, AxisT...>& p1, Args&&... others,
                                           const std::string& path = "") {

    // Check profiles have the same binning
    if ( !((p1 == others) && ...) )
      throw BinningError("Requested zipping of profiles with incompatible binning!");

    // Construct resulting Scatter whose coordinates
    // are given by the unbinned means
    constexpr size_t N = sizeof...(Args)+1;
    ScatterND<N> rtn;
    rtn.setAnnotation("Path", path);
    for (const auto& b1 : p1.bins()) {
      typename ScatterND<N>::NdVal vals = { b1.mean(DbnN), others.bin(b1.binIndex()).mean(DbnN) ... };
      typename ScatterND<N>::NdVal errs = { b1.stdErr(DbnN), others.bin(b1.binIndex()).stdErr(DbnN) ... };
      rtn.addPoint(vals, errs);
    }
    return rtn;
  }

  /// @}

}

#endif
