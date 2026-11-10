/* RX_VK_ROWS: the Insert menu's rows set at given shown frames, for a test run with no one at the menu (vk_menu.cpp
   rows_script_tick): "<frame>:<ini key>=<value>,...", the rows by the keys and the values hookshot_options.ini saves them
   under (a number, or a size such as output_res=3840x2160). */
#pragma once

#include <cstdint>
#include <cstdio>
#include <cstdlib>

namespace mkwvk::rows_script {

struct Entry {
    unsigned long long frame = 0;
    char key[32] = {};
    char text[32] = {};   // (the value as written)
    int value = 0;        // (its number: a size's width)
};
enum class Next { Due, NotYet, Done, Malformed };

/// The entry at next for this shown frame: Due (e filled, next moved past it, null after the last), NotYet (its frame is
/// later), Done (none left) or Malformed (next left at it, for the log)
inline Next take(uint64_t frame, const char*& next, Entry& e) {
    if (!next || !*next) return Next::Done;
    int n = 0;
    if (sscanf(next, "%llu:%31[a-z0-9_]=%31[0-9xX-]%n", &e.frame, e.key, e.text, &n) != 3) return Next::Malformed;
    if (frame < e.frame) return Next::NotYet;
    e.value = atoi(e.text);
    next = next[n] == ',' ? next + n + 1 : nullptr;
    return Next::Due;
}

} // namespace mkwvk::rows_script
