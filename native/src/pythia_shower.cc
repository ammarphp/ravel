// Default path is unchanged. original-v1 is an explicitly requested observation.
// pythia_shower.cc — shower a hard process (internal or LHE) and write HepMC3.
// Usage: pythia_shower <pythia.cfg> <out.hepmc> [nEvents]
// The .cfg sets the process (internal) or `Beams:frameType=4` + `Beams:LHEF=<file>`.
#include "Pythia8/Pythia.h"
#include "Pythia8Plugins/HepMC3.h"
#include <iostream>
#include <string>
using namespace Pythia8;

int legacyMain(int argc, char* argv[]) {
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

// Candidate only: optional original-LHA sidecar; no compile/replay admission.
// The original shower/write loop is preserved. The sidecar calls const getters
// on Pythia's existing LHA object, before copying the event to HepMC.
// Usage: candidate <cfg> <out.hepmc> [nEvents] [--lhe-sidecar <NEW.jsonl>]
#include "Pythia8/Pythia.h"
#include "Pythia8Plugins/HepMC3.h"
#include <iostream>
#include <string>
#include <sstream>
#include <iomanip>
#include <limits>
#include <locale>
#include <cmath>
#include <stdexcept>
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>
using namespace Pythia8;

namespace {
std::string quote(const std::string& value) {
  std::ostringstream s;
  s << '"';
  for (unsigned char c : value) {
    if (c == '"' || c == '\\') s << '\\' << c;
    else if (c < 32) s << "\\u00" << std::hex << std::setw(2)
                       << std::setfill('0') << static_cast<int>(c) << std::dec;
    else s << c;
  }
  s << '"'; return s.str();
}
void number(std::ostream& out, double x) {
  if (!std::isfinite(x)) throw std::runtime_error("Nonfinite original LHA field");
  out << x;
}
std::string originalLHA(const LHAup& lha) {
  const int n = lha.sizePart() - 1; // The default reader retains a dummy entry0.
  if (n <= 0 || n > 10000) throw std::runtime_error("Invalid original LHA particle count");
  std::ostringstream s; s.imbue(std::locale::classic());
  s << std::showpoint << std::setprecision(std::numeric_limits<double>::max_digits10);
  s << "\"header\":[" << n << ',' << lha.idProcess() << ',';
  number(s,lha.weight()); s << ','; number(s,lha.scale()); s << ',';
  number(s,lha.alphaQED()); s << ','; number(s,lha.alphaQCD());
  s << "],\"particles\":[";
  for (int i=1; i<=n; ++i) {
    if (i>1) s << ',';
    s << '[' << lha.id(i) << ',' << lha.status(i) << ',' << lha.mother1(i)
      << ',' << lha.mother2(i) << ',' << lha.col1(i) << ',' << lha.col2(i);
    for (double x : {lha.px(i),lha.py(i),lha.pz(i),lha.e(i),lha.m(i),lha.tau(i),lha.spin(i)}) {
      s << ','; number(s,x);
    }
    s << ']';
  }
  s << ']'; return s.str();
}
class Sidecar {
  int fd = -1;
 public:
  bool active() const { return fd >= 0; }
  void openNew(const char* path) {
    fd = ::open(path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
    if (fd < 0) throw std::runtime_error("Cannot create new sidecar (no overwrite or symlink)");
  }
  void append(const std::string& value) {
    if (!active()) return;
    const std::string row=value+"\n";
    size_t done=0;
    while (done<row.size()) {
      const ssize_t n=::write(fd,row.data()+done,row.size()-done);
      if (n<0 && errno==EINTR) continue;
      if (n<=0) throw std::runtime_error("Sidecar write failed");
      done+=static_cast<size_t>(n);
    }
  }
  void closeChecked() {
    if (!active()) return;
    if (::fsync(fd)!=0) throw std::runtime_error("Sidecar fsync failed");
    const int old=fd; fd=-1;
    if (::close(old)!=0) throw std::runtime_error("Sidecar close failed");
  }
  ~Sidecar() { if (fd>=0) ::close(fd); }
};
}
int provenanceMain(int argc, char* argv[]) {
  const char* sidecarPath=nullptr; const char* count=nullptr;
  if (argc==4) count=argv[3];
  else if (argc==5 && std::string(argv[3])=="--lhe-sidecar") sidecarPath=argv[4];
  else if (argc==6 && std::string(argv[4])=="--lhe-sidecar") {count=argv[3];sidecarPath=argv[5];}
  else if (argc!=3) {
    std::cerr << "usage: candidate <cfg> <out.hepmc> [nEvents] [--lhe-sidecar <NEW.jsonl>]\n";
    return 1;
  }
  Sidecar sidecar; long nWritten=0, attempted=0; int iAbort=0;
  try {
    if (sidecarPath) sidecar.openNew(sidecarPath);
    Pythia pythia;
    if (!pythia.readFile(argv[1])) throw std::runtime_error("Pythia configuration could not be read completely");
    if (count && !pythia.readString(std::string("Main:numberOfEvents = ")+count)) throw std::runtime_error("Invalid event count");
    if (!pythia.init()) throw std::runtime_error("Pythia init failed");
    long nEvent=pythia.mode("Main:numberOfEvents");
    if (nEvent<=0) throw std::runtime_error("Event count must be positive");
    if (sidecar.active()) {
      if (pythia.mode("Beams:frameType")!=4 || !pythia.getLHAupPtr()) throw std::runtime_error("Sidecar requires an existing file LHA reader");
      sidecar.append("{\"type\":\"begin\",\"schema_version\":1,\"requested_events\":"+std::to_string(nEvent)+",\"floating_precision\":"+std::to_string(std::numeric_limits<double>::max_digits10)+",\"source\":\"existing_Pythia_getLHAupPtr\"}");
    }
    Pythia8ToHepMC toHepMC(argv[2]);
    int nAbort=10;
    for (long i=0; i<nEvent; ++i) {
      ++attempted;
      if (!pythia.next()) { if (++iAbort<nAbort) continue; else break; }
      std::string captured;
      if (sidecar.active()) {
        auto lha=pythia.getLHAupPtr();
        if (!lha) throw std::runtime_error("Original LHA pointer disappeared");
        captured=originalLHA(*lha);
      }
      if (!toHepMC.writeNextEvent(pythia)) throw std::runtime_error("HepMC event serialization failed");
      if (sidecar.active()) sidecar.append("{\"type\":\"event\",\"loop_index\":"+std::to_string(i)+",\"successful_index\":"+std::to_string(nWritten)+",\"hepmc_event_number\":"+std::to_string(toHepMC.event().event_number())+","+captured+"}");
      ++nWritten;
    }
    toHepMC.output().close();
    if (toHepMC.output().failed()) throw std::runtime_error("HepMC output did not close successfully");
    pythia.stat();
    std::cerr << "pythia_shower: wrote " << nWritten << " events; sigma = " << pythia.info.sigmaGen() << " mb\n";
    if (nWritten!=nEvent) throw std::runtime_error("Pythia did not produce the requested event count");
    sidecar.append("{\"type\":\"end\",\"events_written\":"+std::to_string(nWritten)+",\"attempted\":"+std::to_string(attempted)+",\"next_failures\":"+std::to_string(iAbort)+",\"complete\":true}");
    sidecar.closeChecked();
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "Provenance candidate failed: " << e.what() << "\n";
    try {
      sidecar.append("{\"type\":\"error\",\"events_written\":"+std::to_string(nWritten)+",\"attempted\":"+std::to_string(attempted)+",\"next_failures\":"+std::to_string(iAbort)+",\"message\":"+quote(e.what())+"}");
      sidecar.closeChecked();
    } catch (...) { std::cerr << "Sidecar failure evidence could not be completed\n"; }
    return 5; // No caller may accept a sidecar without both clean EOF and exit0.
  }
}

int main(int argc, char* argv[]) {
  if ((argc == 5 && std::string(argv[3]) == "--lhe-sidecar") ||
      (argc == 6 && std::string(argv[4]) == "--lhe-sidecar"))
    return provenanceMain(argc, argv);
  return legacyMain(argc, argv);
}
