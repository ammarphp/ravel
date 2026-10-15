// -*- C++ -*-
//
// This file is part of YODA -- Yet more Objects for Data Analysis
// Copyright (C) 2008-2025 The YODA collaboration (see AUTHORS for details)
//
#ifndef YODA_BinnedStorage_H
#define YODA_BinnedStorage_H

#include "YODA/BinnedAxis.h"
#include "YODA/Binning.h"
#include "YODA/Bin.h"

#include <memory>
#include <vector>

namespace YODA {


  /// @brief Vector wrapper used to interact with bins vectors.
  /// Able to hide overflow and hidden bins.
  template <class VecT>
  class BinsVecWrapper {
  public:
    /// @brief Iterator for range based for loops
    class myIt;

    using BinType = std::decay_t<decltype(*std::declval<VecT>().begin())>;

    BinsVecWrapper() = delete;
    /// @brief HiddenBins std::vector<size_t> must be sorted.
    BinsVecWrapper(VecT& bins, const std::vector<size_t>& hiddenBins)
      : _bins(bins), _hiddenBins(hiddenBins) {}

    BinsVecWrapper(BinsVecWrapper&& other)
      : _bins(std::move(other._bins)), _hiddenBins(std::move(other._hiddenBins)) {}

    myIt begin() const  { return myIt(_bins, _hiddenBins); }
    myIt end()   const  { return myIt(_bins); }

    size_t size() const { return _bins.size() - _hiddenBins.size(); }

    const BinType& operator[](size_t index) const { return _bins[index]; }

    BinType& operator[](size_t index) { return _bins[index]; }

  private:

    VecT& _bins;
    std::vector<size_t> _hiddenBins;
  };

  template<typename VecT>
  class BinsVecWrapper<VecT>::myIt {
  private:
    using IterT = std::conditional_t<std::is_const<VecT>::value,
                                        typename VecT::const_iterator,
                                        typename VecT::iterator>;
  public:

    myIt(VecT& bins,
         const std::vector<size_t>& hiddenBins)
        : _ptr(bins.begin()),
          hiddenCurrPtr(hiddenBins.begin()),
          hiddenEndPtr(hiddenBins.end()),
          binsEndPtr(bins.end()) {

        if (hiddenCurrPtr != hiddenEndPtr && 0 == *hiddenCurrPtr){

          ++hiddenCurrPtr; /// Reveal next hidden bin.
          ++(*this);       /// Advance iterator manually

        }
      }

    myIt(VecT& bins)
        :  _ptr(bins.end()),
           //hiddenCurrPtr(std::vector<size_t>::const_iterator()),
           //hiddenEndPtr(std::vector<size_t>::const_iterator()),
           binsEndPtr(bins.end()) {}

    myIt operator++() noexcept {
      /// @brief Increment iterator. If iterator points on hidden element, skip until
      /// non hidden element or end of the vector.
      ++_ptr;
      ++currBinIdx;

      while (_ptr != binsEndPtr &&
            hiddenCurrPtr != hiddenEndPtr &&
            currBinIdx == *hiddenCurrPtr) {

        ++currBinIdx;
        ++hiddenCurrPtr;
        ++_ptr;
      }
      return *this;
    }

    bool operator!=(const myIt& other) const noexcept {
      return _ptr != other._ptr;
    }

    typename std::iterator_traits<IterT>::reference operator*() noexcept { return *_ptr; }

  private:
    IterT _ptr;
    std::vector<size_t>::const_iterator hiddenCurrPtr;
    std::vector<size_t>::const_iterator hiddenEndPtr;
    IterT binsEndPtr;
    size_t currBinIdx = 0;
  };


  /// @brief BinnedStorage, stores the bins and coordinates access to them
  template <typename BinContentT, typename... AxisT>
  class BinnedStorage {
  protected:

    /// @brief Convenience alias to be used in constructor
    using BinningT = Binning<std::decay_t<decltype(std::declval<Axis<AxisT>>())>...>;
    using BinT = Bin<sizeof...(AxisT), BinContentT, BinningT>;
    using BinsVecT = std::vector<BinT>;
    using BaseT = BinnedStorage<BinContentT, AxisT...>;

  public:

    using BinningType = BinningT;
    using BinType = BinT;
    using BinDimension = std::integral_constant<size_t, sizeof...(AxisT)>;


    /// @name Constructors
    /// @{

    /// @brief Nullary constructor for unique pointers etc.
    BinnedStorage() : _binning(std::vector<AxisT>{}...) {
      fillBins();
    }

    /// @brief Constructs BinnedStorage from Binning.
    BinnedStorage(const BinningT& binning) : _binning(binning) {
      fillBins();
    }

    /// @brief Constructs BinnedStorage from Binning. Rvalue.
    BinnedStorage(BinningT&& binning) : _binning(std::move(binning)) {
      fillBins();
    }

    /// @brief Constructs binning from an adapter and vectors of axes' edges
    BinnedStorage(const std::vector<AxisT>&... edges) : _binning(edges...) {
      fillBins();
    }

    /// @brief Constructs binning from an adapter and Rvalue vectors of axes' edges
    BinnedStorage(std::vector<AxisT>&&... edges) : _binning(std::move(edges)...) {
      fillBins();
    }

    /// @brief Constructs binning from an adapter and Rvalue initializer lists of axes' edges
    BinnedStorage(std::initializer_list<AxisT>&&... edges) : _binning(std::vector<AxisT>{edges}...) {
      fillBins();
    }

    /// @brief Constructs binning from an adapter and a sequence of axes
    BinnedStorage(const Axis<AxisT>&... axes) : _binning(axes...) {
      fillBins();
    }

    /// @brief Constructs binning from an adapter and a sequence of Rvalue axes
    BinnedStorage(Axis<AxisT>&&... axes) : _binning(std::move(axes)...) {
      fillBins();
    }

    /// @brief Copy constructor.
    BinnedStorage(const BinnedStorage& other) : _binning(other._binning) {
      fillBins(other._bins);
    }

    /// @brief Move constructor.
    BinnedStorage(BinnedStorage&& other) : _binning(std::move(other._binning)) {
      fillBins(std::move(other._bins));
    }

    /// @}

    /// @name Methods
    /// @{

    /// @brief Total dimension of the object ( = number of axes + content)
    size_t dim() const noexcept {
      return sizeof...(AxisT) + 1;
    }

    /// @brief Returns reference to the bin at idx.
    /// @note Bin position is calculated using this pattern:
    ///     x + y*width + z*width*height + w*width*height*depth + ...
    /// where (x,y,z) are bin positions on three different axes, and
    /// width, height, and depth are length of these axes. Axes are
    /// queried for position (translating coordinates in positions)
    /// in the order of axes specification in Binning template instantiation.
    BinT& bin(size_t idx) noexcept {
      return _bins.at(idx);
    }

    /// @brief Returns Bin at idx.
    const BinT& bin(size_t idx) const noexcept {
      return _bins.at(idx);
    }

    /// @brief Bin access using local bin indices.
    BinT& bin(const std::array<size_t, sizeof...(AxisT)>& idxLocal) noexcept {
      return bin( _binning.localToGlobalIndex(idxLocal) );
    }

    /// @brief Bin access using local bin indices.
    const BinT& bin(const std::array<size_t, sizeof...(AxisT)>& idxLocal) const noexcept {
      return bin( _binning.localToGlobalIndex(idxLocal) );
    }

    /// @brief Returns reference to the bin at coordinates.
    BinT& binAt(typename BinningT::EdgeTypesTuple&& coords) noexcept {
      const size_t binIdx = _binning.globalIndexAt(coords);
      return bin(binIdx);
    }

    /// @brief Returns reference to the bin at coordinates (const version).
    const BinT& binAt(typename BinningT::EdgeTypesTuple&& coords) const noexcept {
      const size_t binIdx = _binning.globalIndexAt(coords);
      return bin(binIdx);
    }

    /// @brief Sets the bin corresponding to @a coords with an rvalue @a content.
    ///
    /// @note Cython is not a fan of perfext forwarding yet
    void set(typename BinningT::EdgeTypesTuple&& coords, BinContentT&& content) noexcept {
      const size_t binIdx = _binning.globalIndexAt(coords);
      _bins[binIdx] = std::move(content);
    }

    /// @brief Sets the bin corresponding to @a coords with @a content.
    void set(typename BinningT::EdgeTypesTuple&& coords, const BinContentT& content) noexcept {
      const size_t binIdx = _binning.globalIndexAt(coords);
      _bins[binIdx] = content;
    }

    /// @brief Sets the bin corresponding to @a binIndex with an rvalue @a content.
    ///
    /// @note Cython is not a fan of perfect forwarding yet
    void set(const size_t binIdx, BinContentT&& content) noexcept {
      _bins[binIdx] = std::move(content);
    }

    /// @brief Sets the bin corresponding to @a binIndex with @a content.
    void set(const size_t binIdx, const BinContentT& content) noexcept {
      _bins[binIdx] = content;
    }

    /// @brief Calculates indices of bins which are marked or located
    /// in the overflow.
    std::vector<size_t> calcIndicesToSkip(const bool includeOverflows, const bool includeMaskedBins) const noexcept {

      // if there are no bins, exit early
      if (!_binning.numBins(!includeOverflows, !includeMaskedBins))  return {};

      std::vector<size_t> indicesToSkip;

      // define a lambda
      auto appendIndicesVec = [&indicesToSkip](std::vector<size_t>&& indicesVec) {
        indicesToSkip.insert(std::end(indicesToSkip),
                             std::make_move_iterator(std::begin(indicesVec)),
                             std::make_move_iterator(std::end(indicesVec)));
      };

      // only calculate the masked indices when
      // the masked bins are to be skipped over
      if(!includeOverflows) {
        appendIndicesVec(_binning.calcOverflowBinsIndices());
      }

      if (!includeMaskedBins) {
        appendIndicesVec(_binning.maskedBins());
      }

      // sort and remove duplicates
      std::sort(indicesToSkip.begin(), indicesToSkip.end());
      indicesToSkip.erase( std::unique(indicesToSkip.begin(), indicesToSkip.end()),
                           indicesToSkip.end() );

      return indicesToSkip;
    }


    /// @brief Returns bins vector wrapper, which skips masked elements
    /// when iterated over.
    ///
    /// @note Here, @a includeoverflows refers to the return value,
    /// i.e. the default value false implies that calcIndicesToSkip
    /// should return an array of under/overflow indices
    BinsVecWrapper<BinsVecT> bins(const bool includeOverflows = false,
                                  const bool includeMaskedBins = false) noexcept {
      return BinsVecWrapper<BinsVecT>(_bins,
                calcIndicesToSkip(includeOverflows, includeMaskedBins));
    }

    /// @brief Const version.
    ///
    /// @note Here, @a includeoverflows refers to the return value,
    /// i.e. the default value false implies that calcIndicesToSkip
    /// should return an array of under/overflow indices
    const BinsVecWrapper<const BinsVecT> bins(const bool includeOverflows = false,
                                              const bool includeMaskedBins = false) const noexcept {
      return BinsVecWrapper<const BinsVecT>(_bins,
                calcIndicesToSkip(includeOverflows, includeMaskedBins));
    }

    /// @}

    /// @name Binning utilities
    /// @{

    /// @brief Returns dimension underlying binning object reference.
    const BinningT& binning() const noexcept {
      return _binning;
    }

    /// @brief Constructs array of axes sizes
    std::vector<size_t> shape(const bool includeOverflows = false) const noexcept {
      std::array<size_t, sizeof...(AxisT)> arr = _binning.shape(includeOverflows);
      return {std::begin(arr), std::end(arr)};
    }

    /// @brief Returns dimension of binning.
    size_t binDim() const noexcept {
      return _binning.dim();
    }

    /// @brief Number of bins in the BinnedStorage.
    size_t numBins(const bool includeOverflows = false, const bool includeMaskedBins = false) const noexcept {
      return _binning.numBins(includeOverflows, includeMaskedBins);
    }

    /// @brief Number of bins in the BinnedStorage.
    ///
    /// @note need "AtAxis" in function name since
    /// numBins(1) would be ambiguous otherwise
    size_t numBinsAt(const size_t axisN, const bool includeOverflows = false) const noexcept {
      size_t nOverflows = includeOverflows? 0 : _binning.countOverflowBins(axisN);
      return _binning.numBinsAt(axisN) - nOverflows;
    }

    /// @brief Reset the BinnedStorage.
    void reset() noexcept { clearBins(); }

    /// @brief Deletes all bins and creates empty new ones.
    ///
    /// @note Bins marked as masked will remain masked
    void clearBins() noexcept {
      _bins.clear();
      fillBins();
    }

    /// @brief Returns the edges of axis N by value.
    template <size_t I, typename E = typename BinningT::template getEdgeT<I>>
    std::vector<E> edges(const bool includeOverflows = false) const noexcept {
      return BaseT::_binning.template edges<I>(includeOverflows);
    }

    /// @brief Templated version to get bin widths of axis I by value.
    ///
    /// Overflows are included depending on @a includeOverflows
    /// Needed by axis-specific version from AxisMixin
    ///
    /// @note This version is only supported for continuous axes.
    template <size_t I, typename E = typename BinningT::template getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, std::vector<E>>
    widths(const bool includeOverflows = false) const noexcept {
      return BaseT::_binning.template widths<I>(includeOverflows);
    }

    /// @brief Templated version to get bin mins of axis I by value.
    ///
    /// Overflows are included depending on @a includeOverflows
    /// Needed by axis-specific version from AxisMixin
    ///
    /// @note This version is only supported for continuous axes.
    template <size_t I, typename E = typename BinningT::template getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, std::vector<E>>
    mins(const bool includeOverflows = false) const noexcept {
      return BaseT::_binning.template mins<I>(includeOverflows);
    }

    /// @brief Templated version to get bin maxs of axis I by value.
    ///
    /// Overflows are included depending on @a includeOverflows
    /// Needed by axis-specific version from AxisMixin
    ///
    /// @note This version is only supported for continuous axes.
    template <size_t I, typename E = typename BinningT::template getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, std::vector<E>>
    maxs(const bool includeOverflows = false) const noexcept {
      return BaseT::_binning.template maxs<I>(includeOverflows);
    }

    /// @brief Templated version to get bin mids of axis I by value.
    ///
    /// Overflows are included depending on @a includeOverflows
    /// Needed by axis-specific version from AxisMixin
    ///
    /// @note This version is only supported for continuous axes.
    template <size_t I, typename E = typename BinningT::template getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, std::vector<E>>
    mids(const bool includeOverflows = false) const noexcept {
      return BaseT::_binning.template mids<I>(includeOverflows);
    }

    /// @brief Get the lowest non-overflow edge of the axis
    ///
    /// @note This method is only supported for continuous axes
    template <size_t I, typename E = typename BinningT::template getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, E> min() const noexcept {
      return BaseT::_binning.template min<I>();
    }

    /// @brief Get the highest non-overflow edge of the axis
    ///
    /// @note This method is only supported for continuous axes
    template <size_t I, typename E = typename BinningT::template getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, E> max() const noexcept {
      return BaseT::_binning.template max<I>();
    }

    /// @}


    /// @name Bin-masking utilities
    /// @{

    /// @brief Mask a range of bins
    void maskBins(const std::vector<size_t>& indicesToMask, const bool status = true) noexcept {
      _binning.maskBins(indicesToMask, status);
    }

    /// @brief Mask a bin at a given index
    void maskBin(const size_t indexToMask, const bool status = true) noexcept {
      _binning.maskBin(indexToMask, status);
    }

    /// @brief Mask a slice of the binning at local bin index @a idx along axis dimesnion @a dim
    void maskSlice(const size_t dim, const size_t idx, const bool status = true) {
      _binning.maskSlice(dim, idx, status);
    }

    /// @brief Mask a bin at a given set of corrdinates
    void maskBinAt(typename BinningT::EdgeTypesTuple&& coords, const bool status = true) noexcept {
      _binning.maskBinAt(coords, status);
    }

    bool isMasked(const size_t binIndex) const noexcept {
      return _binning.isMasked(binIndex);
    }

    std::vector<size_t> maskedBins() const noexcept {
      return _binning.maskedBins();
    }

    bool isVisible(const size_t binIndex) const noexcept {
      return _binning.isVisible(binIndex);
    }

    /// @}


    /// @name Bin-merging and -slicing utilities
    /// @{

    /// @brief Merge bins from A to B at G axis.
    ///
    /// @param mergeRanges Call using following form mergeBins<1,2>({0, 5}, {3, 4}).
    ///
    /// @note Only works when the BinContentT has += operator. Otherwise merge operation
    /// would make little sense since there will be no effects on the binning except it's
    /// shrinking (no statistical strengthening).
    ///
    /// @note Merging unmasks previously masked bins.
    ///
    /// @note RetT to make enable_if work.
    template <size_t... AxisNs, class RetT = void>
    auto mergeBins(
      std::decay_t<decltype(AxisNs, std::declval<std::pair<size_t, size_t>>())>... mergeRanges)
      noexcept -> std::enable_if_t<MetaUtils::is_detected_v<MetaUtils::operatorTraits::addition_assignment_t, BinContentT>, RetT>
    {
      auto mergeStorageBins =
        [&binning = BaseT::_binning, &binStorage = BaseT::_bins](auto I, const auto& mergeRangePair){
          assert(mergeRangePair.first < mergeRangePair.second);

          auto append = [&binStorage](const auto& pivotBinsIndices, const auto& binsIndicesToMerge){
            assert(pivotBinsIndices.size() == binsIndicesToMerge.size());
            /*for (const auto& k : binsIndicesToMerge) { std::cout << " " << k; }
            std::cout << std::endl;
            for (const auto& k : pivotBinsIndices) { std::cout << " " << k; }
            std::cout << std::endl;*/

            // first merge the bins based on old set of indices
            // unless the bins are masked
            for (size_t i = 0; i < pivotBinsIndices.size(); ++i) {
              auto& pivotBin = binStorage[pivotBinsIndices[i]];
              pivotBin += std::move(binStorage[binsIndicesToMerge[i]]);
            }
            // then erase the bins (which will change the set of indices)
            binStorage.erase(
              std::remove_if(binStorage.begin(), binStorage.end(), [&](const auto& b) {
                return std::find(binsIndicesToMerge.begin(), binsIndicesToMerge.end(), b.index()) != binsIndicesToMerge.end();
              }), binStorage.end());
          };

          ssize_t nBinRowsToBeMerged = mergeRangePair.second - mergeRangePair.first;

          size_t currBinRowIdx = mergeRangePair.first;
          size_t nextBinRowIdx = mergeRangePair.first + 1;
          //std::cout << nBinRowsToBeMerged << " " << currBinRowIdx << " " << nextBinRowIdx << std::endl;

          while (nBinRowsToBeMerged--) {
            /// @note Binning iteratively shrinks, so the next bin slice to merge
            /// will always be the next.
            append(binning.sliceIndices(I, mergeRangePair.first), binning.sliceIndices(I, nextBinRowIdx));
            binning.template mergeBins<I>({currBinRowIdx, nextBinRowIdx});
          }
        };

      ((void)mergeStorageBins(std::integral_constant<size_t, AxisNs>(), mergeRanges), ...);

    }


    /// @brief Split this BinnedStorage into a vector of BinnedStorages along @a axisN
    ///
    /// The binning dimension of the returned objects are reduced by one unit.
    /// @note Requires at least two binning dimensions.
    template<size_t axisN, template<typename...> typename BinnedT, typename Func,
             typename = std::enable_if_t< (axisN < sizeof...(AxisT) && sizeof...(AxisT)>=2) >>
    auto mkBinnedSlices(Func&& how2add, const bool includeOverflows=false) const {

      size_t vecN = BaseT::numBinsAt(axisN, includeOverflows);
      auto binnedSlice = _mkBinnedT<BinnedT>(_binning.template _getAxesExcept<axisN>());
      std::vector<decltype(binnedSlice)> rtn(vecN, binnedSlice);
      for (size_t i = 0; i < vecN; ++i) {

        auto mkSlice = [&oldBins = _bins, &how2add, &binnedSlice = rtn[i]](const auto& indicesToCopy) {
          assert(binnedSlice.numBins(true) == indicesToCopy.size());

          // for any given pivot, add the content
          // from the old slice to the new slice
          for (size_t i = 0; i < binnedSlice.numBins(true); ++i) {
            auto& pivotBin = binnedSlice.bin(i);
            auto& binToCopy = oldBins[indicesToCopy[i]];
            how2add(pivotBin, binToCopy);
          }
        };

        // get bin slice for any given bin i along the axis that is to be
        // sliced, then make the estimates for the new binning
        mkSlice(_binning.sliceIndices(axisN, i + !includeOverflows));

      }
      return rtn;
    }

    /// @}


    /// @name Assignment and Boolean operators
    /// @{

    /// @brief Copy assignment
    BinnedStorage& operator = (const BinnedStorage& other) noexcept {
      if (this != &other) {
        _binning = other._binning;
        fillBins(other._bins);
      }
      return *this;
    }

    /// @brief Move assignment
    BinnedStorage& operator = (BinnedStorage&& other) noexcept {
      if (this != &other) {
        _binning = std::move(other._binning);
        fillBins(std::move(other._bins));
      }
      return *this;
    }

    /// @brief Compares BinnedStorages for equality, e.g. dimensions of
    /// underlying binnings and all axes edges are equal.
    ///
    /// @note This only checks for compatible binning but not equal content.
    bool operator == (const BinnedStorage& other) const noexcept {
      return _binning.isCompatible(other._binning);
    }

    /// @brief Compares BinnedStorages for inequality.
    ///
    /// @note This only checks for compatible binning but not equal content.
    bool operator != (const BinnedStorage& other) const noexcept {
        return ! operator == (other);
    }

    /// @brief Helper function to simplify Cython wrapping
    std::vector<size_t> _global2local(size_t idx) const noexcept {
      const auto& indices = _binning.globalToLocalIndices(idx);
      return std::vector<size_t>(indices.begin(), indices.end());
    }

    /// @brief Helper function to simplify Cython wrapping
    size_t _local2global(const std::vector<size_t>& indices) const {
      assert(indices.size() == sizeof...(AxisT));
      std::array<size_t, sizeof...(AxisT)> arr;
      std::copy_n(std::make_move_iterator(indices.begin()), sizeof...(AxisT), arr.begin());
      return _binning.localToGlobalIndex(arr);
    }

    /// @}


    protected:

      /// @name Utilities
      /// @{

      /// @brief Fills bins with wrapped BinContent objects
      void fillBins() noexcept {
        _bins.reserve(_binning.numBins());

        for (size_t i = 0; i < _binning.numBins(); ++i) {
          _bins.emplace_back(i, _binning);
        }
      }

      void fillBins(const BinsVecT& bins) noexcept {
        _bins.clear();
        _bins.reserve(_binning.numBins());
        for (const auto& b : bins) {
          _bins.emplace_back(b, _binning);
        }
      }

      void fillBins(BinsVecT&& bins) noexcept {
        _bins.clear();
        _bins.reserve(_binning.numBins());
        for (auto&& b : bins) {
          _bins.emplace_back(std::move(b), _binning);
        }
      }

      /// @brief Helper function to unpack the tuple of new axes and make a new BinnedT
      template<template<typename...> typename BinnedT, class... newAxes, size_t... As>
      auto _mkBinnedT_aux(const std::tuple<newAxes...>& t, std::index_sequence<As...>) const {
        return BinnedT<typename newAxes::EdgeT...>(std::get<As>(t)...);
      }

      /// @brief Helper function to make a new BinnedT from a tuple of new axes
      template <template<typename...> typename BinnedT, class... newAxes>
      auto _mkBinnedT(const std::tuple<newAxes...>& t) const {
        return _mkBinnedT_aux<BinnedT>(t, std::make_index_sequence<sizeof...(newAxes)>{});
      }

      /// @}

      /// @brief 1-dim vector, which should be indexed by globalIndex of
      /// the underlying _binning object.
      BinsVecT _bins;

      BinningT _binning;

  };

} // namespace YODA

#endif
