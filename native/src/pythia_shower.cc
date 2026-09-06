// pythia_shower.cc — shower a hard process (internal or LHE) and write HepMC3.
// Usage: pythia_shower <pythia.cfg> <out.hepmc> [nEvents]
// The .cfg sets the process (internal) or `Beams:frameType=4` + `Beams:LHEF=<file>`.
#include "Pythia8/Pythia.h"
#include "Pythia8Plugins/HepMC3.h"
#include <iostream>
#include <string>
using namespace Pythia8;

int main(int argc, char* argv[]) {
  if (argc < 3) {
    std::cerr << "usage: pythia_shower <cfg> <out.hepmc> [nEvents]\n";
    return 1;
  }
  Pythia pythia;
  if (!pythia.readFile(argv[1])) {
    std::cerr << "Pythia configuration could not be read completely\n";
    return 2;
  }
  if (argc >= 4 && !pythia.readString(std::string("Main:numberOfEvents = ") + argv[3])) {
    std::cerr << "Invalid event count\n";
    return 2;
  }
  if (!pythia.init()) { std::cerr << "Pythia init failed\n"; return 2; }

  long nEvent = pythia.mode("Main:numberOfEvents");
  if (nEvent <= 0) {
    std::cerr << "Event count must be positive\n";
    return 2;
  }
  Pythia8ToHepMC toHepMC(argv[2]);            // writes HepMC3 ASCII
  int  nAbort = 10, iAbort = 0;
  long nWritten = 0;
  for (long i = 0; i < nEvent; ++i) {
    if (!pythia.next()) { if (++iAbort < nAbort) continue; else break; }
    if (!toHepMC.writeNextEvent(pythia)) {
      std::cerr << "HepMC event serialization failed\n";
      return 4;
    }
    ++nWritten;
  }
  toHepMC.output().close();
  if (toHepMC.output().failed()) {
    std::cerr << "HepMC output did not close successfully\n";
    return 4;
  }
  pythia.stat();
  std::cerr << "pythia_shower: wrote " << nWritten << " events; sigma = "
            << pythia.info.sigmaGen() << " mb\n";
  if (nWritten != nEvent) {
    std::cerr << "Pythia did not produce the requested event count\n";
    return 3;
  }
  return 0;
}
