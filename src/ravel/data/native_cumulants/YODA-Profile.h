// -*- C++ -*-
//
// This file is part of YODA -- Yet more Objects for Data Analysis
// Copyright (C) 2008-2025 The YODA collaboration (see AUTHORS for details)
//
#ifndef YODA_Profile_h
#define YODA_Profile_h

#include "YODA/BinnedDbn.h"

namespace YODA {


  /// @brief Specialisation of the BinnedDbn for a 1D profile
  template <typename AxisT>
  class BinnedDbn<2, AxisT>
      : public DbnStorage<2, AxisT>,
        public XAxisMixin<BinnedDbn<2, AxisT>, AxisT>,
        public XStatsMixin<BinnedDbn<2, AxisT>> {
  public:

    using ProfileT = BinnedDbn<2, AxisT>;
    using BaseT = DbnStorage<2, AxisT>;
    using FillType = typename BaseT::FillType;
    using BinType = typename BaseT::BinT;
    using Ptr = std::shared_ptr<ProfileT>;

    /// @brief Inherit constructors.
    using BaseT::BaseT;

    BinnedDbn() = default;
    BinnedDbn(const ProfileT&) = default;
    BinnedDbn(ProfileT&&) = default;
    BinnedDbn& operator =(const ProfileT&) = default;
    BinnedDbn& operator =(ProfileT&&) = default;
    using AnalysisObject::operator =;

    /// @brief Copy constructor (needed for clone functions).
    ///
    /// @note Compiler won't generate this constructor automatically.
    BinnedDbn(const BaseT& other) : BaseT(other) {}
    //
    BinnedDbn(const ProfileT& other, const std::string& path) : BaseT(other, path) {}

    /// @brief Move constructor
    BinnedDbn(BaseT&& other) : BaseT(std::move(other)) {}
    //
    BinnedDbn(ProfileT&& other, const std::string& path) : BaseT(std::move(other), path) {}

    /// @brief Constructor with auto-setup of evenly spaced axes.
    ///
    /// The constructor argument uses double rather than EdgeT to
    /// allow for auto-conversion of int to double.
    ///
    /// @note This constructor is only supported when all axes are continuous.
    template <typename EdgeT = double, typename = enable_if_all_CAxisT<EdgeT, AxisT>>
    BinnedDbn(size_t nbins, double lower, double upper,
              const std::string& path = "", const std::string& title = "")
        : BaseT({nbins}, {{lower, upper}}, path, title) {}

    /// @brief Make a copy on the stack
    ProfileT clone() const noexcept {
      return ProfileT(*this);
    }

    /// @brief Make a copy on the heap
    ProfileT* newclone() const noexcept {
      return new ProfileT(*this);
    }

    /// @brief Fill function with an explicit coordinate.
    virtual int fill(const AxisT valX, const double valY, const double weight = 1.0, const double fraction = 1.0) {
      return BaseT::fill({valX, valY}, weight, fraction);
    }

    /// @brief Fill function with FillType.
    virtual int fill(FillType&& coords, const double weight = 1.0, const double fraction = 1.0) {
      return BaseT::fill(std::move(coords), weight, fraction);
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


  /// @brief Specialisation of the BinnedDbn for a 2D profile
  template <typename AxisT1, typename AxisT2>
  class BinnedDbn<3, AxisT1, AxisT2>
      : public DbnStorage<3, AxisT1, AxisT2>,
        public XAxisMixin<BinnedDbn<3, AxisT1, AxisT2>, AxisT1>,
        public XStatsMixin<BinnedDbn<3, AxisT1, AxisT2>>,
        public YAxisMixin<BinnedDbn<3, AxisT1, AxisT2>, AxisT2>,
        public YStatsMixin<BinnedDbn<3, AxisT1, AxisT2>> {
  public:

    using ProfileT = BinnedDbn<3, AxisT1, AxisT2>;
    using BaseT = DbnStorage<3, AxisT1, AxisT2>;
    using FillType = typename BaseT::FillType;
    using BinType = typename BaseT::BinT;
    using Ptr = std::shared_ptr<ProfileT>;

    /// @brief Inherit constructors.
    using BaseT::BaseT;

    BinnedDbn() = default;
    BinnedDbn(const ProfileT&) = default;
    BinnedDbn(ProfileT&&) = default;
    BinnedDbn& operator =(const ProfileT&) = default;
    BinnedDbn& operator =(ProfileT&&) = default;
    using AnalysisObject::operator =;

    /// @brief Copy constructor (needed for clone functions).
    ///
    /// @note Compiler won't generate this constructor automatically.
    BinnedDbn(const BaseT& other) : BaseT(other) {}
    //
    BinnedDbn(const ProfileT& other, const std::string& path) : BaseT(other, path) {}

    /// @brief Move constructor
    BinnedDbn(BaseT&& other) : BaseT(std::move(other)) {}
    //
    BinnedDbn(ProfileT&& other, const std::string& path) : BaseT(std::move(other), path) {}

    /// @brief Constructor with auto-setup of evenly spaced axes.
    ///
    /// The constructor argument uses double rather than EdgeT to
    /// allow for auto-conversion of int to double.
    ///
    /// @note This constructor is only supported when all axes are continuous.
    template <typename EdgeT = double, typename = enable_if_all_CAxisT<EdgeT, AxisT1, AxisT2>>
    BinnedDbn(size_t nbinsX, double lowerX, double upperX,
              size_t nbinsY, double lowerY, double upperY,
              const std::string& path = "", const std::string& title = "")
        : BaseT({nbinsX, nbinsY}, {{lowerX, upperX}, {lowerY, upperY}}, path, title) {}

    /// @brief Make a copy on the stack
    ProfileT clone() const noexcept {
      return ProfileT(*this);
    }

    /// @brief Make a copy on the heap
    ProfileT* newclone() const noexcept {
      return new ProfileT(*this);
    }

    /// @brief Fill function with two explicit coordinates.
    virtual int fill(const AxisT1 valX, const AxisT2 valY, const double valZ, const double weight = 1.0, const double fraction = 1.0) {
      return BaseT::fill({valX, valY, valZ}, weight, fraction);
    }

    /// @brief Fill function with FillType.
    virtual int fill(FillType&& coords, const double weight = 1.0, const double fraction = 1.0) {
      return BaseT::fill(std::move(coords), weight, fraction);
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



  /// @brief Specialisation of the BinnedDbn for a 2D profile
  template <typename AxisT1, typename AxisT2, typename AxisT3>
  class BinnedDbn<4, AxisT1, AxisT2, AxisT3>
      : public DbnStorage<4, AxisT1, AxisT2, AxisT3>,
        public XAxisMixin<BinnedDbn<4, AxisT1, AxisT2, AxisT3>, AxisT1>,
        public XStatsMixin<BinnedDbn<4, AxisT1, AxisT2, AxisT3>>,
        public YAxisMixin<BinnedDbn<4, AxisT1, AxisT2, AxisT3>, AxisT3>,
        public YStatsMixin<BinnedDbn<4, AxisT1, AxisT2, AxisT3>> {
  public:

    using ProfileT = BinnedDbn<4, AxisT1, AxisT2, AxisT3>;
    using BaseT = DbnStorage<4, AxisT1, AxisT2, AxisT3>;
    using FillType = typename BaseT::FillType;
    using BinType = typename BaseT::BinT;
    using Ptr = std::shared_ptr<ProfileT>;

    /// @brief Inherit constructors.
    using BaseT::BaseT;

    BinnedDbn() = default;
    BinnedDbn(const ProfileT&) = default;
    BinnedDbn(ProfileT&&) = default;
    BinnedDbn& operator =(const ProfileT&) = default;
    BinnedDbn& operator= (ProfileT&&) = default;
    using AnalysisObject::operator =;

    /// @brief Copy constructor (needed for clone functions).
    ///
    /// @note Compiler won't generate this constructor automatically.
    BinnedDbn(const BaseT& other) : BaseT(other) {}
    //
    BinnedDbn(const ProfileT& other, const std::string& path) : BaseT(other, path) {}

    /// @brief Move constructor
    BinnedDbn(BaseT&& other) : BaseT(std::move(other)) {}
    //
    BinnedDbn(ProfileT&& other, const std::string& path) : BaseT(std::move(other), path) {}

    /// @brief Constructor with auto-setup of evenly spaced axes.
    ///
    /// The constructor argument uses double rather than EdgeT to
    /// allow for auto-conversion of int to double.
    ///
    /// @note This constructor is only supported when all axes are continuous.
    template <typename EdgeT = double, typename = enable_if_all_CAxisT<EdgeT, AxisT1, AxisT2, AxisT3>>
    BinnedDbn(size_t nbinsX, double lowerX, double upperX,
              size_t nbinsY, double lowerY, double upperY,
              size_t nbinsZ, double lowerZ, double upperZ,
              const std::string& path, const std::string& title = "")
        : BaseT({nbinsX, nbinsY, nbinsZ},
                {{lowerX, upperX}, {lowerY, upperY},
                {lowerZ, upperZ}}, path, title) {}

    /// @brief Make a copy on the stack
    ProfileT clone() const noexcept {
      return ProfileT(*this);
    }

    /// @brief Make a copy on the heap
    ProfileT* newclone() const noexcept {
      return new ProfileT(*this);
    }

    /// @brief Fill function with three explicit coordinates.
    virtual int fill(const AxisT1 valX, const AxisT2 valY, const AxisT3 valZ, const double valZplus,
                                                   const double weight = 1.0, const double fraction = 1.0) {
      return BaseT::fill({valX, valY, valZ, valZplus}, weight, fraction);
    }

    /// @brief Fill function with FillType.
    virtual int fill(FillType&& coords, const double weight = 1.0, const double fraction = 1.0) {
      return BaseT::fill(std::move(coords), weight, fraction);
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

    /// @brief Bin access using local indices (const version)
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


  /// Define dimension-specific short-hands (Cython sugar)
  template<typename A1>
  using BinnedProfile1D = BinnedProfile<A1>;

  template <typename A1, typename A2>
  using BinnedProfile2D = BinnedProfile<A1, A2>;

  template <typename A1, typename A2, typename A3>
  using BinnedProfile3D = BinnedProfile<A1, A2, A3>;

  /// Anonymous namespace to limit visibility
  namespace {
    template <class T>
    struct ProfileMaker;

    template<size_t... Is>
    struct ProfileMaker<std::index_sequence<Is...>> {
      using type = BinnedProfile< std::decay_t<decltype((void)Is, std::declval<double>())>... >;
    };
  }

  /// @brief User-friendly name for the N-dimensional profile with all-continuous axes
  template<size_t N>
  using ProfileND = typename ProfileMaker<std::make_index_sequence<N>>::type;

  /// User-friendly familiar names (continuous axes only)
  using Profile1D = BinnedProfile<double>;
  using Profile2D = BinnedProfile<double,double>;
  using Profile3D = BinnedProfile<double,double,double>;

}

#endif

