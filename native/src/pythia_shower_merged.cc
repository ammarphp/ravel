// pythia_shower_merged.cc — shower an MLM/CKKW-L-merged LHE WITH ME/PS matching, write HepMC3.
// Usage: pythia_shower_merged <pythia.cfg> <out.hepmc> [nEvents]
// The .cfg must set Beams:frameType=4 + Beams:LHEF and the JetMatching block
// (JetMatching:merge=on, scheme=1, setMad=on for MadGraph ickkw=1 MLM). CombineMatchingInput
// reads those settings and registers the matching UserHook (the plain pythia_shower would
// double-count the matrix-element jets against the shower — that is the whole point of merging).
#include "Pythia8/Pythia.h"
#include "Pythia8Plugins/HepMC3.h"
#include "Pythia8Plugins/CombineMatchingInput.h"
#include <iostream>
#include <string>
using namespace Pythia8;

int main(int argc, char* argv[]) {
  if (argc < 3) {
    std::cerr << "usage: pythia_shower_merged <cfg> <out.hepmc> [nEvents]\n";
    return 1;
  }
  Pythia pythia;
  pythia.readFile(argv[1]);
  if (argc >= 4) pythia.readString(std::string("Main:numberOfEvents = ") + argv[3]);
  CombineMatchingInput combined;
  combined.setHook(pythia);                  // registers the MLM/CKKW-L matching hook from the cfg
  if (!pythia.init()) { std::cerr << "Pythia init failed\n"; return 2; }

  Pythia8ToHepMC toHepMC(argv[2]);           // HepMC3 ASCII
  long nEvent = pythia.mode("Main:numberOfEvents");
  int  nAbort = 10, iAbort = 0;
  long nWritten = 0;
  for (long i = 0; i < nEvent; ++i) {
    if (!pythia.next()) { if (++iAbort < nAbort) continue; else break; }
    toHepMC.writeNextEvent(pythia);
    ++nWritten;
  }
  pythia.stat();
  std::cerr << "pythia_shower_merged: wrote " << nWritten << " events; sigma = "
            << pythia.info.sigmaGen() << " mb (merged, matched)\n";
  return 0;
}
