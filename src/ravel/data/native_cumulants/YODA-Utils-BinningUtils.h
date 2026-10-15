// -*- C++ -*-
//
// This file is part of YODA -- Yet more Objects for Data Analysis
// Copyright (C) 2008-2025 The YODA collaboration (see AUTHORS for details)
//
#ifndef YODA_BinningUtils_h
#define YODA_BinningUtils_h

#include <type_traits>
#include <string>

namespace YODA {


  /// @name Helper methods to probe continuous/discrete axis properties.
  /// @{

  template <typename... EdgeT>
  using all_CAxes = typename std::conjunction<std::is_floating_point<EdgeT>...>;

  /// @brief Checks if all edge types are continuous.
  template <typename... EdgeT>
  using enable_if_all_CAxisT = std::enable_if_t<all_CAxes<EdgeT...>::value>;

  /// @brief Checks if edge type is continuous and returns edge type.
  template <typename EdgeT>
  using enable_if_CAxisT = std::enable_if_t<std::is_floating_point<EdgeT>::value, EdgeT>;

  /// @brief Checks if edge type is discrete and returns edge type.
  template <typename EdgeT>
  using enable_if_DAxisT = std::enable_if_t<!std::is_floating_point<EdgeT>::value, EdgeT>;

  /// @}

  /// @name Helper methods to stringify edge types
  /// @{

  /// @brief Returns the type ID as a character sequence
  ///
  /// d - double
  /// f - float
  /// i - int
  /// j - unsigned int
  /// m - size_t
  /// l - ssize_t
  template <typename T>
  struct TypeID {
    static const char* name() { return typeid(T).name(); }
  };

  /// @brief Specialisation for type string
  template <>
  struct TypeID<std::string> {
    static const char* name() { return "s"; }
  };

  /// @brief Helper function to construct the axis config
  template<typename A, typename... As>
  std::string mkAxisConfig() {
    return (std::string(TypeID<A>::name()) + ... + TypeID<As>::name());
  }

  /// @brief Helper function to construct the BinnedDbn and
  /// BinnedEstimate type names.
  template <ssize_t DbnN, typename A, typename... As>
  std::string mkTypeString() {

    constexpr size_t N = sizeof...(As)+1;

    if constexpr (all_CAxes<A, As...>::value) {
      if constexpr (DbnN < 0) {
        return "Estimate"+std::to_string(N)+"D";
      }
      if constexpr (DbnN == N+1) {
        return "Profile"+std::to_string(N)+"D";
      }
      if constexpr (DbnN == N) {
        return "Histo"+std::to_string(N)+"D";
      }
    }

    std::string type = "Binned";
    if (DbnN < 0)          type += "Estimate";
    else if (DbnN == N)    type += "Histo";
    else if (DbnN == N+1)  type += "Profile";
    else type += "Dbn" + std::to_string(DbnN);

    std::string axes = (TypeID<A>::name() + ... + (std::string{","} + TypeID<As>::name()));

    return (type + "<" + axes + ">");
  }

  /// @brief Same as above, but for non-Dbn bin contents.
  template <typename A, typename... As>
  std::string mkTypeString() {  return mkTypeString<-1, A, As...>(); }

  /// @}

}

#endif
