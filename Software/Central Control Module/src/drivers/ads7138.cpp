#include "ads7138.h"
namespace automaton::ccb::drivers {
bool Ads7138::probe() {
    wire_.beginTransmission(address_);
    return wire_.endTransmission() == 0;
}
}
