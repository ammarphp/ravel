// -*- C++ -*-
//
// This file is part of YODA -- Yet more Objects for Data Analysis
// Copyright (C) 2008-2025 The YODA collaboration (see AUTHORS for details)
//
#ifndef YODA_Writer_h
#define YODA_Writer_h

#include "YODA/AnalysisObject.h"
#include "YODA/Utils/Traits.h"

#include <YODA/Config/BuildConfig.h>
#ifdef HAVE_HDF5
#ifdef WITH_HIGHFIVE
#include <YODA/highfive/H5File.hpp>
#else
#include <highfive/H5File.hpp>
#define YODA_H5 HighFive
#endif
#endif

#include <type_traits>
#include <fstream>
#include <iostream>

namespace YODA {


  static bool enableH5compression = Utils::getEnvParam("YODA_HDF5_COMPRESSION", true);

  /// Pure virtual base class for various output writers.
  class Writer {
  public:

    /// Virtual destructor
    virtual ~Writer() {}


    /// @name Writing a single analysis object.
    /// @{

    /// Write out object @a ao to file @a filename.
    void write(const std::string& filename, const AnalysisObject& ao);

    /// Write out object @a ao to output stream @a stream.
    void write(std::ostream& stream, const AnalysisObject& ao) {
      std::vector<const AnalysisObject*> vec{&ao};
      write(stream, vec);
    }

    /// Write out pointer-like object @a ao to output stream @a stream.
    template <typename T>
    typename std::enable_if_t<DerefableToAO<T>::value> //< -> void if valid
    write(std::ostream& stream, const T& ao) {
      write(stream, *ao);
    }

    /// Write out pointer-like object @a ao to file @a filename.
    template <typename T>
    typename std::enable_if_t<DerefableToAO<T>::value> //< -> void if valid
    write(const std::string& filename, const T& ao) {
      write(filename, *ao);
    }

    /// @}


    /// @name Writing multiple analysis objects by collection.
    /// @{

    /// Write out a vector of AO pointers (untemplated=exact type-match) to the given stream
    ///
    /// @note This is the canonical function for implementing AO writing to H5:
    /// all others call this.
    ///
    /// @note Among other reasons, this is non-inline to hide zstr from the public API
    #ifdef HAVE_HDF5
    void write(YODA_H5::File& file, const std::vector<const AnalysisObject*>& aos);
    #endif

    /// Write out a vector of AO pointers (untemplated=exact type-match) to the given stream
    ///
    /// @note This is the canonical function for implementing AO writing to stream:
    /// all others call this.
    ///
    /// @note Among other reasons, this is non-inline to hide zstr from the public API
    void write(std::ostream& stream, const std::vector<const AnalysisObject*>& aos, int precision = -1);


    /// Write out a collection of objects @a objs to output stream @a stream.
    ///
    /// @note The enable_if call checks whether RANGE is const_iterable, if yes the return
    ///       type is void. If not, this template will not be a candidate in the lookup
    template <typename RANGE>
    typename std::enable_if_t<CIterable<RANGE>::value>
    write(std::ostream& stream, const RANGE& aos) {
      write(stream, std::begin(aos), std::end(aos));
    }

    /// Write out a collection of objects @a objs to file @a filename.
    template <typename RANGE>
    typename std::enable_if_t<CIterable<RANGE>::value>
    write(const std::string& filename, const RANGE& aos) {
      write(filename, std::begin(aos), std::end(aos));
    }

    /// @}


    /// @name Writing multiple analysis objects by iterator range.
    /// @{

    /// Write out the objects specified by start iterator @a begin and end
    /// iterator @a end to output stream @a stream.
    ///
    /// @todo Add SFINAE trait checking for AOITER = DerefableToAO
    template <typename AOITER>
    void write(std::ostream& stream, const AOITER& begin, const AOITER& end, int precision = -1) {
      std::vector<const AnalysisObject*> vec;
      // vec.reserve(std::distance(begin, end));
      for (AOITER ipao = begin; ipao != end; ++ipao)  vec.push_back(&(**ipao));
      write(stream, vec, precision);
    }


    /// Write out the objects specified by start iterator @a begin and end
    /// iterator @a end to file @a filename.
    ///
    /// @todo Add SFINAE trait checking for AOITER = DerefableToAO
    template <typename AOITER>
    void write(const std::string& filename, const AOITER& begin, const AOITER& end) {
      std::vector<const AnalysisObject*> vec;
      // vec.reserve(std::distance(begin, end));
      for (AOITER ipao = begin; ipao != end; ++ipao)  vec.push_back(&(**ipao));

      if (filename != "-") {
        try {
          const size_t lastdot = filename.find_last_of(".");
          std::string fmt = Utils::toLower(lastdot == std::string::npos ? filename : filename.substr(lastdot+1));
          const bool compress = (fmt == "gz") || (fmt == "h5" && enableH5compression);
          useCompression(compress);
          #ifdef HAVE_HDF5
          // check if the requested format is H5
          if (Utils::startswith(fmt, "h5")) {
            try {
              YODA_H5::File h5(filename, YODA_H5::File::OpenOrCreate | YODA_H5::File::Truncate);
              write(h5, vec);
            } catch(...) {
              throw WriteError("Failed to open HDF5 file " + filename);
            }
            return;
          }
          #endif
          // try writing to stream
          std::ofstream stream;
          stream.exceptions(std::ofstream::failbit | std::ofstream::badbit);
          stream.open(filename.c_str());
          if (stream.fail())
            throw WriteError("Writing to filename " + filename + " failed");
          write(stream, vec);
        } catch (std::ofstream::failure& e) {
          throw WriteError("Writing to filename " + filename + " failed: " + e.what());
        }
      } else {
        try {
          write(std::cout, vec);
        } catch (std::runtime_error& e) {
          throw WriteError("Writing to stdout failed: " + std::string(e.what()));
        }
      }

    }

    /// @}

    /// Set precision of numerical quantities in this writer's output.
    void setPrecision(int precision) {
      _precision = precision;
    }

    /// Set precision of numerical quantities for current AO in this writer's output.
    void setAOPrecision(const bool needsDP = false) {
      if (needsDP)             _aoprecision = std::numeric_limits<double>::max_digits10;
      else if (_precision > 0) _aoprecision = _precision;
      else                     _aoprecision = 6;
    }

    /// Use libz compression?
    void useCompression(const bool compress=true) {
      _compress = compress;
    }


  protected:

    /// @name Main writer elements
    /// @{

    /// Write any opening boilerplate required by the format to @a stream
    virtual void writeHead(std::ostream&) {}

    /// @brief Write the body elements corresponding to AnalysisObject @a ao to @a stream
    virtual void writeBody(std::ostream& stream, const AnalysisObject* ao);

    /// @brief Write the body elements corresponding to AnalysisObject pointer @a ao to @a stream
    virtual void writeBody(std::ostream& stream, const AnalysisObject& ao);

    /// @brief Write the body elements corresponding to AnalysisObject @a ao to @a stream
    /// @note Requires that @a ao is dereferenceable to an AnalysisObject, via the DerefableToAO<T> trait,
    template <typename T>
    typename std::enable_if_t<DerefableToAO<T>::value> //< -> void if valid
    writeBody(std::ostream& stream, const T& ao) { writeBody(stream, *ao); }

    /// Write any closing boilerplate required by the format to @a stream
    virtual void writeFoot(std::ostream& stream) { stream << std::flush; }

    /// @}


    /// @name Specific AO type writer implementations, to be implemented in derived classes
    /// @{

    virtual void writeAO(std::ostream& stream, const AnalysisObject& ao) = 0;

    #ifdef HAVE_HDF5
    virtual void writeAOS(YODA_H5::File& file, const vector<const AnalysisObject*>& aos) = 0;
    #endif

    /// @}


    /// Output precision
    int _precision, _aoprecision;

    /// Compress the output?
    bool _compress;

  };


  /// Factory function to make a writer object by format name or a filename
  Writer& mkWriter(const std::string& format_name);


}

#endif
