// Generic RooFit bridge to a captured, source-described objective.
#include <RooAbsReal.h>
#include <RooArgList.h>
#include <RooListProxy.h>
#include <functional>
#include <vector>

class RavelCachedObjective final : public RooAbsReal {
  RooListProxy coordinates_;
  std::function<double(const std::vector<double>&)> score_;
public:
  RavelCachedObjective(const char* name, const RooArgList& coordinates,
                       std::function<double(const std::vector<double>&)> score)
      : RooAbsReal(name, name), coordinates_("coordinates", "coordinates", this), score_(score) {
    coordinates_.add(coordinates);
  }
  RavelCachedObjective(const RavelCachedObjective& other, const char* name = nullptr)
      : RooAbsReal(other, name), coordinates_("coordinates", this, other.coordinates_), score_(other.score_) {}
  TObject* clone(const char* name) const override { return new RavelCachedObjective(*this, name); }
protected:
  double evaluate() const override {
    std::vector<double> values;
    for (int i = 0; i < coordinates_.getSize(); ++i)
      values.push_back(static_cast<const RooAbsReal*>(coordinates_.at(i))->getVal());
    return score_(values);
  }
};
