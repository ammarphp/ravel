// -*- C++ -*-
#ifndef RIVET_RivetONNXrt_HH
#define RIVET_RivetONNXrt_HH

#include <algorithm>
#include <functional>
#include <iostream>
#include <map>
#include <numeric>

#include "Rivet/Tools/RivetPaths.hh"
#include "Rivet/Tools/Utils.hh"
#include "onnxruntime/onnxruntime_cxx_api.h"

namespace Rivet {


  /// @brief Simple interface class to take care of basic ONNX networks
  ///
  /// See analyses/examples/EXAMPLE_ONNX.cc for how to use this.
  ///
  /// @note A node is not a neuron but a single tensor of arbitrary dimension size
  class RivetONNXrt {
  public:

    // Suppress default constructor
    RivetONNXrt() = delete;

    /// Constructor
    RivetONNXrt(const string& filename, const string& runname = "RivetONNXrt", const int maxOrtThreads = 1) {

      // Set some ORT variables that need to be kept in memory
      _runName = runname;
      _env = std::make_unique<Ort::Env>(ORT_LOGGING_LEVEL_WARNING, runname.c_str());

      // Set up the ORT session options.
      Ort::SessionOptions sessionopts;

      // Has the user set RIVET_ORT_MAX_THREADS?
      const int envMaxOrtThreads = getEnvParam<int>("RIVET_ORT_MAX_THREADS", 0);

      // Set the max number of threads for ONNX RT to use. Beware, ORT is greedy!
      if (envMaxOrtThreads == 0) {
        // Default case: set to min(OMP_NUM_THREADS, analysis specified max)
        const int max_threads = getEnvParam<int>("OMP_NUM_THREADS", maxOrtThreads);
        const int used_threads = min(maxOrtThreads, max_threads);
        sessionopts.SetIntraOpNumThreads(used_threads);
        MSG_DEBUG("Using " << used_threads << " ORT threads");
      }
      // if env var specifies a max, take the min of this and the analysis specified
      else if (envMaxOrtThreads >= 1) {
        const int used_threads = min(maxOrtThreads, envMaxOrtThreads);
        MSG_DEBUG("Using " << used_threads << " ORT threads.");
        sessionopts.SetIntraOpNumThreads(used_threads);
      }
      // special debug mode: if envMaxOrtThreads is negative, force overwrite analysis default.
      else {
        MSG_WARNING("Using " << abs(envMaxOrtThreads)
                             << " ORT threads, as forced by the negative RIVET_ORT_MAX_THREADS value.");
        sessionopts.SetIntraOpNumThreads(abs(envMaxOrtThreads));
      }


      // Load the model
      try {
        _session = std::make_unique<Ort::Session>(*_env, filename.c_str(), sessionopts);
      }
      catch (const std::exception& e) {
        MSG_ERROR("Failure loading onnx file: " << e.what());
      }

      // Store network hyperparameters (input/output shape, etc.)
      getNetworkInfo();

      MSG_DEBUG(*this);
    }


    /// Given a multi-node input vector, populate and return the multi-node output vector
    ///
    /// @todo Expose template param for optional double-valued networks?
    template <typename T = float>
    vector<vector<T>> compute(const vector<vector<T>>& inputs) const {

      // Check that number of input nodes matches what the model expects
      if (inputs.size() != _inDims.size()) {
        throw DataError("Expected " + to_string(_inDims.size()) + " input nodes, " + "received "
                        + to_string(inputs.size()));
      }

      // Reject models with non-tensor outputs before running inference
      for (size_t i = 0; i < _outTypes.size(); ++i) {
        if (_outTypes[i] == ONNX_TENSOR_ELEMENT_DATA_TYPE_UNDEFINED)
          throw DataError("Output node " + to_string(i) + " (" + string(_outNames[i])
                          + ") is not a tensor — use computeMaps() for Seq(Map) outputs");
      }

      // Create input tensor objects from input data
      vector<Ort::Value> ort_input;
      ort_input.reserve(_inDims.size());
      auto memory_info = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
      for (size_t i = 0; i < _inDims.size(); ++i) {

        // Check that input data matches expected input node dimension
        if (inputs[i].size() != (size_t)_inDimsFlat[i]) {
          throw DataError("Expected flattened dimension " + to_string(_inDimsFlat[i]) + " for input node "
                          + to_string(i) + ", received " + to_string(inputs[i].size()));
        }

        // Check that input data matches expected input node type
        _checkTypes(inputs[i].data(), i); //< bit hacky, but minimises duplication

        ort_input.emplace_back(Ort::Value::CreateTensor<T>(memory_info, const_cast<T*>(inputs[i].data()),
                                                           inputs[i].size(), _inDims[i].data(),
                                                           _inDims[i].size()));
      }

      // Retrieve output tensors
      auto ort_output = _session->Run(Ort::RunOptions{nullptr}, _inNames.data(), ort_input.data(),
                                      ort_input.size(), _outNames.data(), _outNames.size());

      // Construct flattened values and return
      vector<vector<T>> outputs;
      outputs.resize(_outDims.size());
      for (size_t i = 0; i < _outDims.size(); ++i) {
        T* floatarr = ort_output[i].GetTensorMutableData<T>();
        outputs[i].assign(floatarr, floatarr + _outDimsFlat[i]);
      }
      return outputs;
    }


    /// Given a single-node input vector, populate and return the single-node output vector
    template <typename T = float>
    vector<T> compute(const vector<T>& inputs) const {
      if (_inDims.size() != 1 || _outDims.size() != 1) {
        throw("This method assumes a single input/output node!");
      }
      vector<vector<T>> wrapped_inputs = {inputs};
      vector<vector<T>> outputs = compute(wrapped_inputs);
      return outputs[0];
    }


    /// Given a multi-node input vector, return one map per Seq(Map(K,V)) output node.
    /// Tensor output nodes yield an empty map; use compute() for those.
    template <typename K = long, typename V = float>
    vector<map<K, V>> computeMaps(const vector<vector<V>>& inputs) const {

      if (inputs.size() != _inDims.size()) {
        throw DataError("Expected " + to_string(_inDims.size()) + " input nodes, " + "received "
                        + to_string(inputs.size()));
      }

      // Reject models where all outputs are tensors
      const bool has_seq_map = std::any_of(_outTypes.begin(), _outTypes.end(), [](auto t) {
        return t == ONNX_TENSOR_ELEMENT_DATA_TYPE_UNDEFINED;
      });
      if (!has_seq_map) throw DataError("No Seq(Map) outputs found in this model — use compute() instead");

      vector<Ort::Value> ort_input;
      ort_input.reserve(_inDims.size());
      auto memory_info = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
      for (size_t i = 0; i < _inDims.size(); ++i) {
        if (inputs[i].size() != (size_t)_inDimsFlat[i]) {
          throw DataError("Expected flattened dimension " + to_string(_inDimsFlat[i]) + " for input node "
                          + to_string(i) + ", received " + to_string(inputs[i].size()));
        }
        _checkTypes(inputs[i].data(), i);
        ort_input.emplace_back(Ort::Value::CreateTensor<V>(memory_info, const_cast<V*>(inputs[i].data()),
                                                           inputs[i].size(), _inDims[i].data(),
                                                           _inDims[i].size()));
      }

      auto ort_output = _session->Run(Ort::RunOptions{nullptr}, _inNames.data(), ort_input.data(),
                                      ort_input.size(), _outNames.data(), _outNames.size());

      vector<map<K, V>> outputs(_outDims.size());
      Ort::AllocatorWithDefaultOptions alloc;
      for (size_t i = 0; i < _outDims.size(); ++i) {
        if (ort_output[i].IsTensor()) continue; // tensor outputs return empty map
        // Unpack Seq(Map(K,V)): extract the map from the first batch element
        auto map_val = ort_output[i].GetValue(0, alloc);
        auto keys_val = map_val.GetValue(0, alloc);
        auto vals_val = map_val.GetValue(1, alloc);
        const int64_t n = keys_val.GetTensorTypeAndShapeInfo().GetShape()[0];
        const K* keys = keys_val.GetTensorMutableData<K>();
        const float* vals = vals_val.GetTensorMutableData<float>();
        for (int64_t j = 0; j < n; ++j) outputs[i][keys[j]] = static_cast<V>(vals[j]);
      }
      return outputs;
    }


    /// Single-node convenience overload: returns the map from a single Seq(Map(K,V)) output
    template <typename K = long, typename V = float>
    map<K, V> computeMap(const vector<V>& inputs) const {
      if (_inDims.size() != 1 || _outDims.size() != 1) {
        throw("This method assumes a single input/output node!");
      }
      return computeMaps<K, V>({inputs})[0];
    }


    /// Method to check if @a key exists in network metatdata
    bool hasKey(const std::string& key) const {
      Ort::AllocatorWithDefaultOptions allocator;
      return (bool)_metadata->LookupCustomMetadataMapAllocated(key.c_str(), allocator);
    }


    /// Method to retrieve value associated with @a key
    /// from network metadata and return value as type T
    template <typename T, typename std::enable_if_t<!is_iterable_v<T> | is_cstring_v<T>>>
    T retrieve(const std::string& key) const {
      Ort::AllocatorWithDefaultOptions allocator;
      Ort::AllocatedStringPtr res = _metadata->LookupCustomMetadataMapAllocated(key.c_str(), allocator);
      if (!res) {
        throw("Key '" + key + "' not found in network metadata!");
      }
      /*if constexpr (std::is_same<T, std::string>::value) {
        return res.get();
      }*/
      return lexical_cast<T>(res.get());
    }

    /// Template specialisation of retrieve for std::string
    std::string retrieve(const std::string& key) const {
      Ort::AllocatorWithDefaultOptions allocator;
      Ort::AllocatedStringPtr res = _metadata->LookupCustomMetadataMapAllocated(key.c_str(), allocator);
      if (!res) {
        throw("Key '" + key + "' not found in network metadata!");
      }
      return res.get();
    }

    /// Overload of retrieve for vector<T>
    template <typename T>
    vector<T> retrieve(const std::string& key) const {
      const vector<string> stringvec = split(retrieve(key), ",");
      vector<T> returnvec = {};
      for (const string& s : stringvec) {
        returnvec.push_back(lexical_cast<T>(s));
      }
      return returnvec;
    }

    /// Overload of retrieve for vector<T>, with a default return
    template <typename T>
    vector<T> retrieve(const std::string& key, const vector<T>& defaultreturn) const {
      try {
        return retrieve<T>(key);
      }
      catch (...) {
        return defaultreturn;
      }
    }

    std::string retrieve(const std::string& key, const std::string& defaultreturn) const {
      try {
        return retrieve(key);
      }
      catch (...) {
        return defaultreturn;
      }
    }

    /// Variation of retrieve method that falls back
    /// to @a defaultreturn if @a key cannot be found
    template <typename T, typename std::enable_if_t<!is_iterable_v<T> | is_cstring_v<T>>>
    T retrieve(const std::string& key, const T& defaultreturn) const {
      try {
        return retrieve<T>(key);
      }
      catch (...) {
        return defaultreturn;
      }
    }

    /// Printing function for debugging.
    friend std::ostream& operator<<(std::ostream& os, const RivetONNXrt& rort) {
      os << "RivetONNXrt Network Summary: \n";
      for (size_t i = 0; i < rort._inNames.size(); ++i) {
        os << "- Input node " << i << " name: " << rort._inNames[i];
        os << ", dimensions: (";
        for (size_t j = 0; j < rort._inDims[i].size(); ++j) {
          if (j) os << ", ";
          os << rort._inDims[i][j];
        }
        os << "), type (as ONNX enums): " << rort._inTypes[i] << "\n";
      }
      for (size_t i = 0; i < rort._outNames.size(); ++i) {
        os << "- Output node " << i << " name: " << rort._outNames[i];
        os << ", dimensions: (";
        for (size_t j = 0; j < rort._outDims[i].size(); ++j) {
          if (j) os << ", ";
          os << rort._outDims[i][j];
        }
        os << "), type (as ONNX enums): (" << rort._outTypes[i] << "\n";
      }
      return os;
    }

    /// Logger
    Log& getLog() const {
      string logname = "Rivet.RivetONNXrt." + _runName;
      return Log::getLog(logname);
    }


  private:

    /// @brief Extract and store key info about this network, for checking against inputs
    void getNetworkInfo() {

      Ort::AllocatorWithDefaultOptions allocator;

      // Retrieve network metadata
      _metadata = std::make_unique<Ort::ModelMetadata>(_session->GetModelMetadata());

      // Find out how many input nodes the model expects
      const size_t num_input_nodes = _session->GetInputCount();
      _inDimsFlat.reserve(num_input_nodes);
      _inTypes.reserve(num_input_nodes);
      _inDims.reserve(num_input_nodes);
      _inNames.reserve(num_input_nodes);
      _inNamesPtr.reserve(num_input_nodes);
      for (size_t i = 0; i < num_input_nodes; ++i) {
        // Retrieve input node name
        auto input_name = _session->GetInputNameAllocated(i, allocator);
        _inNames.push_back(input_name.get());
        _inNamesPtr.push_back(std::move(input_name));

        // Retrieve input node type
        auto in_type_info = _session->GetInputTypeInfo(i);
        auto in_tensor_info = in_type_info.GetTensorTypeAndShapeInfo();
        _inTypes.push_back(in_tensor_info.GetElementType());
        _inDims.push_back(in_tensor_info.GetShape());
      }

      // Fix negative shape values - appears to be an artefact of batch size issues.
      for (auto& dims : _inDims) {
        int64_t n = 1;
        for (auto& dim : dims) {
          if (dim < 0) dim = abs(dim);
          n *= dim;
        }
        _inDimsFlat.push_back(n);
      }
      // Find out how many output nodes the model expects
      const size_t num_output_nodes = _session->GetOutputCount();
      _outDimsFlat.reserve(num_output_nodes);
      _outTypes.reserve(num_output_nodes);
      _outDims.reserve(num_output_nodes);
      _outNames.reserve(num_output_nodes);
      _outNamesPtr.reserve(num_output_nodes);
      for (size_t i = 0; i < num_output_nodes; ++i) {
        // Retrieve output node name
        auto output_name = _session->GetOutputNameAllocated(i, allocator);
        _outNames.push_back(output_name.get());
        _outNamesPtr.push_back(std::move(output_name));

        // Retrieve output node type
        auto out_type_info = _session->GetOutputTypeInfo(i);
        if (out_type_info.GetONNXType() == ONNX_TYPE_TENSOR) {
          auto out_tensor_info = out_type_info.GetTensorTypeAndShapeInfo();
          _outTypes.push_back(out_tensor_info.GetElementType());
          _outDims.push_back(out_tensor_info.GetShape());
        }
        else {
          // Non-tensor output (e.g. Seq(Map) ZipMap from sklearn-onnx).
          // UNDEFINED flags this node for computeMaps(); compute() will reject it.
          _outTypes.push_back(ONNX_TENSOR_ELEMENT_DATA_TYPE_UNDEFINED);
          _outDims.push_back({-1});
        }
      }

      // Fix negative shape values - appears to be an artefact of batch size issues.
      for (auto& dims : _outDims) {
        int64_t n = 1;
        for (auto& dim : dims) {
          if (dim < 0) dim = abs(dim);
          n *= dim;
        }
        _outDimsFlat.push_back(n);
      }
    }


    /// Check for type mismatches (float overload)
    void _checkTypes(const float*, size_t inode) const {
      if (_inTypes[inode] != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT)
        throw DataError("ONNX network provided wrong input type (float)");
    }
    /// Check for type mismatches (double overload)
    void _checkTypes(const double*, size_t inode) const {
      if (_inTypes[inode] != ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE)
        throw DataError("ONNX network provided wrong input type (double)");
    }

  private:

    /// ONNX RT run name
    std::string _runName;

    /// ONNXrt environment for this session
    std::unique_ptr<Ort::Env> _env;

    /// ONNXrt session holiding the network
    std::unique_ptr<Ort::Session> _session;

    /// Network metadata
    std::unique_ptr<Ort::ModelMetadata> _metadata;

    /// Input/output node dimensions
    ///
    /// @note Each could be a multidimensional tensor
    vector<vector<int64_t>> _inDims, _outDims;

    /// Equivalent length for flattened input/output node structure
    vector<int64_t> _inDimsFlat, _outDimsFlat;

    /// Types of input/output nodes (as ONNX enums)
    vector<ONNXTensorElementDataType> _inTypes, _outTypes;

    /// Pointers to the ONNXrt inout/output node names
    vector<Ort::AllocatedStringPtr> _inNamesPtr, _outNamesPtr;

    /// C-style arrays of the input/output node names
    vector<const char*> _inNames, _outNames;
  };


  /// Typedef for a handle to an OONXrt object
  using RivetONNXrtPtr = unique_ptr<RivetONNXrt>;


  /// @brief Useful function for getting ONNX file paths
  ///
  /// Based on getDatafilePath from RivetYODA.cc
  inline string getONNXFilePath(const string& filename) {
    /// Try to find an ONNX file matching this analysis name
    const string path1 = findAnalysisDataFile(filename);
    if (!path1.empty()) return path1;
    throw Rivet::Error("Couldn't find an ONNX data file for '" + filename + "' " + "in the path "
                       + toString(getRivetDataPath()));
  }


  /// Function to get a RivetONNXrt object from an analysis name
  ///
  /// Use suffix to help disambiguate if an analysis requires
  /// multiple networks. The filename will be structured like
  /// ANALYSISNAME[-SUFFIX].EXTN .
  ///
  /// @todo When/if ONNXrt is fully integrated into Rivet, move to
  /// analysis class and remove the analysisname arg.
  inline RivetONNXrtPtr getONNX(const string& analysisname,
                                const string& suffix = "",
                                const string& extn = "onnx",
                                const int maxOrtThreads = 1) {
    const string fname = analysisname + (suffix.empty() ? "" : "-") + suffix + "." + extn;
    return make_unique<RivetONNXrt>(getONNXFilePath(fname), analysisname + "-onnxrt"s, maxOrtThreads);
  }


  /// Forward-compatibility typedefs, for when we eliminate the "Rivet" prefix
  /// @{
  using ONNXrt = RivetONNXrt;
  using ONNXrtPtr = RivetONNXrtPtr;
  ///@}


}

#endif
