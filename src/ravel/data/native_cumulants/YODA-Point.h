// -*- C++ -*-
//
// This file is part of YODA -- Yet more Objects for Data Analysis
// Copyright (C) 2008-2025 The YODA collaboration (see AUTHORS for details)
//
#ifndef YODA_POINT_H
#define YODA_POINT_H

#include "YODA/AnalysisObject.h"
#include "YODA/Exceptions.h"
#include "YODA/Transformation.h"
#include "YODA/Utils/MathUtils.h"
#include "YODA/Utils/PointUtils.h"
#include "YODA/Utils/Traits.h"
#include "YODA/Utils/ndarray.h"
#include <utility>
#include <algorithm>
#include <iostream>

namespace YODA {


  /// Base class for all Point*Ds, providing generic access to their numerical properties
  class Point {
  public:

    using ValuePair = std::pair<double,double>;
    using Pair = std::pair<double,double>;


    /// Virtual destructor for inheritance
    virtual ~Point() {};


    /// @name Core properties
    /// @{

    /// Space dimension of the point
    virtual size_t dim() const = 0;

    /// Get the point value for direction @a i
    virtual double val(size_t i) const = 0;

    /// Set the point value for direction @a i
    virtual void setVal(const size_t i, const double val) = 0;

    /// Clear the point values and errors
    virtual void clear() = 0;
    /// @}


    /// @name Errors
    /// @{

    /// Get error values for direction @a i
    //virtual const std::pair<double,double>& errs(size_t i) const = 0;
    /// Set symmetric error for direction @a i
    virtual void setErr(const size_t i, const double e) = 0;

    /// Set asymmetric error for direction @a i
    virtual void setErrs(const size_t i, const double eminus, const double eplus) = 0;

    /// Set error pair for direction @a i
    virtual void setErrs(const size_t i, const std::pair<double,double>& e) = 0;

    /// Get negative error value for direction @a i
    //virtual double errMinus(size_t i) const = 0;
    /// Set negative error for direction @a i
    virtual void setErrMinus(const size_t i, const double eminus) = 0;

    /// Get positive error value for direction @a i
    //virtual double errPlus(size_t i) const = 0;
    /// Set positive error for direction @a i
    virtual void setErrPlus(const size_t i, const double eplus) = 0;

    /// Get error values along axis @a i
    virtual Pair errs(const size_t i) const = 0;

    /// Get the minus error along axis @a i
    virtual double errMinus(const size_t i) const = 0;

    /// Get the plus error along axis @a i
    virtual double errPlus(const size_t i) const = 0;

    /// Get average error value for direction @a i
    virtual double errAvg(const size_t i) const = 0;

    /// Get value minus negative error along axis @a i
    virtual double min(const size_t i) const = 0;

    /// Get value plus positive error along axis @a i
    virtual double max(const size_t i) const = 0;

    /// @}


    /// @name Combined value and error setters
    /// @{

    /// Set value and symmetric error for direction @a i
    virtual void set(const size_t i, const double val, const double e) = 0;

    /// Set value and asymmetric error for direction @a i
    virtual void set(const size_t i, const double val, const double eminus, const double eplus) = 0;

    /// Set value and asymmetric error for direction @a i
    virtual void set(const size_t i, const double val, const std::pair<double,double>& e) = 0;

    /// @}


    /// @name Manipulations
    /// @{

    /// Scaling of direction @a i
    virtual void scale(const size_t i, const double scale) = 0;

    /// Scaling value along direction @a i
    virtual void scaleVal(const size_t i, const double scale) = 0;

    /// Scaling error along direction @a i
    virtual void scaleErr(const size_t i, const double scale) = 0;

    //template<typename FN>
    //void scale(size_t i, FN f) = 0;

    /// @}

  };





  /// The base for an N-dimensional data point to be contained in a Scatter<N>
  template<size_t N>
  class PointBase : public Point {
  protected:

     // Convenient aliases
     using Pair = std::pair<double,double>;
     using ValList = std::initializer_list<double>;
     using PairList = std::initializer_list<Pair>;

     // extract the content type of an array Arr
     template<typename Arr>
     using containedType = std::decay_t<decltype(*std::declval<Arr>().begin())>;

     // check if content type of an array Arr is Pair
     template<typename Arr>
     using containsPair = typename std::is_same<containedType<Arr>, Pair>;

     // succeeds if T is an iterable container
     template<typename T>
     using isIterable = std::enable_if_t<Iterable<T>::value>;

     // succeeds if T is an iterable container and its content type is Pair
     template<typename T, typename U>
     using isIterableWithPair = std::enable_if_t<(Iterable<T>::value && Iterable<U>::value && containsPair<U>::value)>;

  public:

    // Typedefs
    using NdVal = typename Utils::ndarray<double, N>;
    using NdValPair = typename Utils::ndarray<std::pair<double,double>, N>;
    using DataSize = std::integral_constant<size_t, 3*N>;


    /// @name Constructors
    /// @{

    /// @brief Default constructor
    PointBase() {
      clear();
    }


    /// @brief Constructor from position values without errors
    template <typename ValRange = ValList, typename = isIterable<ValRange>>
    PointBase(ValRange&& val) : _val(std::forward<ValRange>(val)) { }


    /// Constructor from values and a set of asymmetric errors
    template <typename ValRange = ValList,
              typename PairRange = PairList,
              typename = isIterableWithPair<ValRange,PairRange>>
    PointBase(ValRange&& val, PairRange&& errs)
      : _val(std::forward<ValRange>(val)), _errs(std::forward<PairRange>(errs)) { }

    /// Constructor from values and a set of symmetric errors
    template <typename ValRange = ValList, typename = isIterable<ValRange>>
    PointBase(ValRange&& val, ValRange&& errs)
       : _val(std::forward<ValRange>(val)) {
      if (val.size() != N || errs.size() != N)
        throw RangeError("Expected " + std::to_string(N) + " dimensions.");
      size_t i = 0;
      auto it = std::begin(errs);
      const auto& itEnd = std::end(errs);
      for (; it != itEnd; ++it) {
        _errs[i++] = std::make_pair(*it, *it);
      }
    }


    /// Constructor from values and a set of asymmetric errors
    template <typename ValRange = ValList, typename = isIterable<ValRange>>
    PointBase(ValRange&& val, ValRange&& errsdn, ValRange&& errsup)
       : _val(std::forward<ValRange>(val)) {
      if (val.size() != N || errsdn.size() != N || errsup.size() != N)
        throw RangeError("Expected " + std::to_string(N) + " dimensions.");
      size_t i = 0;
      auto itdn = std::begin(errsdn);
      auto itup = std::begin(errsup);
      const auto& itEnd = std::end(errsdn);
      for (; itdn != itEnd; ) {
        _errs[i++] = std::make_pair(*itdn++, *itup++);
      }
    }

    PointBase(const PointBase& p) : _val(p._val), _errs(p._errs) { }

    PointBase(PointBase&& p) : _val(std::move(p._val)), _errs(std::move(p._errs)) { }

    /// @}

    /// Space dimension of the point
    size_t dim() const { return N; }

    /// @name I/O
    /// @{

    void _renderYODA(std::ostream& os, const int width = 13) const noexcept {

      for (size_t i = 0; i < N; ++i) {
        os << std::setw(width) << std::left << _val[i] << "\t"
           << std::setw(width) << std::left << _errs[i].first  << "\t"
           << std::setw(width) << std::left << _errs[i].second << "\t";
      }
      os << "\n";

    }

    /// @}

    /// @name Modifiers
    /// @{

    /// Clear the point values and errors
    void clear() {
      for (size_t i = 0; i < N; ++i) {
        _val[i] = 0;
        _errs[i] = {0.,0.};
      }
    }

    /// Assignment operator
    PointBase& operator = (const PointBase& p) {
      if (this != &p) {
        _val = p._val;
        _errs = p._errs;
      }
      return *this;
    }

    /// Assignment operator
    PointBase& operator = (PointBase&& p) {
      if (this != &p) {
        _val = std::move(p._val);
        _errs = std::move(p._errs);
      }
      return *this;
    }

    /// @todo addError, addErrors, setErrors

    /// @}


  public:

    /// @name Coordinate accessors
    /// @{

    /// Get the coordinate vector
    NdVal& vals() { return _val; }

    /// Get the coordinate vector (const version)
    const NdVal& vals() const { return _val; }

    /// Get the value along direction @a i
    double val(size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      return _val[i];
    }

    /// Set the coordinate vector
    void setVal(const NdVal& val) {
      _val = val;
    }

    /// Set a specific coordinate
    void setVal(const size_t i, const double val) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      _val[i] = val;
    }

    /// @}


    /// @name Error accessors
    /// @{

    /// Get error values
    NdValPair& errs() {
      return _errs;
    }

    /// Get error values (const version)
    const NdValPair& errs() const {
      return _errs;
    }

    /// Get error values along axis @a i
    Pair errs(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      return _errs[i];
    }

    /// Get the minus error along axis @a i
    double errMinus(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      return _errs[i].first;
    }

    /// Get the plus error along axis @a i
    double errPlus(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      return _errs[i].second;
    }

    // Get the average error along axis @a i
    double errAvg(const size_t i) const {
      return 0.5*(errMinus(i) + errPlus(i));
    }

    /// Get value minus negative error along axis @a i
    double min(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      return _val[i] - _errs[i].first;
    }

    /// Get value plus positive error along axis @a i
    double max(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      return _val[i] + _errs[i].second;
    }

    /// Set a symmetric error pair along axis @a i
    void setErr(const size_t i, const double e) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      const double err = fabs(e);
      _errs[i] = { err, err};
    }

    /// Set an asymmetric error pair along axis @a i
    void setErrs(const size_t i, const double eminus, const double eplus) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      _errs[i] = { eminus, eplus};
    }

    /// Set a specific error pair along axis @a i
    void setErrs(const size_t i, const std::pair<double,double>& e) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      _errs[i] = e;
    }

    /// Set a specific minus error along axis @a i
    void setErrMinus(const size_t i, const double eminus) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      _errs[i].first = eminus;
    }

    /// Set a specific plus error along axis @a i
    void setErrPlus(const size_t i, const double eplus) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      _errs[i].second = eplus;
    }

    /// @}

    /// @name Combined value and error setters
    /// @{

    void set(const size_t i, const double val, const double e) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      const double err = fabs(e);
      _val[i] = val;
      _errs[i] = {err,err};
    }

    void set(const size_t i, const double val, const double eminus, const double eplus) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      _val[i] = val;
      _errs[i].first = eminus;
      _errs[i].second = eplus;
    }

    void set(const size_t i, const double val, const std::pair<double,double>& e) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      _val[i] = val;
      _errs[i] = e;
    }

    /// @}

    /// @name Scaling and transformations
    /// @{

    /// Scaling value along direction @a i
    void scaleVal(const size_t i, const double scale) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      _val[i] *= scale;
    }

    /// Scaling error along direction @a i
    void scaleErr(const size_t i, const double scale) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      _errs[i].first  *= scale;
      _errs[i].second *= scale;
    }

    /// Scaling along direction @a i
    void scale(const size_t i, const double scale) {
      scaleVal(i, scale);
      scaleErr(i, scale);
    }

    /// Uniform scaling
    void scale(const NdVal& scales) {
      for (size_t i = 0; i < N; ++i) {
        scale(i, scales[i]);
      }
    }

    /// Generalised transformations with functors
    void scale(const Trf<N>& trf) {
      trf.transform(_val, _errs);
    }

    /// Generalised transformations with functors
    /// along axis @a i
    void scale(const size_t i, const Trf<N>& trf) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      trf.transform(_val[i], _errs[i]);
    }
    //
    void transform(const size_t i, const Trf<N>& trf) {
      scale(i, trf);
    }

    /// @}

    /// @name MPI (de-)serialisation
    /// @{

    std::vector<double> _serializeContent() const noexcept {
      std::vector<double> rtn;
      rtn.reserve(DataSize::value);
      rtn.insert(rtn.end(), _val.begin(),  _val.end());
      for (auto err : _errs) {
        rtn.push_back(std::move(err.first));
        rtn.push_back(std::move(err.second));
      }
      return rtn;
    }

    void _deserializeContent(const std::vector<double>& data) {

      if (data.size() != DataSize::value)
        throw UserError("Length of serialized data should be "+std::to_string(DataSize::value)+"!");

      for (size_t i = 0; i < N; ++i) {
        _val[i] = data[i];
        _errs[i] = { data[N+i], data[2*N+i] };
      }

    }

    /// @}

  protected:

    /// @name Value and error variables
    /// @{

    NdVal _val;
    NdValPair _errs;

    /// @}

  };



  /// @name Comparison operators
  /// @{

  /// Equality test
  template <size_t N>
  inline bool operator==(const PointBase<N>& a, const PointBase<N>& b) {
    // Compare valitions
    for (size_t i = 0; i < N; ++i) {
      if ( !fuzzyEquals(a.vals()[i],        b.vals()[i]) )        return false;
      if ( !fuzzyEquals(a.errs()[i].first,  b.errs()[i].first))  return false;
      if ( !fuzzyEquals(a.errs()[i].second, b.errs()[i].second)) return false;
    }
    return true;
  }

  /// Inequality test
  template <size_t N>
  inline bool operator!=(const PointBase<N>& a, const PointBase<N>& b) {
    return !(a == b);
  }


  /// Less-than operator used to sort points
  template <size_t N>
  inline bool operator<(const PointBase<N>& a, const PointBase<N>& b) {
    #define LT_IF_NOT_EQ(a,b) { if (!fuzzyEquals(a, b)) return a < b; }
    for (size_t i = 0; i < N; ++i) {
      LT_IF_NOT_EQ(a.vals()[i],        b.vals()[i]);
      LT_IF_NOT_EQ(a.errs()[i].first,  b.errs()[i].first);
      LT_IF_NOT_EQ(a.errs()[i].second, b.errs()[i].second);
    }
    #undef LT_IF_NOT_EQ
    return false;
  }

  /// Less-than-or-equals operator used to sort points
  template <size_t N>
  inline bool operator<=(const PointBase<N>& a, const PointBase<N>& b) {
    if (a == b) return true;
    return a < b;
  }

  /// Greater-than operator used to sort points
  template <size_t N>
  inline bool operator>(const PointBase<N>& a, const PointBase<N>& b) {
    return !(a <= b);
  }

  /// Greater-than-or-equals operator used to sort points
  template <size_t N>
  inline bool operator>=(const PointBase<N>& a, const PointBase<N>& b) {
    return !(a < b);
  }

  /// @}

  template <size_t N>
  class PointND : public PointBase<N> {
    using BaseT = PointBase<N>;
    using BaseT::BaseT;
  };



  /// A 1D data point to be contained in a Scatter1D
  template <>
  class PointND<1> : public PointBase<1>,
                     public XDirectionMixin<PointND<1>> {
  public:

    using BaseT = PointBase<1>;
    using BaseT::BaseT;

    /// @name Constructors
    /// @{

    /// Constructor from values with optional symmetric errors
    PointND(double x, double ex=0.0)
      : BaseT({x}, {{ex, ex}}) {  }


    /// Constructor from values with explicit asymmetric errors
    PointND(double x, double exminus, double explus)
      : BaseT({x}, {{exminus, explus}}) {  }


    /// Constructor from values with asymmetric errors
    PointND(double x, const std::pair<double,double>& ex)
      : BaseT( {x}, {ex}) {  }


    /// Copy constructor
    PointND(const BaseT& other) : BaseT(other) {}

    /// Move constructor
    PointND(BaseT&& other) : BaseT(std::move(other)) {}

    /// @}


    /// @name Coordinate accessors
    /// @{

    /// Get the value along direction @a i
    double val(size_t i=0) const {
      if (i >= 1) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      return _val[i];
    }

    /// @}

  };



  /// A 2D data point to be contained in a Scatter2D
  template <>
  class PointND<2> : public PointBase<2>,
                     public XDirectionMixin<PointND<2>>,
                     public YDirectionMixin<PointND<2>> {
  public:

    using BaseT = PointBase<2>;
    using BaseT::BaseT;

    /// @name Constructors
    /// @{

    /// Constructor from values with optional symmetric errors
    PointND(double x, double y, double ex=0.0, double ey=0.0)
      : BaseT( {x,y}, {{ex,ex}, {ey,ey}}) {  }


    /// Constructor from values with explicit asymmetric errors
    PointND(double x, double y,
                 double exminus, double explus,
                 double eyminus, double eyplus)
      : BaseT({x,y}, {{exminus,explus}, {eyminus,eyplus}}) {  }


    /// Constructor from values with asymmetric errors on both x and y
    PointND(double x, double y, const std::pair<double,double>& ex, const std::pair<double,double>& ey)
      : BaseT({x,y}, {ex, ey}) {  }


    /// Copy constructor
    PointND(const BaseT& other) : BaseT(other) { }

    /// Move constructor
    PointND(BaseT&& other) : BaseT(std::move(other)) { }

    /// @}


    /// @name Manipulations
    /// @{

    /// Scaling of both axes
    void scaleXY(double scalex, double scaley) {
      scaleX(scalex);
      scaleY(scaley);
    }

    /// @}

  };



  /// A 3D data point to be contained in a Scatter3D
  template <>
  class PointND<3> : public PointBase<3>,
                     public XDirectionMixin<PointND<3>>,
                     public YDirectionMixin<PointND<3>>,
                     public ZDirectionMixin<PointND<3>> {
  public:

    using BaseT = PointBase<3>;
    using BaseT::BaseT;

    /// @name Constructors
    /// @{

    /// Constructor from values with optional symmetric errors
    PointND(double x, double y, double z, double ex=0.0, double ey=0.0, double ez=0.0)
      : BaseT({x,y,z}, {{ex,ex}, {ey,ey}, {ez,ez}}) { }


    /// Constructor from values with explicit asymmetric errors
    PointND(double x, double y, double z,
                 double exminus, double explus,
                 double eyminus, double eyplus,
                 double ezminus, double ezplus)
      : BaseT({x,y,z}, {{exminus,explus}, {eyminus,eyplus}, {ezminus,ezplus}}) { }

    /// Constructor from asymmetric errors given as vectors
    PointND(double x, double y, double z,
                 const std::pair<double,double>& ex,
                 const std::pair<double,double>& ey,
                 const std::pair<double,double>& ez)
      : BaseT({x,y,z}, {ex,ey,ez}) {  }


    /// Copy constructor
    PointND(const BaseT& other) : BaseT(other) { }

    /// Move constructor
    PointND(BaseT&& other) : BaseT(std::move(other)) { }

    /// @}

    /// @name Manipulations
    /// @{

    /// Scaling of both axes
    void scaleXYZ(double scalex, double scaley, double scalez) {
      scaleX(scalex);
      scaleY(scaley);
      scaleZ(scalez);
    }

    /// @}

  };


  /// @brief User-familiar alias
  using Point1D = PointND<1>;
  using Point2D = PointND<2>;
  using Point3D = PointND<3>;
  using Point4D = PointND<4>;

}

#endif
