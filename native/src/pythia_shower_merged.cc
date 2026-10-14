// pythia_shower_merged.cc — shower an MLM-merged LHE with ME/PS matching, write HepMC3.
// Usage: pythia_shower_merged <pythia.cfg> <out.hepmc> [nEvents] [--accounting <out.json>] [--djr <out.tsv>]
// The .cfg must set Beams:frameType=4 + Beams:LHEF and the JetMatching block
// (JetMatching:merge=on, scheme=1 for MadGraph ickkw=1 MLM). CombineMatchingInput
// reads those settings and registers the matching UserHook (the plain pythia_shower would
// double-count the matrix-element jets against the shower).
//
// nEvents is the number of LHE events to attempt. A vetoed event is not an error: the
// loop continues until nEvents have been attempted or the LHE file ends. The accounting
// file records attempted, accepted and vetoed counts and Pythia's own estimate of the
// matched cross section; the DJR file records, per accepted event, the number of
// matrix-element partons and the differential jet rates.
#include "Pythia8/Pythia.h"
#include "Pythia8Plugins/HepMC3.h"
#include "Pythia8Plugins/CombineMatchingInput.h"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <string>
using namespace Pythia8;

int main(int argc, char* argv[]) {
  if (argc < 3) {
    std::cerr << "usage: pythia_shower_merged <cfg> <out.hepmc> [nEvents] [--accounting FILE] [--djr FILE]\n";
    return 1;
  }
  std::string accountingPath, djrPath;
  long requested = -1;
  for (int i = 3; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--accounting" && i + 1 < argc) accountingPath = argv[++i];
    else if (arg == "--djr" && i + 1 < argc) djrPath = argv[++i];
    else if (requested < 0) requested = std::stol(arg);
    else { std::cerr << "unexpected argument " << arg << "\n"; return 1; }
  }
  Pythia pythia;
  if (!pythia.readFile(argv[1])) {
    std::cerr << "Pythia configuration could not be read completely\n";
    return 2;
  }
  if (requested > 0) pythia.readString("Main:numberOfEvents = " + std::to_string(requested));
  CombineMatchingInput combined;
  combined.setHook(pythia);                  // registers the MLM matching hook from the cfg
  if (!pythia.init()) { std::cerr << "Pythia init failed\n"; return 2; }
  auto matching = std::dynamic_pointer_cast<JetMatchingMadgraph>(combined.hook);

  Pythia8ToHepMC toHepMC(argv[2]);           // HepMC3 ASCII
  std::ofstream djr;
  if (!djrPath.empty()) {
    djr.open(djrPath);
    djr << "# n_me_partons djr...\n";
  }
  long nEvent = pythia.mode("Main:numberOfEvents");
  long attempted = 0, accepted = 0, failed = 0;
  bool endOfFile = false;
  while (nEvent <= 0 || attempted < nEvent) {
    bool ok = pythia.next();
    if (!ok && pythia.info.atEndOfFile()) { endOfFile = true; break; }
    ++attempted;
    if (!ok) { ++failed; continue; }        // matching veto (or a rejected event): not written
    if (!toHepMC.writeNextEvent(pythia)) {
      std::cerr << "HepMC event serialization failed\n";
      return 4;
    }
    ++accepted;
    if (djr.is_open() && matching) {
      djr << matching->nMEpartons().first;
      for (double value : matching->getDJR()) djr << ' ' << std::setprecision(10) << value;
      djr << '\n';
    }
  }
  toHepMC.output().close();
  if (toHepMC.output().failed()) {
    std::cerr << "HepMC output did not close successfully\n";
    return 4;
  }
  pythia.stat();
  std::cerr << "pythia_shower_merged: attempted " << attempted << ", accepted " << accepted
            << "; sigma = " << pythia.info.sigmaGen() << " mb (merged, matched)\n";
  if (!accountingPath.empty()) {
    std::ofstream out(accountingPath);
    out << std::setprecision(17)
        << "{\"schema_version\": 1, \"program\": \"pythia_shower_merged\", "
        << "\"pythia_version\": " << pythia.parm("Pythia:versionNumber") << ", "
        << "\"attempted\": " << attempted << ", \"accepted\": " << accepted << ", "
        << "\"not_accepted\": " << failed << ", \"end_of_file\": " << (endOfFile ? "true" : "false") << ", "
        << "\"n_tried\": " << pythia.info.nTried() << ", \"n_selected\": " << pythia.info.nSelected() << ", "
        << "\"n_accepted\": " << pythia.info.nAccepted() << ", "
        << "\"sigma_gen_mb\": " << pythia.info.sigmaGen() << ", \"sigma_err_mb\": " << pythia.info.sigmaErr()
        << "}\n";
    if (!out) { std::cerr << "accounting file could not be written\n"; return 4; }
  }
  if (accepted == 0) {
    std::cerr << "pythia_shower_merged: no event was accepted\n";
    return 3;
  }
  return 0;
}
