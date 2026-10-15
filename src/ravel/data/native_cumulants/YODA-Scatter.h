// -*- C++ -*-
//
// This file is part of YODA -- Yet more Objects for Data Analysis
// Copyright (C) 2008-2025 The YODA collaboration (see AUTHORS for details)
//
#ifndef YODA_Scatter_h
#define YODA_Scatter_h

#include "YODA/AnalysisObject.h"
#include "YODA/Point.h"
#include "YODA/Transformation.h"
#include "YODA/Utils/Traits.h"
#include "YODA/Utils/ndarray.h"
#include <vector>
#include <set>
#include <string>
#include <utility>
#include <memory>

namespace YODA {


  /// Limit visibility
  namespace {

    // Checks that the first half of tuple arguments
    // can be cast to double and the second half
    // to pair<double,double>
    template<class T, class U, typename = void>
    struct HalfValsHalfPairs : std::false_type { };
    //
    template<class T, size_t... Is>
    struct HalfValsHalfPairs<T, std::index_sequence<Is...>,
                   std::enable_if_t<( std::is_same<double,
                                           std::common_type_t<std::tuple_element_t<Is,T>...,
                                           double>>::value && // first half double
                                      std::is_same<std::pair<double,double>,
                                           std::common_type_t<std::tuple_element_t<sizeof...(Is)+Is,T>...,
                                           std::pair<double,double>>>::value // second half pair<double,double>
                                    )>> : std::true_type { };
  }

  /// A base class for common operations on scatter types (Scatter1D, etc.)
  class Scatter {
  public:

    /// @todo Add a generic Scatter base class, providing reset(), rmPoint(), etc.

    /// Virtual destructor for inheritance
    virtual ~Scatter() {}

    /// Dimension of this data object
    virtual size_t dim() const noexcept = 0;


    /// @name Modifiers
    /// @{

    /// Clear all points
    virtual void reset() = 0;

    /// Scaling along direction @a i
    //virtual void scale(size_t i, double scale) = 0;

    /// @}


    ///////////////////////////////////////////////////


    /// Number of points in the scatter
    virtual size_t numPoints() const = 0;


    /// @name Point removers
    /// @{

    /// Remove the point with index @a index
    virtual void rmPoint(size_t index) = 0;

    /// Safely remove the points with indices @a indices
    virtual void rmPoints(std::vector<size_t> indices) {
      // remove points in decreasing order, so the numbering isn't invalidated mid-loop:
      std::sort(indices.begin(), indices.end(), std::greater<size_t>()); //< reverse-sort
      for (size_t i : indices) rmPoint(i);
    }

    /// @}


    /// @name Point inserters
    ///
    /// These don't currently make sense for a generic base class, but passing
    /// generic tuples of vals/errs would be quite nice.
    ///
    /// @{

    // /// Insert a new point, defined as the x value and no errors
    // void addPoint(double x) {
    //   Point1D thisPoint=Point1D(x);
    //   thisPoint.setParentAO(this);
    //   _points.insert(thisPoint);
    // }

    // /// Insert a new point, defined as the x value and symmetric errors
    // void addPoint(double x, double ex) {
    //   Point1D thisPoint=Point1D(x, ex);
    //   thisPoint.setParentAO(this);
    //   _points.insert(thisPoint);
    // }

    // /// Insert a new point, defined as the x value and an asymmetric error pair
    // void addPoint(double x, const std::pair<double,double>& ex) {
    //   Point1D thisPoint=Point1D(x, ex);
    //   thisPoint.setParentAO(this);
    //   _points.insert(thisPoint);
    // }

    // /// Insert a new point, defined as the x value and explicit asymmetric errors
    // void addPoint(double x, double exminus, double explus) {
    //   Point1D thisPoint=Point1D(x, exminus, explus);
    //   thisPoint.setParentAO(this);
    //   _points.insert(thisPoint);
    // }

    // /// Insert a collection of new points
    // void addPoints(const Points& pts) {
    //   for (const Point1D& pt : pts) addPoint(pt);
    // }

    /// @}


    // /// Equality operator
    // bool operator == (const Scatter1D& other) {
    //   return _points == other._points;
    // }

    // /// Non-equality operator
    // bool operator != (const Scatter1D& other) {
    //   return ! operator == (other);
    // }

  };




  /// A generic data type which is just a collection of n-dim data points with errors
  template <size_t N>
  class ScatterND : public AnalysisObject, public Scatter {
  protected:

     // Convenient aliases
     using Pair = std::pair<double,double>;
     using ValVec = std::vector<double>;
     using PairVec = std::vector<Pair>;
     using ValList = std::initializer_list<double>;
     using PairList = std::initializer_list<Pair>;

     // extract the content type of an array Arr
     template<typename Arr>
     using containedType = std::decay_t<decltype(*std::declval<Arr>().begin())>;

     // check if content type of an array Arr is Pair
     template<typename Arr>
     using containsPair = typename std::is_same<containedType<Arr>, Pair>;

     // succeeds if the first argument is vector<vector<double> (or similar iterable)
     // and the second argument is vector<vector<Pair>> (or similar iterable)
     template<typename T, typename U>
     using enableIfNestedArrayWithPair = std::enable_if_t<(isIterable<T,U,containedType<T>,containedType<U>> &&
                                                           containsPair<containedType<U>>::value)>;

     // check if every element in parameter pack can be cast to double
     template<typename... Args>
     using isAllVals = std::is_same<double, std::common_type_t<Args..., double>>;

     // check if every element in first half of parameter pack can be
     // cast to double and every element in the second half to Pair
     // (based on helper struct defined at the top of the file)
     template<typename... Args>
     using isHalfValsHalfPairs = HalfValsHalfPairs<std::tuple<Args...>, std::make_index_sequence<N>>;

  public:

    // Typedefs
    using NdVal = Utils::ndarray<double, N>;
    using NdValPair = Utils::ndarray<std::pair<double,double>, N>;
    using Point = PointND<N>;
    using Points = std::vector<Point>;
    using Ptr = std::shared_ptr<ScatterND>;
    using AnalysisObject::operator =;


    /// @name Constructors
    /// @{

    /// Empty constructor
    ScatterND(const std::string& path = "", const std::string& title="")
      : AnalysisObject("Scatter"+std::to_string(N)+"D", path, title) {  }

    /// Constructor from a set of points
    ScatterND(const Points& points,
              const std::string& path="", const std::string& title="")
      : AnalysisObject("Scatter"+std::to_string(N)+"D", path, title),
        _points(points) {  }

    /// Constructor from a set of rvalue points
    ScatterND(Points&& points,
              const std::string& path="", const std::string& title="")
      : AnalysisObject("Scatter"+std::to_string(N)+"D", path, title),
        _points(std::move(points)) {  }

    /// Constructor from a vector of position values with no errors
    template <typename ValRange = std::initializer_list<ValList>,
              typename = std::enable_if_t<isIterable<ValRange, containedType<ValRange>>>> // enable if is nested array
    ScatterND(ValRange&& positions, const std::string& path="", const std::string& title="")
      : AnalysisObject("Scatter"+std::to_string(N)+"D", path, title) {
      for (size_t i = 0; i < positions.size(); ++i) {
        addPoint(PointND<N>(std::forward<containedType<ValRange>>(positions[i])));
      }
    }

    /// Constructor from vectors of values for positions and a single set of symmetric errors
    template <typename ValRange = std::initializer_list<ValList>,
              typename = std::enable_if_t<isIterable<ValRange, containedType<ValRange>>>> // enable if is nested array
    ScatterND(ValRange&& positions, ValRange&& errors, const std::string& path="", const std::string& title="")
      : AnalysisObject("Scatter"+std::to_string(N)+"D", path, title) {
      if (positions.size() != errors.size()) throw RangeError("Number of errors doesn't match number of positions");
      for (size_t i = 0; i < positions.size(); ++i) {
        addPoint(PointND<N>(std::forward<containedType<ValRange>>(positions[i]),
                            std::forward<containedType<ValRange>>(errors[i])));
      }
    }

    /// Constructor from vectors of values for positions and a single set of symmetric errors
    template <typename ValRange = std::initializer_list<ValList>,
              typename PairRange = std::initializer_list<PairList>,
              typename = enableIfNestedArrayWithPair<ValRange,PairRange>>
    ScatterND(ValRange&& positions, PairRange&& errors, const std::string& path="", const std::string& title="")
      : AnalysisObject("Scatter"+std::to_string(N)+"D", path, title) {
      if (positions.size() != errors.size()) throw RangeError("Number of error pairs doesn't match number of positions");
      for (size_t i = 0; i < positions.size(); ++i) {
        addPoint(PointND<N>(std::forward<containedType<ValRange>>(positions[i]),
                            std::forward<containedType<PairRange>>(errors[i])));
      }
    }

    /// Copy constructor with optional new path
    ScatterND(const ScatterND<N>& s, const std::string& path = "")
      : AnalysisObject("Scatter"+std::to_string(N)+"D", (path != "")? path : s.path(), s, s.title()),
        _points(s._points)  { }

    /// Move constructor with optional new path
    ScatterND(ScatterND<N>&& s, const std::string& path = "")
      : AnalysisObject("Scatter"+std::to_string(N)+"D", (path != "")? path : s.path(), s, s.title()),
        _points(std::move(s._points))  {
    }


    /// Assignment operator
    ScatterND<N>& operator = (const ScatterND<N>& s) {
      if (this != &s) {
        AnalysisObject::operator = (s);
        _points = s._points;
      }
      return *this;
    }

    /// Move operator
    ScatterND<N>& operator = (ScatterND<N>&& s) {
      if (this != &s) {
        AnalysisObject::operator = (s);
        _points = std::move(s._points);
      }
      return *this;
    }

    /// Make a copy on the stack
    ScatterND<N> clone() const {
      return ScatterND<N>(*this);
    }

    /// Make a copy on the heap, via 'new'
    ScatterND<N>* newclone() const {
      return new ScatterND<N>(*this);
    }

    /// @}

    /// Dimension of this data object
    size_t dim() const noexcept { return N; }

    /// @name Modifiers
    /// @{

    /// Clear all points
    void reset() {
      _points.clear();
    }

    /// Scaling
    void scale(const NdVal& scales) {
      for (PointND<N>& p : _points) p.scale(scales);
    }

    void scale(const std::vector<double>& scales) {
      if (scales.size() != N) throw RangeError("Expected " + std::to_string(N) + " scale factors");
      for (PointND<N>& p : _points) p.scale(scales);
    }

    /// Scale value and error along direction @a i
    void scale(const size_t i, double factor) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      for (PointND<N>& p : _points) p.scale(i, factor);
    }

    /// Scale value along direction @a i
    void scaleVal(const size_t i, double factor) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      for (PointND<N>& p : _points) p.scaleVal(i, factor);
    }

    /// Scale error along direction @a i
    void scaleErr(const size_t i, double factor) {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      for (PointND<N>& p : _points) p.scaleErr(i, factor);
    }

    /// @}


    ///////////////////////////////////////////////////


    /// @name Point accessors
    /// @{

    /// Number of points in the scatter
    size_t numPoints() const {
      return _points.size();
    }


    /// Get the collection of points
    Points& points() {
      return _points;
    }


    /// Get the collection of points (const version)
    const Points& points() const {
      return _points;
    }


    /// Get a reference to the point with index @a index
    PointND<N>& point(size_t index) {
      return _points.at(index);
    }


    /// Get the point with index @a index (const version)
    const PointND<N>& point(size_t index) const {
      return _points.at(index);
    }

    /// @}


    /// @name Point inserters/removers
    /// @{

    /// Insert a new point
    ScatterND<N>& addPoint(const PointND<N>& pt) {
      _points.push_back(pt);
      return *this;
    }

    /// Insert a new rvalue point
    ScatterND<N>& addPoint(PointND<N>&& pt) {
      _points.push_back(std::move(pt));
      return *this;
    }

    /// Insert a new point from a position array (of N elements)
    template <typename ValRange = ValList,
              typename = std::enable_if_t<isIterable<ValRange>>>
    ScatterND<N>& addPoint(ValRange&& pos) {
      _points.push_back(PointND<N>(std::forward<ValRange>(pos)));
      return *this;
    }

    /// Insert a new point from position and symmetric error arrays (of N elements)
    template <typename ValRange = ValList,
              typename = std::enable_if_t<isIterable<ValRange>>>
    ScatterND<N>& addPoint(ValRange&& pos, ValRange&& err) {
      _points.push_back(PointND<N>(std::forward<ValRange>(pos), std::forward<ValRange>(err)));
      return *this;
    }

    /// Insert a new point from position and asymmetric error arrays (of N elements)
    template <typename ValRange = ValList,
              typename = std::enable_if_t<isIterable<ValRange>>>
    ScatterND<N>& addPoint(ValRange&& pos, ValRange&& errdn, ValRange&& errup) {
      _points.push_back(PointND<N>(std::forward<ValRange>(pos),
                                   std::forward<ValRange>(errdn),
                                   std::forward<ValRange>(errup)));
      return *this;
    }

    /// Insert a new point from a position and error-pair array
    template <typename ValRange = ValList, typename PairRange = PairList>
    auto addPoint(ValRange&& pos, PairRange&& err)
    -> std::enable_if_t<(isIterable<ValRange,PairRange> && containsPair<PairRange>::value), ScatterND<N>>& {
      _points.push_back(PointND<N>(pos, err));
      return *this;
    }

    /// Insert a new point from a parameter pack
    ///
    /// The deduction guide on the parameter pack asks
    /// that its length be 2N or 3N for dimension N.
    ///
    /// If accepted, the parameter pack is then forwarded as
    /// a tuple to the helper method addPoint_aux, which is
    /// overloaded to deal with the following three cases:
    ///
    /// Case 1: position and symmetric errors:
    ///         Scatter1D::addPoint(x, ex);
    ///         Scatter2D::addPoint(x,y, ex,ey);
    ///         ...
    /// Case 2: position and asymmetric errors:
    ///         Scatter1D::addPoint(x, exdn,exup);
    ///         Scatter2D::addPoint(x,y, exdn,eydn, exup,eyup);
    ///         ...
    /// Case 3: position and error pairs
    ///         Scatter1D::addPoint(x, make_pair(exdn,exup));
    ///         Scatter2D::addPoint(x,y, make_pair(exdn,eydn), make_pair(exup,eyup));
    ///         ...
    template<typename... Args>
    auto addPoint(Args&&... args)
    -> std::enable_if_t<(sizeof...(Args) == 2*N || sizeof...(Args) == 3*N), ScatterND<N>>& {
      return addPoint_aux(std::make_tuple(std::forward<Args>(args)...), std::make_index_sequence<N>{});
    }

    /// Insert a collection of new points
    ScatterND<N>& addPoints(Points pts) {
      for (const PointND<N>& pt : pts) addPoint(pt);
      return *this;
    }

    /// Remove the point with @a index
    void rmPoint(size_t index) {
      _points.erase(_points.begin()+index);
    }

    /// @}

  protected:

    /// Helper method to deal with parameter pack that
    /// has been forwarded as a tuple from addPoints.
    ///
    /// The deduction guide on the parameter pack asks
    /// that all arguments can be cast to double,
    /// thereby covering the following two cases:
    ///
    /// Case 1: position and symmetric errors:
    ///         Scatter1D::addPoint(x, ex);
    ///         Scatter2D::addPoint(x,y, ex,ey);
    ///         ...
    /// Case 2: position and asymmetric errors:
    ///         Scatter1D::addPoint(x, exdn,exup);
    ///         Scatter2D::addPoint(x,y, exdn,eydn, exup,eyup);
    ///         ...
    template<typename... Args, size_t... Is>
    auto addPoint_aux(std::tuple<Args...>&& t, std::index_sequence<Is...>)
    -> std::enable_if_t<(isAllVals<Args...>::value), ScatterND<N>>& {
      if constexpr(sizeof...(Args) == 2*N) { // Case 1: symmetric errors
        _points.push_back(
          PointND<N>( ValVec{  static_cast<double>(std::get<Is>(t))...},
                      PairVec{{static_cast<double>(std::get<N+Is>(t)),
                               static_cast<double>(std::get<N+Is>(t))}...} ));
      }
      else { // Case 2: asymmetric errors
        _points.push_back(PointND<N>( ValVec{  static_cast<double>(std::get<Is>(t))...},
                                      PairVec{{static_cast<double>(std::get<N+2*Is>(t)),
                                               static_cast<double>(std::get<N+2*Is+1>(t))}...} ));
      }
      return *this;
    }


    /// Helper method to deal with parameter pack that
    /// has been forwarded as a tuple from addPoints.
    ///
    /// The deduction guide on the parameter pack asks that
    /// its length be 2N for dimension N, that the first
    /// half of the arguments can be cast to double, and
    /// that the second half can be cast to Pair,
    /// thereby covering the following case:
    ///
    /// Case 3: position and error pairs
    ///         Scatter1D::addPoint(x, make_pair(exdn,exup));
    ///         Scatter2D::addPoint(x,y, make_pair(exdn,eydn), make_pair(exup,eyup));
    ///         ...
    template<typename... Args, size_t... Is>
    auto addPoint_aux(std::tuple<Args...>&& t, std::index_sequence<Is...>) // Case 3: error pairs
    -> std::enable_if_t<(sizeof...(Args) == 2*N && isHalfValsHalfPairs<Args...>::value), ScatterND<N>>& {
      _points.push_back(PointND<N>( ValVec{  static_cast<double>(std::get<Is>(t))...},
                                    PairVec{ static_cast<Pair>(std::get<N+Is>(t))...} ));
      return *this;
    }

  public:

    /// @name MPI (de-)serialisation
    /// @{

    size_t lengthContent(bool fixed_length = false) const noexcept {
      if (fixed_length) return 0;
      return numPoints() * Point::DataSize::value;
    }

    std::vector<double> serializeContent(bool fixed_length = false) const noexcept {

      if (fixed_length)  return { }; // cannot guarantee fixed length

      std::vector<double> rtn;
      rtn.reserve(lengthContent());
      for (size_t i = 0; i < numPoints(); ++i) {
        std::vector<double> pdata = point(i)._serializeContent();
        rtn.insert(std::end(rtn),
                   std::make_move_iterator(std::begin(pdata)),
                   std::make_move_iterator(std::end(pdata)));
      }
      return rtn;
    }

    void deserializeContent(const std::vector<double>& data) {

      if (data.size() % Point::DataSize::value)
        throw UserError("Length of serialized data should be a multiple of "+std::to_string(Point::DataSize::value)+"!");

      const size_t nPoints = data.size()/Point::DataSize::value;
      const auto itr = data.cbegin();
      reset();
      for (size_t i = 0; i < nPoints; ++i) {
        addPoint(Point());
        auto first = itr + i*Point::DataSize::value;
        auto last = first + Point::DataSize::value;
        point(i)._deserializeContent(std::vector<double>{first, last});
      }

    }

    /// @}

    /// @name Combining sets of scatter points
    /// @{

    /// @todo Better name?
    ScatterND<N>& combineWith(const ScatterND<N>& other) {
      addPoints(other.points());
      return *this;
    }

    /// @todo Better name?
    ScatterND<N>& combineWith(ScatterND<N>&& other) {
      addPoints(std::move(other._points));
      return *this;
    }

    /// @todo Better name?
    ScatterND<N>& combineWith(const std::vector< ScatterND<N> >& others) {
      for (const ScatterND<N>& s : others) combineWith(s);
      return *this;
    }

    /// @todo Better name?
    ScatterND<N>& combineWith(std::vector< ScatterND<N> >&& others) {
      for (ScatterND<N>&& s : others) combineWith(std::move(s));
      return *this;
    }

    /// @}

    /// @name Coordinate accessors
    /// @{

    /// Get the coordinate vector along axis @a i
    ValVec vals(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      ValVec rtn;  rtn.reserve(_points.size());
      for (const auto& pt : _points) {
        rtn.push_back( pt.val(i) );
      }
      return rtn;
    }

    /// Get the lowest value vector along axis @a i
    ValVec mins(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      ValVec rtn;  rtn.reserve(_points.size());
      for (const auto& pt : _points) {
        rtn.push_back( pt.min(i) );
      }
      return rtn;
    }

    /// Get the positive error vector along axis @a i
    ValVec maxs(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      ValVec rtn;  rtn.reserve(_points.size());
      for (const auto& pt : _points) {
        rtn.push_back( pt.max(i) );
      }
      return rtn;
    }

    /// Get the smallest central value along axis @a i
    double min(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      const ValVec cvals = vals(i);
      return *std::min_element(cvals.begin(), cvals.end());
    }

    /// Get the largest central value along axis @a i
    double max(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      const ValVec cvals = vals(i);
      return *std::max_element(cvals.begin(), cvals.end());
    }

    /// Get the error pairs along axis @a i
    PairVec errs(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      PairVec rtn;  rtn.reserve(_points.size());
      for (const auto& pt : _points) {
        rtn.push_back( pt.errs(i) );
      }
      return rtn;
    }

    /// Get the average error along axis @a i
    ValVec errAvgs(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      ValVec rtn;  rtn.reserve(_points.size());
      for (const auto& pt : _points) {
        rtn.push_back( pt.errAvg(i) );
      }
      return rtn;
    }

    /// Axis-specific alias
    ValVec xVals() const { return vals(0); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 2)>>
    ValVec yVals() const { return vals(1); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 3)>>
    ValVec zVals() const { return vals(2); }

    /// Axis-specific alias
    ValVec xMins() const { return mins(0); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 2)>>
    ValVec yMins() const { return mins(1); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 3)>>
    ValVec zMins() const { return mins(2); }

    /// Axis-specific alias
    ValVec xMaxs() const { return maxs(0); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 2)>>
    ValVec yMaxs() const { return maxs(1); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 3)>>
    ValVec zMaxs() const { return maxs(2); }

    /// Axis-specific alias
    double xMin() const {  return min(0); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 2)>>
    double yMin() const {  return min(1); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 3)>>
    double zMin() const {  return min(2); }

    /// Axis-specific alias
    double xMax() const {  return max(0); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 2)>>
    double yMax() const {  return max(1); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 3)>>
    double zMax() const {  return max(2); }

    /// Axis-specific alias
    PairVec xErrs() const {  return errs(0); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 2)>>
    PairVec yErrs() const {  return errs(1); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 3)>>
    PairVec zErrs() const {  return errs(2); }

    /// Axis-specific alias
    ValVec xErrAvgs() const {  return errAvgs(0); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 2)>>
    ValVec yErrAvgs() const {  return errAvgs(1); }

    /// Axis-specific alias
    template<size_t axisN = N, typename = std::enable_if_t<(axisN >= 3)>>
    ValVec zErrAvgs() const {  return errAvgs(2); }

    /// @}

    /// @name I/O
    /// @{

    /// @brief Render information about this AO
    void _renderYODA(std::ostream& os, const int width = 13) const noexcept {

      os << "# ";
      for (size_t i = 0; i < N; ++i) {
        os << std::setw(width - int(i? 0 : 2)) << std::left << ("val" + std::to_string(i+1)) << "\t"
           << std::setw(width) << std::left << ("err" + std::to_string(i+1) + "-") << "\t"
           << std::setw(width) << std::left << ("err" + std::to_string(i+1) + "+") << "\t";
      }
      os << "\n";

      for (const auto& pt : _points) {
        pt._renderYODA(os, width);
      }
    }

    /// @brief Render information about this AO
    void _renderFLAT(std::ostream& os, const int width = 13) const noexcept { _renderYODA(os, width); }

    /// @}

    /// @name Utilities
    /// @{

    std::vector<Pair> edges(const size_t i) const {
      if (i >= N) throw RangeError("Invalid axis int, must be in range 0..dim-1");
      std::vector<Pair> rtn;
      rtn.resize(numPoints());
      size_t j = 0;
      for (const Point& p : points()) {
        rtn[j++] = std::make_pair(p.min(i), p.max(i));
      }
      std::sort(rtn.begin(), rtn.end());
      rtn.erase(std::unique(rtn.begin(), rtn.end()), rtn.end());
      return rtn;
    }

    /// @}

  private:

    Points _points;

  };


  /// @name Combining scatters by merging sets of points
  /// @{

  template <int N>
  inline ScatterND<N> combine(ScatterND<N> a, const ScatterND<N>& b) {
    a.combineWith(b);
    return a;
  }

  template <int N>
  inline ScatterND<N> combine(ScatterND<N> a, ScatterND<N>&& b) {
    a.combineWith(std::move(b));
    return a;
  }

  template <int N>
  inline ScatterND<N> combine(const std::vector< ScatterND<N> >& scatters) {
    ScatterND<N> rtn;
    rtn.combineWith(scatters);
    return rtn;
  }

  template <int N>
  inline ScatterND<N> combine(std::vector< ScatterND<N> >&& scatters) {
    ScatterND<N> rtn;
    rtn.combineWith(std::move(scatters));
    return rtn;
  }

  /// @}


  //////////////////////////////////


  // /// @name Combining scatters: global operators, assuming aligned points
  // /// @{

  // /// Add two scatters
  // template <size_t N>
  // Scatter add(const Scatter& first, const Scatter& second);


  // /// Add two scatters
  // template <size_t N>
  // inline Scatter operator + (const Scatter& first, const Scatter& second) {
  //   return add(first, second);
  // }


  // /// Subtract two scatters
  // template <size_t N>
  // Scatter subtract(const Scatter& first, const Scatter& second);


  // /// Subtract two scatters
  // template <size_t N>
  // inline Scatter operator - (const Scatter& first, const Scatter& second) {
  //   return subtract(first, second);
  // }


  // /// Divide two scatters
  // template <size_t N>
  // Scatter divide(const Scatter& numer, const Scatter& denom);


  // /// Divide two scatters
  // template <size_t N>
  // inline Scatter operator / (const Scatter& numer, const Scatter& denom) {
  //   return divide(numer, denom);
  // }

  // /// @}


  //////////////////////////////////


  /// @name Generalised transformations
  /// @{

  template<size_t N>
  inline void transform(ScatterND<N>& s, const Trf<N>& fn, const size_t i) {
    for (auto& p : s.points()) {
      p.transform(i, fn);
    }
  }

  template<size_t N, typename FN>
  inline void transform(ScatterND<N>& s, const FN& fn, const size_t i) {
    transform(s, Trf<N>(fn), i);
  }

  template<size_t N, typename FN>
  inline void transformX(ScatterND<N>& s, const FN& fn) {
    transform(s, fn, 0);
  }

  template<size_t N, typename FN>
  inline void transformY(ScatterND<N>& s, const FN& fn) {
    transform(s, fn, 1);
  }

  template<size_t N, typename FN>
  inline void transformZ(ScatterND<N>& s, const FN& fn) {
    transform(s, fn, 2);
  }

  /// @}

  /// @name User friendly aliases
  /// @{

  using Scatter1D = ScatterND<1>;
  using Scatter2D = ScatterND<2>;
  using Scatter3D = ScatterND<3>;
  using Scatter4D = ScatterND<4>;
  using S1D = Scatter1D;
  using S2D = Scatter2D;
  using S3D = Scatter3D;
  using S4D = Scatter4D;

  /// @}


}

#endif
