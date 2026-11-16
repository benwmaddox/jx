// GH Archive star count: WatchEvent count and distinct repo.name, several readers.
// usage: ghbench <mode> <file> [runs] [batch_mb]
//   od-sel      On-Demand iterate_many over NDJSON, reads only type and repo.name
//   od-full     On-Demand iterate_many, walks every value (strings unescaped, numbers parsed)
//   dom         DOM parse_many over NDJSON
//   od-sel-arr  On-Demand over one big array file ([ev,ev,...]), reads only type and repo.name
//   yy          yyjson DOM, one yyjson_read per line
// Prints load time and per-run processing time (file already in memory), plus counts.
#include "simdjson.h"
#include "yyjson.h"
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <unordered_map>
using namespace simdjson;
using clk = std::chrono::steady_clock;

struct Counts {
  uint64_t stars = 0;
  std::unordered_map<std::string, uint64_t> repos;
  void add(std::string_view name) { stars++; repos[std::string(name)]++; }
};

static uint64_t sink = 0;

static void walk(ondemand::value v) {
  switch (v.type().value()) {
  case ondemand::json_type::object:
    for (auto f : v.get_object()) { sink += f.unescaped_key().value().size(); walk(f.value().value()); }
    break;
  case ondemand::json_type::array:
    for (auto e : v.get_array()) walk(e.value());
    break;
  case ondemand::json_type::string: sink += v.get_string().value().size(); break;
  case ondemand::json_type::number: sink += (uint64_t)v.get_number().value().get_double(); break;
  case ondemand::json_type::boolean: sink += v.get_bool().value(); break;
  case ondemand::json_type::null: sink += v.is_null().value(); break;
  default: break;
  }
}

static bool is_watch(ondemand::raw_json_string r) { return r.is_equal("WatchEvent"); }

static void od_sel(const padded_string &buf, size_t batch, Counts &c) {
  ondemand::parser parser;
  ondemand::document_stream stream;
  if (parser.iterate_many(buf, batch).get(stream)) { fprintf(stderr, "iterate_many error\n"); exit(1); }
  for (auto doc : stream) {
    ondemand::object o = doc.get_object().value();
    if (!is_watch(o.find_field_unordered("type").get_raw_json_string().value())) continue;
    c.add(o.find_field_unordered("repo").find_field_unordered("name").get_string().value());
  }
  if (stream.truncated_bytes()) { fprintf(stderr, "truncated %zu\n", stream.truncated_bytes()); exit(1); }
}

static void od_full(const padded_string &buf, size_t batch, Counts &c) {
  ondemand::parser parser;
  ondemand::document_stream stream;
  if (parser.iterate_many(buf, batch).get(stream)) { fprintf(stderr, "iterate_many error\n"); exit(1); }
  for (auto doc : stream) {
    bool watch = false;
    std::string name;
    for (auto f : doc.get_object()) {
      std::string_view k = f.unescaped_key().value();
      ondemand::value v = f.value().value();
      if (k == "type") { watch = v.get_string().value() == "WatchEvent"; }
      else if (k == "repo") {
        for (auto g : v.get_object()) {
          std::string_view gk = g.unescaped_key().value();
          ondemand::value gv = g.value().value();
          if (gk == "name") name = std::string(gv.get_string().value()); else walk(gv);
        }
      } else walk(v);
    }
    if (watch) c.add(name);
  }
}

static void dom_run(const padded_string &buf, size_t batch, Counts &c) {
  simdjson::dom::parser parser;
  simdjson::dom::document_stream stream;
  if (parser.parse_many(buf, batch).get(stream)) { fprintf(stderr, "parse_many error\n"); exit(1); }
  for (auto r : stream) {
    simdjson::dom::element doc = r.value();
    if (doc["type"].get_string().value() != "WatchEvent") continue;
    c.add(doc["repo"]["name"].get_string().value());
  }
}

static void od_sel_arr(const padded_string &buf, Counts &c) {
  ondemand::parser parser(buf.size() + 64);
  ondemand::document doc = parser.iterate(buf).value();
  for (auto e : doc.get_array()) {
    ondemand::object o = e.get_object().value();
    if (!is_watch(o.find_field_unordered("type").get_raw_json_string().value())) continue;
    c.add(o.find_field_unordered("repo").find_field_unordered("name").get_string().value());
  }
}

static void yy(const padded_string &buf, Counts &c) {
  const char *p = buf.data(), *end = p + buf.size();
  while (p < end) {
    const char *nl = (const char *)memchr(p, '\n', end - p);
    if (!nl) nl = end;
    if (nl > p) {
      yyjson_doc *d = yyjson_read(p, nl - p, 0);
      if (!d) { fprintf(stderr, "yyjson error\n"); exit(1); }
      yyjson_val *root = yyjson_doc_get_root(d);
      if (yyjson_equals_str(yyjson_obj_get(root, "type"), "WatchEvent")) {
        yyjson_val *n = yyjson_obj_get(yyjson_obj_get(root, "repo"), "name");
        c.add(std::string_view(yyjson_get_str(n), yyjson_get_len(n)));
      }
      yyjson_doc_free(d);
    }
    p = nl + 1;
  }
}

int main(int argc, char **argv) {
  if (argc < 3) { fprintf(stderr, "usage: ghbench mode file [runs] [batch_mb]\n"); return 2; }
  std::string mode = argv[1];
  int runs = argc > 3 ? atoi(argv[3]) : 5;
  size_t batch = (argc > 4 ? atoi(argv[4]) : 4) * size_t(1) << 20;
  fprintf(stderr, "simdjson implementation: %s\n", get_active_implementation()->name().c_str());
  auto t0 = clk::now();
  padded_string buf = padded_string::load(argv[2]).value();
  double load = std::chrono::duration<double>(clk::now() - t0).count();
  double gb = buf.size() / 1e9;
  printf("%s load %.3f s (%.2f GB/s)\n", mode.c_str(), load, gb / load);
  for (int i = 0; i < runs; i++) {
    Counts c;
    auto t = clk::now();
    if (mode == "od-sel") od_sel(buf, batch, c);
    else if (mode == "od-full") od_full(buf, batch, c);
    else if (mode == "dom") dom_run(buf, batch, c);
    else if (mode == "od-sel-arr") od_sel_arr(buf, c);
    else if (mode == "yy") yy(buf, c);
    else { fprintf(stderr, "unknown mode\n"); return 2; }
    double s = std::chrono::duration<double>(clk::now() - t).count();
    printf("%s run %d: %.3f s  %.2f GB/s  (with load %.2f GB/s)  stars %llu repos %zu\n", mode.c_str(), i, s, gb / s,
           gb / (s + load), (unsigned long long)c.stars, c.repos.size());
  }
  return sink == 42 ? 1 : 0;
}
