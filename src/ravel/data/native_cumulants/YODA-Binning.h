// -*- C++ -*-
//
// This file is part of YODA -- Yet more Objects for Data Analysis
// Copyright (C) 2008-2025 The YODA collaboration (see AUTHORS for details)
//
#ifndef YODA_BINNING_H
#define YODA_BINNING_H
#include "YODA/BinnedAxis.h"
#include "YODA/Utils/MetaUtils.h"
#include <memory>
#include <tuple>
#include <vector>
#include <array>

namespace YODA {


  /// @brief Nullifies coordinate if it is discrete.
  template<typename CoordT>
  double nullifyIfDiscCoord(CoordT&& /* coord */, std::false_type, double null = 0.0) {
    return null;
  }
  //
  template<typename CoordT>
  double nullifyIfDiscCoord(CoordT&& coord, std::true_type, double /* null */ = 0.0) {
    return std::forward<CoordT>(coord);
  }

  /// @brief Checks if a coordinate tuple has a nan
  template<typename... Args>
  inline bool containsNan(const std::tuple<Args...>& coords) {
    std::array<size_t, sizeof...(Args)> hasNan{};
    auto checkCoords = [&hasNan, &coords](auto I) {
      using isContinuous = typename std::is_floating_point<typename std::tuple_element_t<I, std::tuple<Args...>>>;

      hasNan[I] = size_t(std::isnan(nullifyIfDiscCoord(std::move(std::get<I>(coords)),
                                                       std::integral_constant<bool,
                                                       isContinuous::value>{})));
    };

    MetaUtils::staticFor<sizeof...(Args)>(checkCoords);

    return std::any_of(hasNan.begin(), hasNan.end(), [ ](const bool i) { return i; } );
  }



  template <typename... Axes>
  class Binning {
  private:

    std::tuple<Axes...> _axes;
    size_t _dim = sizeof...(Axes);
    std::vector<size_t> _maskedIndices;


  public:

    /// @name Utilities
    /// @{

    using IndexArr = std::array<size_t, sizeof...(Axes)>;

    template <size_t I>
    using getAxisT = std::tuple_element_t<I, std::tuple<Axes...>>;

    template <size_t I>
    using getEdgeT = typename getAxisT<I>::EdgeT;

    template <size_t I>
    using is_CAxis = typename std::is_floating_point<getEdgeT<I>>;

    template<size_t I>
    using is_Arithmetic = typename std::is_arithmetic<getEdgeT<I>>;

    using all_CAxes = typename std::conjunction<std::is_floating_point<typename Axes::EdgeT>...>;

    using EdgeTypesTuple = decltype(
      std::tuple_cat(std::declval<std::tuple<typename Axes::EdgeT>>()...));

    using Dimension = std::integral_constant<size_t, sizeof...(Axes)>;

    /// @}

    /// @name Constructors
    /// @{

    /// @brief Nullary constructor for unique pointers etc.
    Binning() { }

    /// @brief Constructs binning from vectors of axes' edges
    Binning(const std::initializer_list<typename Axes::EdgeT>&... edges)
        : _axes(Axes(edges)...) {
      updateMaskedBins();
    }

    /// @brief Constructs binning from Rvalue vectors of axes' edges
    Binning(std::initializer_list<typename Axes::EdgeT>&&... edges)
        : _axes(Axes(std::move(edges))...) {
      updateMaskedBins();
    }

    /// @brief Constructs binning from a sequence of axes
    Binning(const Axes&... axes)
        : _axes(axes...) {
      updateMaskedBins();
    }

    /// @brief Constructs binning from a sequence of Rvalue axes
    Binning(Axes&&... axes)
        : _axes(std::move(axes)...) {
      updateMaskedBins();
    }

    /// @brief Copy constructor.
    Binning(const Binning& other) : _axes(other._axes), _maskedIndices(other._maskedIndices) {}

    /// @brief Move constructor.
    Binning(Binning&& other) : _axes(std::move(other._axes)), _maskedIndices(std::move(other._maskedIndices)) {}

    /// @brief Copy assignment
    Binning& operator=(const Binning& other) {
      if (this != &other) {
        _axes = other._axes;
        _maskedIndices = other._maskedIndices;
      }
      return *this;
    }

    /// @brief Move assignment
    Binning& operator=(Binning&& other) {
      if (this != &other) {
        _axes = std::move(other._axes);
        _maskedIndices = std::move(other._maskedIndices);
      }
      return *this;
    }

    /// @}

    /// @name Indexing methods
    /// @{

    /// @brief calculates global index from array of local indices
    size_t localToGlobalIndex(const IndexArr& localIndices) const;

    /// @brief calculates array of local indices from a global index
    IndexArr globalToLocalIndices(size_t globalIndex) const;

    /// @brief assembles array of local indices for an array of input values
    IndexArr localIndicesAt(const EdgeTypesTuple& coords) const;

    /// @brief calculates global index for a given array of input values
    size_t globalIndexAt(const EdgeTypesTuple& coords) const;

    /// @brief Calculates indices of overflow bins.
    std::vector<size_t> overflowBins() const noexcept;

    /// @brief Alias for overflowBins.
    std::vector<size_t> calcOverflowBinsIndices() const noexcept {
      return overflowBins();
    }

    /// @brief Count number of overflow bins.
    size_t countOverflowBins(const size_t axisN) const noexcept;

    /// @brief Calculates indices of masked bins.
    std::vector<size_t> maskedBins() const noexcept { return _maskedIndices; }

    /// @brief Clear masked bins
    void clearMaskedBins() noexcept { _maskedIndices.clear(); }

    /// @brief Mask/Unmask bin with global index @a index
    void maskBin(const size_t index, const bool status = true);

    /// @brief Mask/Unmask bin with local @a localIndices
    void maskBin(const IndexArr& localIndices, const bool status = true);

    /// @brief Mask/Unmask bin at set of @ coords
    void maskBinAt(const EdgeTypesTuple& coords, const bool status = true) noexcept;

    /// @brief Mask/Unmask bins in list of global @a indices
    void maskBins(const std::vector<size_t>& indices, const bool status = true);

    /// @brief Mask a slice of the binning at local bin index @a idx along axis dimesnion @a dim
    void maskSlice(const size_t dim, const size_t idx, const bool status = true);

    /// @brief Check if bin is masked
    bool isMasked(const size_t i) const noexcept;

    /// @brief Calculates indices of visible bins.
    ///
    /// @note Masked bins still treated as (in principle) visible
    std::vector<size_t> visibleBins() const noexcept;

    /// @brief Check if bin is in visible range
    ///
    /// @note Masked bins still treated as (in principle) visible
    bool isVisible(const size_t i) const noexcept;

    /// @brief Calculates size of a binning slice.
    size_t calcSliceSize(const size_t pivotAxisN) const noexcept;

    /// @brief Calculates indices of bins located in the specified slices.
    /// @note Accept vector of pairs where pair.first is index of axis,
    /// and pair.second is slice pivot bins on this axis.
    std::vector<size_t> sliceIndices(std::vector<std::pair<size_t, std::vector<size_t>>>) const noexcept;

    /// @brief Calculates indices of bins located in the slice corresponding to
    /// bin at @a binN at @a axisN.
    std::vector<size_t> sliceIndices(size_t axisN, size_t binN) const noexcept;

    /// @brief Helper function to extract and mask index slices
    /// corresponding to masked bins along the axes
    void updateMaskedBins() noexcept {

      std::vector<std::pair<size_t, std::vector<size_t>>> slicePivots;
      auto extractMaskedBins = [&slicePivots, &axes = _axes](auto I) {
        using isContinuous = typename Binning::template is_CAxis<I>;

        if constexpr(isContinuous::value) {
          const auto& axis = std::get<I>(axes);
          slicePivots.push_back({I, {axis.maskedBins()} });
        }
      };

      // apply for all axes
      MetaUtils::staticFor<Dimension::value>(extractMaskedBins);

      // get indices along slice pivots and remove duplicates
      _maskedIndices = sliceIndices(slicePivots);
      std::sort(_maskedIndices.begin(), _maskedIndices.end());
      _maskedIndices.erase( std::unique(_maskedIndices.begin(), _maskedIndices.end()),
                            _maskedIndices.end() );
    }

    /// @}

    /// @name Transformations

    /// @{
    template <size_t... AxisNs>
    void mergeBins(
      std::decay_t<decltype(AxisNs, std::declval<std::pair<size_t, size_t>>())>... mergeRanges) noexcept;
    /// @}

    /// @name Comparisons to other Binning objects
    /// @{

    /// @brief checks if Binnings are compatible
    ///
    /// Binnings are compatible if they have the same number of axes,
    /// and those axes have the same bin edges
    bool isCompatible(const Binning<Axes...>& other) const noexcept;

    /// @}

    /// @name Getters
    /// @{

    /// @brief Extracts axis corresponding to dimension. Const version
    template <size_t I>
    const getAxisT<I>& axis() const noexcept;

    /// @brief Extracts axis corresponding to dimension. Non-const version
    template <size_t I>
    getAxisT<I>& axis() noexcept;

    template<size_t I>
    auto _getAxesExcept() const noexcept;

    /// @brief Constructs array of axes sizes
    IndexArr shape(const bool includeOverflows = false) const noexcept;

    /// @brief get dimension of Binning
    size_t dim() const noexcept;

    /// @brief get total number of bins in Binning
    size_t numBins(const bool includeOverflows = true, const bool includeMaskedBins = true) const noexcept;

    /// @brief get number of bins at axis
    size_t numBinsAt(const size_t axisN, const bool includeOverflows = true) const noexcept;

    /// @brief Return a coordinate tuple for bin @a index
    EdgeTypesTuple edgeTuple(const size_t index) const noexcept;

    /// @brief Templated version to get edges of axis I by value.
    ///
    /// +-inf edges are included, depending on the value of @a includeOverflows
    /// Needed by axis-specific version from StatsMixin
    template <size_t I, typename E = getEdgeT<I>>
    std::vector<E> edges(const bool includeOverflows = false) const noexcept {
      const auto& axis = std::get<I>(_axes);
      if (!includeOverflows && Binning::template is_CAxis<I>::value) {
        auto&& all_edges = axis.edges();
        typename std::vector<E> rtn;
        const size_t offset = all_edges.size() - 1;
        rtn.insert(rtn.end(), std::make_move_iterator(all_edges.begin()+1),
                              std::make_move_iterator(all_edges.begin()+offset));
        return rtn;
      }
      return axis.edges();
    }

    /// @brief Templated version to get bin widths of axis I by value.
    ///
    /// Overflows are included depending on @a includeOverflows
    /// Needed by axis-specific version from AxisMixin
    ///
    /// @note This version is only supported for continuous axes.
    template <size_t I, typename E = getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, std::vector<E>>
    widths(const bool includeOverflows = false) const noexcept {
      const auto& axis = std::get<I>(_axes);
      return axis.widths(includeOverflows);
    }

    /// @brief Templated version to get bin maxs of axis I by value.
    ///
    /// Overflows are included depending on @a includeOverflows
    /// Needed by axis-specific version from AxisMixin
    ///
    /// @note This version is only supported for continuous axes.
    template <size_t I, typename E = getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, std::vector<E>>
    maxs(const bool includeOverflows = false) const noexcept {
      const auto& axis = std::get<I>(_axes);
      return axis.maxs(includeOverflows);
    }

    /// @brief Templated version to get bin mins of axis I by value.
    ///
    /// Overflows are included depending on @a includeOverflows
    /// Needed by axis-specific version from AxisMixin
    ///
    /// @note This version is only supported for continuous axes.
    template <size_t I, typename E = getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, std::vector<E>>
    mins(const bool includeOverflows = false) const noexcept {
      const auto& axis = std::get<I>(_axes);
      return axis.mins(includeOverflows);
    }

    /// @brief Templated version to get bin mids of axis I by value.
    ///
    /// Overflows are included depending on @a includeOverflows
    /// Needed by axis-specific version from AxisMixin
    ///
    /// @note This version is only supported for continuous axes.
    template <size_t I, typename E = getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, std::vector<E>>
    mids(const bool includeOverflows = false) const noexcept {
      const auto& axis = std::get<I>(_axes);
      return axis.mids(includeOverflows);
    }

    /// @brief Get the lowest non-overflow edge of the axis
    ///
    /// @note This method is only supported for continuous axes
    template <size_t I, typename E = getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, E> min() const noexcept {
      const auto& axis = std::get<I>(_axes);
      assert(axis.numBins(true) > 2); // More than 2 overflow bins.
      return axis.min(1); // Bin 0 is the underflow bin.
    }

    /// @brief Get the highest non-overflow edge of the axis
    ///
    /// @note This method is only supported for continuous axes
    template <size_t I, typename E = getEdgeT<I>>
    std::enable_if_t<std::is_floating_point<E>::value, E> max() const noexcept {
      const auto& axis = std::get<I>(_axes);
      assert(axis.numBins(true) > 2); // More than 2 overflow bins.
      return axis.min(axis.numBins(true)-1); // Bin 0 is the underflow bin.
    }

    /// @brief Return the differential volume for bin @a index
    double dVol(const size_t index) const;

    /// @}

    /// @name I/O
    /// @{

    /// @brief Render axis setup for this binning
    void _renderYODA(std::ostream& os) const noexcept {
      // lambda that renders the axis edges
      auto edgePrinter = [&](auto I) {
        const auto& axis  = std::get<I>(_axes);
        if (axis.numBins()) {
          os << "Edges(A"+ std::to_string(I+1) + "): ";
          axis._renderYODA(os);
          os << "\n";
        }
      };
      // apply lambda to all axes
      MetaUtils::staticFor<Dimension::value>(edgePrinter);

      // render indices of masked bins
      if (_maskedIndices.size()) {
        std::vector<size_t> gaps(_maskedIndices.size());
        std::partial_sort_copy(begin(_maskedIndices), end(_maskedIndices), begin(gaps), end(gaps));
        //std::sort(_maskedIndices.begin(), _maskedIndices.end());
        os << "MaskedBins: [";
        for (size_t i = 0; i < gaps.size(); ++i) {
          if (i)  os << ", ";
          os << std::to_string(gaps[i]);
        }
        os << "]\n";
      }
    }

    /// @brief Render edges for this binning at index @a idx
    void _renderYODA(std::ostream& os, const size_t idx, const int width = 13) const {
      IndexArr localIndices = globalToLocalIndices(idx);
      // lambda that renders low/high edge or discrete value depending on the axis type
      auto edgePrinter = [&](auto I) {
        const auto& axis  = std::get<I>(_axes);
        axis._renderYODA(os, localIndices[I], width);
      };
      // apply lambda to all axes
      MetaUtils::staticFor<Dimension::value>(edgePrinter);
    }

    /// @}

  };


  template<typename... Axes>
  size_t Binning<Axes...>::localToGlobalIndex(const IndexArr& localIndices) const {
    size_t gIndex = 0;
    // std::string st_indices = "";
    // for (size_t iIndex = 0; iIndex < localIndices.size(); ++iIndex) {
    //   st_indices += "|";
    //   st_indices += std::to_string(localIndices[iIndex]);
    // }

    /// x + y*width + z*width*height + w*width*height*depth + ...
    IndexArr axesSizes = shape(true);
    for (size_t iIndex = 0; iIndex < localIndices.size(); ++iIndex) {
      size_t productOfBinSizes = 1;
      for (ssize_t iBinnedAxis = iIndex - 1; iBinnedAxis >= 0; --iBinnedAxis) {
        productOfBinSizes *= (axesSizes[iBinnedAxis]);
      }
      gIndex += localIndices[iIndex] * productOfBinSizes;
    }
    return gIndex;
  }

  template <typename... Axes>
  typename Binning<Axes...>::IndexArr
  Binning<Axes...>::globalToLocalIndices(size_t globalIndex) const {
    if (globalIndex >= numBins(true, true))  throw RangeError("Global index outside bin range");
    IndexArr localIndices{};

    IndexArr axesSizes = shape(true);

    for (ssize_t iIndex = localIndices.size()-1 ; iIndex >= 0; --iIndex){
      size_t productOfNestedBinSizes = 1;

      for (ssize_t iBinnedAxis = iIndex - 1; iBinnedAxis >= 0; --iBinnedAxis) {
        productOfNestedBinSizes *= (axesSizes[iBinnedAxis]);
      }

      // integer division to get the multiplier
      localIndices[iIndex] = globalIndex / productOfNestedBinSizes;
      // then left with only the remainder
      globalIndex = globalIndex % productOfNestedBinSizes;
    }
    return localIndices;
  }

  template<typename... Axes>
  typename Binning<Axes...>::IndexArr
  Binning<Axes...>::localIndicesAt(const EdgeTypesTuple& coords) const {
    IndexArr localIndices{};
    auto extractIndices = [&localIndices, &coords, &axes = _axes](auto I) {
                               const auto& coord = std::get<I>(coords);
                               const auto& axis  = std::get<I>(axes);

                               localIndices[I] = axis.index(coord);
                             };

    MetaUtils::staticFor<Dimension::value>(extractIndices);

    return localIndices;
  }

  template<typename... Axes>
  size_t Binning<Axes...>::globalIndexAt(const EdgeTypesTuple& coords) const {
    return localToGlobalIndex(localIndicesAt(coords));
  }

  template<typename... Axes>
  std::vector<size_t> Binning<Axes...>::overflowBins() const noexcept {
    IndexArr axesSizes = shape(true);
    std::vector<bool> isCAxis;

    auto getCAxisIndices = [&isCAxis](auto I){
      using isContinuous = typename Binning::template is_CAxis<I>;
      isCAxis.emplace_back(isContinuous::value);
    };

    MetaUtils::staticFor<Dimension::value>(getCAxisIndices);

    std::vector<std::pair<size_t, std::vector<size_t>>> slicePivots;
    slicePivots.reserve(isCAxis.size());

    for (size_t axisN = 0; axisN < isCAxis.size(); ++axisN) {
      if (isCAxis[axisN])
        slicePivots.push_back({axisN, {0, axesSizes[axisN]-1} });
      else
        slicePivots.push_back({axisN, {0} });
    }

    std::vector<size_t> res = sliceIndices(slicePivots);
    std::sort(res.begin(), res.end());
    res.erase( std::unique(res.begin(), res.end()), res.end() );
    return res;
  }


  /// @brief Helper function to count the number of under/other/overflow bins
  /// for a given axis @a axisN.
  ///
  /// Continuous axes have an underflow and an overflow bin (= 2).
  /// Discrete axes have an otherflow bin (= 1).
  template<typename... Axes>
  size_t Binning<Axes...>::countOverflowBins(const size_t axisN) const noexcept {
    std::vector<bool> CAxisIndices;

    auto getCAxisIndices = [&CAxisIndices](auto I){
      using isContinuous = typename Binning::template is_CAxis<I>;
      CAxisIndices.emplace_back(isContinuous::value);
    };

    MetaUtils::staticFor<Dimension::value>(getCAxisIndices);
    return CAxisIndices.at(axisN) + 1;
  }

  /// @brief Only visible in this translation unit.
  /*namespace {
    template<typename VecT, typename AxisT, typename IdxT>
    void appendIfCAxis(VecT& vec, AxisT& axis, IdxT I, std::true_type) {
      if(axis.maskedBins.size() != 0)
        vec.push_back({I, axis.maskedBins});
    }

    template<typename VecT, typename AxisT, typename IdxT>
    void appendIfCAxis(VecT& vec, AxisT& axis, IdxT I, std::false_type) {
      return;
    }
  }*/

  template<typename... Axes>
  void Binning<Axes...>::maskBin(const size_t index, const bool status) {
    Binning<Axes...>::maskBins({{index}}, status);
  }

  template<typename... Axes>
  void Binning<Axes...>::maskBin(const IndexArr& localIndices, const bool status) {
    const size_t gIndex = Binning<Axes...>::localToGlobalIndex(localIndices);
    Binning<Axes...>::maskBins({{gIndex}}, status);
  }

  template<typename... Axes>
  void Binning<Axes...>::maskBinAt(const EdgeTypesTuple& coords, const bool status) noexcept {
    const size_t gIndex = Binning<Axes...>::globalIndexAt(coords);
    Binning<Axes...>::maskBins({{gIndex}}, status);
  }

  template<typename... Axes>
  void Binning<Axes...>::maskBins(const std::vector<size_t>& indices, const bool status) {
    for (size_t i : indices) {
      const auto& itEnd = this->_maskedIndices.cend();
      const auto& res = std::find(this->_maskedIndices.cbegin(), itEnd, i);
      if (status && res == itEnd)  this->_maskedIndices.push_back(i);
      else if (!status && res != itEnd)  this->_maskedIndices.erase(res);
    }
  }

  template <typename... Axes>
  void Binning<Axes...>::maskSlice(const size_t dim, const size_t idx, const bool status) {
    //_binning.maskSlice(dim, idx, status);
    std::vector<std::pair<size_t, std::vector<size_t>>> slicePivot{{dim,{idx}}};
    std::vector<size_t> indices = Binning<Axes...>::sliceIndices(slicePivot);
    Binning<Axes...>::maskBins(indices, status);
  }

  template<typename... Axes>
  bool Binning<Axes...>::isMasked(const size_t i) const noexcept {
    const auto& itEnd = _maskedIndices.cend();
    return  std::find(_maskedIndices.cbegin(), itEnd, i) != itEnd;
  }

  template<typename... Axes>
  std::vector<size_t> Binning<Axes...>::visibleBins() const noexcept {
    std::vector<size_t> res;
    res.reserve(numBins(false));

    const std::vector<size_t> overflows = overflowBins();
    const auto& itEnd = overflows.cend();

    size_t nBins = numBins();
    for (size_t i=0; i<nBins; ++i) {
      if (std::find(overflows.cbegin(), itEnd, i) == itEnd) {
        res.push_back(i);
      }
    }
    return res;
  }

  template<typename... Axes>
  bool Binning<Axes...>::isVisible(const size_t i) const noexcept {
    const std::vector<size_t> overflows = overflowBins();
    const auto& itEnd = overflows.cend();
    return  std::find(overflows.cbegin(), itEnd, i) == itEnd;
  }

  template<typename... Axes>
  size_t Binning<Axes...>::calcSliceSize(const size_t pivotAxisN) const noexcept {
    const IndexArr axesSizes = shape(true);
    size_t sliceSize = 1;
    for (size_t iDim = 0; iDim < _dim; ++iDim) {
      if (iDim == pivotAxisN)
        continue;
      sliceSize *= (axesSizes[iDim]);
    }
    return sliceSize;
  }

  template<typename... Axes>
  std::vector<size_t>
  Binning<Axes...>::sliceIndices(std::vector<std::pair<size_t, std::vector<size_t>>> slicePivots) const noexcept {

    std::vector<size_t> slicesSizes;
    slicesSizes.reserve(slicePivots.size());
    size_t slicedIndicesVecSize = 0;

    for (const auto& slicePivot : slicePivots) {
      if(slicePivot.second.size() == 0)
        continue;

      const size_t& sliceSize = calcSliceSize(slicePivot.first);

      slicesSizes.emplace_back(sliceSize);
      slicedIndicesVecSize += sliceSize;
    }

    std::vector<size_t> slicedIndices;
    slicedIndices.reserve(slicedIndicesVecSize);

    auto appendSliceIndices = [&slicedIndices](std::vector<size_t>&& overflowSlice) {
      slicedIndices.insert(std::end(slicedIndices),
                           std::make_move_iterator(std::begin(overflowSlice)),
                           std::make_move_iterator(std::end(overflowSlice)));
    };

    for (const auto& slicePivot : slicePivots) {
      const size_t axisN = slicePivot.first;
      const auto& binPivots = slicePivot.second;

      for(const auto& binPivot : binPivots) {
        appendSliceIndices(sliceIndices(axisN, binPivot));
      }
    }

    return slicedIndices;
  }

  template<typename... Axes>
  std::vector<size_t> Binning<Axes...>::sliceIndices(const size_t axisN, const size_t binN) const noexcept {
    if(sizeof...(Axes) == 1) {
      return {binN};
    }
    /// x + y*width + (const value of pivot bin)*width*height + w*width*height*depth + ...
    const IndexArr axesSizes = shape(true);
    const size_t sliceSize = calcSliceSize(axisN);

    IndexArr multiIdx{};
    multiIdx[axisN] = binN;
    std::vector<size_t> slicedIndices;

    assert(axesSizes.size() != 0);
    slicedIndices.reserve(sliceSize);

    /* @note Iteratively generates permutations of multindex for fixed
    /// binN at axisN, e.g. (idx_1, idx_2, binN_axisN, idx_4)
    ///                      /        |          \         \
    ///       {0, axis1.size}  {0, axis2.size}   const    {0, axis4.size}
    ///
    /// Source: https://stackoverflow.com/a/30808351
    */
    size_t idxShift = axisN == 0 ? 1 : 0;

    size_t idx = idxShift;

    while (true) {
      slicedIndices.emplace_back(localToGlobalIndex(multiIdx));

      multiIdx[idx]++;

      while (multiIdx[idx] == axesSizes[idx] || idx == axisN) {
        // Overflow, we're done
        if (idx == axesSizes.size() - 1) {
          return slicedIndices;
        }

        if(idx != axisN)
          multiIdx[idx] = 0;

        idx++;

        if(idx != axisN)
          multiIdx[idx]++;
      }

      idx = idxShift;
    }

    return slicedIndices;
  }

  template <typename... Axes>
  template <size_t... AxisNs>
  void Binning<Axes...>::mergeBins(
    std::decay_t<decltype(AxisNs, std::declval<std::pair<size_t, size_t>>())>... mergeRanges) noexcept {

    ((void)axis<AxisNs>().mergeBins(mergeRanges), ...);
    updateMaskedBins();

  }


  template <typename... Axes>
  template <size_t I>
  const typename Binning<Axes...>::template getAxisT<I>&
  Binning<Axes...>::axis() const noexcept {
    return std::get<I>(_axes);
  }

  template <typename... Axes>
  template <size_t I>
  typename Binning<Axes...>::template getAxisT<I>&
  Binning<Axes...>::axis() noexcept {
    return std::get<I>(_axes);
  }


  template<typename... Axes>
  template<size_t I>
  auto Binning<Axes...>::_getAxesExcept() const noexcept {
    return MetaUtils::removeTupleElement<I>(_axes);
  }

  template<typename... Axes>
  typename Binning<Axes...>::IndexArr
  Binning<Axes...>::shape(const bool includeOverflows) const noexcept {
    IndexArr axesSizes{};
    auto extractSizes = [&axesSizes, &axes = _axes, &includeOverflows](auto I) {
                          const auto& axis = std::get<I>(axes);
                          axesSizes[I] = axis.numBins(includeOverflows);
                      };

    MetaUtils::staticFor<Dimension::value>(extractSizes);

    return axesSizes;
  }

  template<typename... Axes>
  size_t Binning<Axes...>::dim() const noexcept {
    return _dim;
  }


  template<typename... Axes>
  bool Binning<Axes...>::isCompatible(const Binning<Axes...>& other) const noexcept {
    // compatible if they have the same number of axes,
    // and those axes have the same bin edges
    if (_dim != other.dim())
      return false;

    std::array<bool, 1> isEqual{true};
    auto isEqAxes =
      [&isEqual, &axes1 = _axes, &axes2 = other._axes](auto I) {
        const auto& axis_lhs = std::get<I>(axes1);
        const auto& axis_rhs = std::get<I>(axes2);

        /// If one comparison fails, isEqal will stay false
        isEqual[0] &= axis_lhs.hasSameEdges(axis_rhs);
    };

    MetaUtils::staticFor<Dimension::value>(isEqAxes);

    return isEqual[0];
  }

  template<typename... Axes>
  size_t Binning<Axes...>::numBins(const bool includeOverflows, const bool includeMaskedBins) const noexcept {
    size_t nBins = 0;
    IndexArr axesSizes = shape(includeOverflows);
    assert(axesSizes.size() > 0);
    nBins = axesSizes[0];
    if constexpr (sizeof...(Axes) > 1) {
      for (size_t iDim = 1; iDim < _dim; ++iDim) {
        nBins *= (axesSizes[iDim]);
      }
    }
    const size_t maskedBins = includeMaskedBins? 0 : _maskedIndices.size();
    return nBins - maskedBins;
  }

  template<typename... Axes>
  size_t Binning<Axes...>::numBinsAt(const size_t axisN, const bool includeOverflows) const noexcept {
    IndexArr axesSizes = shape(includeOverflows);
    assert(axesSizes.size() > 0);
    return axesSizes[axisN];
  }

  template<typename... Axes>
  typename Binning<Axes...>::EdgeTypesTuple
  Binning<Axes...>::edgeTuple(const size_t index) const noexcept {

    EdgeTypesTuple coords;
    IndexArr indices = globalToLocalIndices(index);

    auto setCoords = [&coords, &indices, &axes = _axes](auto I) {
      using isContinuous = typename Binning::template is_CAxis<I>;
      const auto& axis = std::get<I>(axes);
      const size_t idx = std::get<I>(indices);
      if constexpr(isContinuous::value) {
        std::get<I>(coords) = axis.mid(idx);
      }
      else {
        std::get<I>(coords) = axis.edge(idx);
      }
    };
    MetaUtils::staticFor<Dimension::value>(setCoords);

    return coords;
  }

  template<typename... Axes>
  double Binning<Axes...>::dVol(const size_t index) const {
    double rtn = 1.0;
    IndexArr indices = globalToLocalIndices(index);

    auto getCAxisWidths = [&rtn, &indices, &axes = _axes](auto I){
      using isContinuous = typename Binning::template is_CAxis<I>;
      if constexpr (isContinuous::value) {
        const auto& axis = std::get<I>(axes);
        const size_t idx = std::get<I>(indices);
        rtn *= axis.width(idx);
      }
    };
    MetaUtils::staticFor<Binning::Dimension::value>(getCAxisWidths);

    return rtn;
  }

}

#endif
