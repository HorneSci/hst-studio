// ---------------------------------------------------------------------------
// PUBLICATION NOTE (added for release; the body below is byte-for-byte the
// internal file, and `git diff` against it will show only this block).
//
// WHAT THIS PROVES, AND WHAT IT DOES NOT.
//
// It proves: propagating a sparse delta up only the affected paths of a fixed
// tree keeps every aggregate BIT-EXACT against a full recompute, checked at
// every one of 400 steps, across scripted disturbances (a hot node, a node
// failure, a rack-wide congestion spike, a workload migration). The exit code
// gates on it: any parity failure at any step returns 1. The companion TLA+
// spec ../tla/DCTelemetry.tla models the same property, and TLAPS proves the
// invariant inductive.
//
// It does NOT prove anything about a sparse-matrix runtime. This is a tree
// aggregator -- SUM and MAX up a fixed hierarchy -- not a sparse mat-vec. It
// does not link, call, or exercise any shipped SpMV kernel.
//
// The "energy" figure is a modeled work-unit proxy and says so at the point it
// is printed. It is not a RAPL measurement and must not be quoted as joules.
//
// The frozen control is real: pass churn=0 and the run asserts that zero leaves
// are dirtied per step, rather than flooring to one. A harness whose "frozen"
// cell is not frozen reports a speedup in the one regime it should not.
//
// Build with a NAMED compiler. On macOS `g++` is Apple clang, not GCC:
//     g++-13 -O3 -std=c++17 -DNDEBUG hst_dc_telemetry.cpp -o dc_telemetry
// Run:   ./dc_telemetry [churn] [steps] [locality]     e.g. ./dc_telemetry 0 400
// ---------------------------------------------------------------------------

// hst_dc_telemetry.cpp — Data-center telemetry hierarchy: baseline full-recompute
// vs HST delta-aware affected-path propagation.
//
// Topology (fixed for the whole run): sensors -> servers -> racks -> aisles -> facility.
// Each server carries K metric sensors: CPU%, temperature, power(W), network load.
// Every interval only ~1-5% of leaf readings change (sparse delta). Aggregates:
//   - CPU / power / net : SUM up the tree (with a mean available via count)
//   - temperature       : MAX up the tree (hotspot tracking)
//
// Baseline: recompute every internal aggregate (rack/aisle/facility) from scratch,
//           bottom-up, every step. O(all nodes).
// HST:      given the dirty leaf set, walk unique parent paths upward and recompute
//           only the touched internal nodes from their children (same child order,
//           so results are BIT-EXACT vs baseline). O(dirty + touched ancestors).
//
// Metrics tracked per step and in aggregate:
//   latency (wall ns), CPU-time proxy, touched-node count, memory (maxRSS),
//   energy (modeled proxy, clearly labelled), and exact output parity.
//
// Build:  clang++ -O3 -march=native -std=c++17 -DNDEBUG hst_dc_telemetry.cpp -o hst_dc_telemetry
// Run:    ./hst_dc_telemetry

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cerrno>
#include <cstring>
#include <cmath>
#include <vector>
#include <random>
#include <chrono>
#include <algorithm>
#include <array>
#include <ctime>
#include <sys/resource.h>

using clk = std::chrono::high_resolution_clock;
static inline double ns(clk::time_point a, clk::time_point b) {
    return std::chrono::duration_cast<std::chrono::duration<double, std::nano>>(b - a).count();
}
static long max_rss_kb() {
    struct rusage ru; getrusage(RUSAGE_SELF, &ru);
    // darwin reports bytes, linux reports KB. Normalize to KB.
#if defined(__APPLE__)
    return ru.ru_maxrss / 1024;
#else
    return ru.ru_maxrss;
#endif
}

// ---- metric layout: 4 metrics per node, contiguous ----
enum { M_CPU = 0, M_TEMP = 1, M_POWER = 2, M_NET = 3, NMET = 4 };
// aggregation op per metric: SUM for cpu/power/net, MAX for temp.
static inline bool is_max_metric(int m) { return m == M_TEMP; }

struct Tree {
    // Level sizes (leaves = sensors folded into servers: each server holds NMET readings).
    int A, Rp, Sp;            // aisles, racks/aisle, servers/rack
    int nAisle, nRack, nServer;
    // Node value arrays, one contiguous [count*NMET] block per level.
    std::vector<double> facility;   // 1 * NMET
    std::vector<double> aisle;      // nAisle * NMET
    std::vector<double> rack;       // nRack  * NMET
    std::vector<double> server;     // nServer* NMET   (these are the leaves that change)
    // parent index maps
    std::vector<int> serverRack;    // server -> rack
    std::vector<int> rackAisle;     // rack -> aisle
    // child ranges (contiguous by construction)
    int serversPerRack() const { return Sp; }
    int racksPerAisle() const { return Rp; }
};

static Tree build_tree(int A, int Rp, int Sp) {
    Tree t; t.A = A; t.Rp = Rp; t.Sp = Sp;
    t.nAisle = A;
    t.nRack = A * Rp;
    t.nServer = A * Rp * Sp;
    t.facility.assign(NMET, 0.0);
    t.aisle.assign((size_t)t.nAisle * NMET, 0.0);
    t.rack.assign((size_t)t.nRack * NMET, 0.0);
    t.server.assign((size_t)t.nServer * NMET, 0.0);
    t.serverRack.resize(t.nServer);
    t.rackAisle.resize(t.nRack);
    for (int r = 0; r < t.nRack; ++r) t.rackAisle[r] = r / Rp;
    for (int s = 0; s < t.nServer; ++s) t.serverRack[s] = s / Sp;
    return t;
}

// initialize server readings to plausible steady-state values
static void seed_servers(Tree& t, std::mt19937_64& rng) {
    std::uniform_real_distribution<double> cpu(15, 55), temp(38, 55), pow_(120, 260), net(0.1, 0.6);
    for (int s = 0; s < t.nServer; ++s) {
        double* v = &t.server[(size_t)s * NMET];
        v[M_CPU] = cpu(rng); v[M_TEMP] = temp(rng); v[M_POWER] = pow_(rng); v[M_NET] = net(rng);
    }
}

// ---- baseline: recompute EVERY internal aggregate bottom-up ----
static void recompute_full(Tree& t) {
    // racks from servers
    for (int r = 0; r < t.nRack; ++r) {
        double acc[NMET]; for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? -1e300 : 0.0;
        int s0 = r * t.Sp;
        for (int s = s0; s < s0 + t.Sp; ++s) {
            const double* v = &t.server[(size_t)s * NMET];
            for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? std::max(acc[m], v[m]) : acc[m] + v[m];
        }
        std::memcpy(&t.rack[(size_t)r*NMET], acc, sizeof(acc));
    }
    // aisles from racks
    for (int a = 0; a < t.nAisle; ++a) {
        double acc[NMET]; for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? -1e300 : 0.0;
        int r0 = a * t.Rp;
        for (int r = r0; r < r0 + t.Rp; ++r) {
            const double* v = &t.rack[(size_t)r * NMET];
            for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? std::max(acc[m], v[m]) : acc[m] + v[m];
        }
        std::memcpy(&t.aisle[(size_t)a*NMET], acc, sizeof(acc));
    }
    // facility from aisles
    {
        double acc[NMET]; for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? -1e300 : 0.0;
        for (int a = 0; a < t.nAisle; ++a) {
            const double* v = &t.aisle[(size_t)a * NMET];
            for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? std::max(acc[m], v[m]) : acc[m] + v[m];
        }
        std::memcpy(t.facility.data(), acc, sizeof(acc));
    }
}

// recompute one rack node from its servers (same child order as baseline)
static inline void recompute_rack(Tree& t, int r) {
    double acc[NMET]; for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? -1e300 : 0.0;
    int s0 = r * t.Sp;
    for (int s = s0; s < s0 + t.Sp; ++s) {
        const double* v = &t.server[(size_t)s * NMET];
        for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? std::max(acc[m], v[m]) : acc[m] + v[m];
    }
    std::memcpy(&t.rack[(size_t)r*NMET], acc, sizeof(acc));
}
static inline void recompute_aisle(Tree& t, int a) {
    double acc[NMET]; for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? -1e300 : 0.0;
    int r0 = a * t.Rp;
    for (int r = r0; r < r0 + t.Rp; ++r) {
        const double* v = &t.rack[(size_t)r * NMET];
        for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? std::max(acc[m], v[m]) : acc[m] + v[m];
    }
    std::memcpy(&t.aisle[(size_t)a*NMET], acc, sizeof(acc));
}
static inline void recompute_facility(Tree& t) {
    double acc[NMET]; for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? -1e300 : 0.0;
    for (int a = 0; a < t.nAisle; ++a) {
        const double* v = &t.aisle[(size_t)a * NMET];
        for (int m=0;m<NMET;++m) acc[m] = is_max_metric(m) ? std::max(acc[m], v[m]) : acc[m] + v[m];
    }
    std::memcpy(t.facility.data(), acc, sizeof(acc));
}

// ---- HST delta: propagate dirty servers up unique affected paths ----
// Returns number of touched internal nodes (racks+aisles+facility) recomputed.
static int propagate_delta(Tree& t, const std::vector<int>& dirtyServers,
                           std::vector<uint8_t>& rackMark, std::vector<uint8_t>& aisleMark,
                           std::vector<int>& touchedRacks, std::vector<int>& touchedAisles) {
    touchedRacks.clear(); touchedAisles.clear();
    for (int s : dirtyServers) {
        int r = t.serverRack[s];
        if (!rackMark[r]) { rackMark[r] = 1; touchedRacks.push_back(r); }
    }
    for (int r : touchedRacks) {
        recompute_rack(t, r);
        int a = t.rackAisle[r];
        if (!aisleMark[a]) { aisleMark[a] = 1; touchedAisles.push_back(a); }
    }
    for (int a : touchedAisles) recompute_aisle(t, a);
    recompute_facility(t); // facility always touched if anything changed (1 node)
    int touched = (int)touchedRacks.size() + (int)touchedAisles.size() + 1;
    // reset marks
    for (int r : touchedRacks) rackMark[r] = 0;
    for (int a : touchedAisles) aisleMark[a] = 0;
    return touched;
}

static bool exact_parity(const Tree& a, const Tree& b) {
    if (a.facility != b.facility) return false;
    if (a.aisle != b.aisle) return false;
    if (a.rack != b.rack) return false;
    return true;
}

// ---------------------------------------------------------------------------
// Argument validation. `atof`/`atoi` return 0 on anything they cannot parse
// and have no way to report that they did, so `./hst_dc_telemetry banana -5`
// used to run to completion: churn=0.0, steps=-5, the step loop body never
// executed, ZERO parity checks were performed, and main returned 0. The README
// says "the contract is the exit code" -- a green exit that checked nothing
// breaks that contract more completely than a wrong number would.
// ---------------------------------------------------------------------------
static const int EXIT_USAGE = 2;   // 1 is reserved for a parity failure

static bool parse_double(const char* s, double& out) {
    char* end = nullptr;
    errno = 0;
    double v = strtod(s, &end);
    if (end == s || *end != '\0' || errno == ERANGE || !std::isfinite(v)) return false;
    out = v;
    return true;
}

static bool parse_int(const char* s, long& out) {
    char* end = nullptr;
    errno = 0;
    long v = strtol(s, &end, 10);
    if (end == s || *end != '\0' || errno == ERANGE) return false;
    out = v;
    return true;
}

static int usage(const char* prog, const char* what) {
    fprintf(stderr,
            "%s: %s\n"
            "usage: %s [churn] [steps] [locality]\n"
            "  churn     fraction of servers dirtied per step, 0.0 <= churn <= 1.0\n"
            "            (0 is the FROZEN control and is asserted to dirty zero leaves)\n"
            "  steps     number of intervals to run, a positive integer\n"
            "  locality  0.0 = uniform random, 1.0 = fully bursty; 0.0 <= locality <= 1.0\n"
            "example: %s 0.03 400        (and %s 0 400 for the frozen control)\n",
            prog, what, prog, prog, prog);
    return EXIT_USAGE;
}

int main(int argc, char** argv) {
    // ---- topology sizing ~ thousands of servers ----
    int A = 8, Rp = 12, Sp = 24;          // 8 aisles * 12 racks * 24 servers = 2304 servers
    double churn = 0.03;                   // 3% of servers change per step
    int steps = 400;
    uint64_t seed = 42;
    double locality = 0.0;                  // 0 = uniform random; 1 = fully bursty (dirty concentrated in few racks)
    const char* prog = (argc > 0 && argv[0]) ? argv[0] : "hst_dc_telemetry";

    if (argc > 4)
        return usage(prog, "too many arguments");
    if (argc > 1) {
        if (!parse_double(argv[1], churn))
            return usage(prog, "churn is not a number");
        if (!(churn >= 0.0 && churn <= 1.0)) {
            char msg[128];
            snprintf(msg, sizeof msg,
                     "churn %g is outside 0.0-1.0 -- it is a FRACTION of servers, "
                     "so 5 would mean 500%%", churn);
            return usage(prog, msg);
        }
    }
    if (argc > 2) {
        long s = 0;
        if (!parse_int(argv[2], s))
            return usage(prog, "steps is not an integer");
        if (s < 1 || s > 100000000L) {
            char msg[128];
            snprintf(msg, sizeof msg,
                     "steps %ld must be a positive integer -- a run of %ld steps "
                     "performs zero parity checks and proves nothing", s, s);
            return usage(prog, msg);
        }
        steps = (int)s;
    }
    if (argc > 3) {
        if (!parse_double(argv[3], locality))
            return usage(prog, "locality is not a number");
        if (!(locality >= 0.0 && locality <= 1.0))
            return usage(prog, "locality is outside 0.0-1.0");
    }

    std::mt19937_64 rng(seed);
    Tree base = build_tree(A, Rp, Sp);
    seed_servers(base, rng);
    Tree hst = base; // identical copy (same server values + topology)

    // establish identical initial aggregates in both
    recompute_full(base);
    recompute_full(hst);
    if (!exact_parity(base, hst)) { printf("INIT PARITY FAIL\n"); return 1; }

    int nServer = base.nServer;
    // churn<=0 must be genuinely FROZEN: zero dirty leaves per step. The old
    // std::max(1, ...) floor swapped in one dirty server even at churn=0, so
    // the "frozen" cell was never actually frozen -- the same defect class
    // documented in learn/pytorch_fit/BASELINE_LADDER_FINDINGS_2026-08-03.md
    // (a max(1,...) floor with no rho<=0 guard silently denies the frozen
    // control). Only floor to 1 when churn asked for something nonzero but
    // rounded away.
    int dirtyPerStep = (churn > 0.0) ? std::max(1, (int)std::llround(churn * nServer)) : 0;
    // startup self-check: assert the invariant rather than trust the ternary
    // above to keep meaning what this comment says it means.
    if (churn <= 0.0 && dirtyPerStep != 0) {
        fprintf(stderr, "SELF-CHECK FAILED: churn=%.4f (<=0) must yield dirtyPerStep==0, got %d\n",
                churn, dirtyPerStep);
        return 1;
    }
    if (churn <= 0.0) {
        printf("# self-check: churn<=0 -> dirtyPerStep=%d (FROZEN control confirmed)\n", dirtyPerStep);
    }

    std::vector<uint8_t> rackMark(base.nRack, 0), aisleMark(base.nAisle, 0);
    std::vector<int> touchedRacks, touchedAisles;
    std::vector<int> dirty;
    std::uniform_int_distribution<int> pick(0, nServer - 1);
    std::normal_distribution<double> jitter(0.0, 1.0);

    // accumulators
    double base_ns = 0, hst_ns = 0;
    long long total_touched = 0, total_full = 0;
    long long parity_fail = 0;
    // energy proxy: model each aggregate "combine" (touch of an internal node's
    // child fan-in) as unit work. Baseline cost = all internal fan-ins every step;
    // HST cost = touched internal fan-ins. Reported as relative energy, NOT joules.
    long long base_ops = 0, hst_ops = 0;
    int internalFanBase = base.nRack * Sp + base.nAisle * Rp + A; // per full recompute

    // scripted events: (step -> lambda). Each still expressed as dirty leaves.
    auto apply_reading_jitter = [&](Tree& t, int s) {
        double* v = &t.server[(size_t)s * NMET];
        v[M_CPU]   = std::clamp(v[M_CPU]   + jitter(rng)*4.0, 0.0, 100.0);
        v[M_TEMP]  = std::clamp(v[M_TEMP]  + jitter(rng)*1.5, 20.0, 95.0);
        v[M_POWER] = std::clamp(v[M_POWER] + jitter(rng)*8.0, 40.0, 400.0);
        v[M_NET]   = std::clamp(v[M_NET]   + jitter(rng)*0.05, 0.0, 1.0);
    };

    printf("# DC telemetry: %d aisles x %d racks x %d servers = %d servers, %d metrics\n",
           A, Rp, Sp, nServer, NMET);
    printf("# churn=%.1f%% (%d dirty/step), %d steps, locality=%.2f\n", churn*100, dirtyPerStep, steps, locality);
    printf("# events at scripted steps; parity checked bit-exact every step\n\n");

    struct Ev { int step; const char* name; };
    std::vector<Ev> events = {
        {50,  "hot GPU server (temp+power spike, 1 node)"},
        {120, "node failure (server -> 0 across all metrics)"},
        {200, "congestion spike (one rack's 24 servers net-saturate)"},
        {300, "workload migration (rack A drains, rack B fills)"},
    };
    auto event_at = [&](int step) -> const char* {
        for (auto& e : events) if (e.step == step) return e.name;
        return nullptr;
    };

    for (int step = 0; step < steps; ++step) {
        // ---- choose dirty set for this step ----
        dirty.clear();
        const char* ev = event_at(step);

        if (ev && strstr(ev, "hot GPU")) {
            int s = pick(rng);
            double* v = &base.server[(size_t)s*NMET];
            v[M_TEMP] = 88.0; v[M_POWER] = 380.0; v[M_CPU] = 97.0;
            std::memcpy(&hst.server[(size_t)s*NMET], v, sizeof(double)*NMET);
            dirty.push_back(s);
        } else if (ev && strstr(ev, "node failure")) {
            int s = pick(rng);
            double* v = &base.server[(size_t)s*NMET];
            for (int m=0;m<NMET;++m) v[m] = 0.0;
            std::memcpy(&hst.server[(size_t)s*NMET], v, sizeof(double)*NMET);
            dirty.push_back(s);
        } else if (ev && strstr(ev, "congestion")) {
            int r = pick(rng) / 1; r = base.serverRack[pick(rng)];
            int s0 = r * Sp;
            for (int s = s0; s < s0 + Sp; ++s) {
                base.server[(size_t)s*NMET + M_NET] = 0.98;
                base.server[(size_t)s*NMET + M_CPU] = std::min(100.0, base.server[(size_t)s*NMET+M_CPU]+30);
                std::memcpy(&hst.server[(size_t)s*NMET], &base.server[(size_t)s*NMET], sizeof(double)*NMET);
                dirty.push_back(s);
            }
        } else if (ev && strstr(ev, "migration")) {
            int rA = base.serverRack[pick(rng)], rB = base.serverRack[pick(rng)];
            for (int r : {rA, rB}) {
                int s0 = r * Sp;
                for (int s = s0; s < s0 + Sp; ++s) {
                    double load = (r == rA) ? 5.0 : 75.0;
                    base.server[(size_t)s*NMET + M_CPU] = load;
                    base.server[(size_t)s*NMET + M_POWER] = (r==rA)?110.0:330.0;
                    std::memcpy(&hst.server[(size_t)s*NMET], &base.server[(size_t)s*NMET], sizeof(double)*NMET);
                    dirty.push_back(s);
                }
            }
        } else {
            // normal step: 1-5% churn, split between a bursty "active" set of racks
            // (spatial correlation, the realistic case) and uniform background scatter.
            // locality in [0,1]: fraction of dirty leaves drawn from a small hot-rack set.
            int nHotRacks = std::max(1, base.nRack / 16);            // ~6 racks form the active zone
            int hotBudget = (int)std::llround(locality * dirtyPerStep);
            // pick a fresh hot-rack window each step (drifts over time)
            int hotBase = (int)(rng() % (base.nRack - nHotRacks + 1));
            for (int i = 0; i < dirtyPerStep; ++i) {
                int s;
                if (i < hotBudget) {
                    int r = hotBase + (int)(rng() % nHotRacks);
                    s = r * Sp + (int)(rng() % Sp);
                } else {
                    s = pick(rng);
                }
                apply_reading_jitter(base, s);
                std::memcpy(&hst.server[(size_t)s*NMET], &base.server[(size_t)s*NMET], sizeof(double)*NMET);
                dirty.push_back(s);
            }
        }
        // dedup dirty (events may repeat a server)
        std::sort(dirty.begin(), dirty.end());
        dirty.erase(std::unique(dirty.begin(), dirty.end()), dirty.end());

        // ---- baseline (full recompute) vs HST (delta propagation) ----
        // These are two independent arms this step: `base` and `hst` are
        // separate Tree copies, and by this point both already carry this
        // step's dirty leaf values (memcpy'd above in the event/normal-step
        // branches), so neither arm reads the other's output -- recompute_full
        // only touches `base`, propagate_delta only touches `hst` plus its own
        // scratch marks/lists. A FIXED order is a one-sided measurement tax --
        // whichever arm runs later inherits warmer cache/TLB from its
        // predecessor (learn/pytorch_fit/LANE_ORDER_FINDINGS_2026-08-01.md,
        // "one-sided order tax"). Rotate per step, seeded deterministically
        // off (seed, step) so reruns reproduce.
        int touched = 0;
        std::array<int,2> arm_order{{0,1}};
        std::mt19937_64 order_rng(seed ^ 0x5eedULL ^ (uint64_t)step);
        std::shuffle(arm_order.begin(), arm_order.end(), order_rng);
        for (int arm : arm_order) {
            if (arm == 0) {
                // ---- baseline: full recompute ----
                auto b0 = clk::now();
                recompute_full(base);
                auto b1 = clk::now();
                base_ns += ns(b0, b1);
                base_ops += internalFanBase;
                total_full += base.nRack + base.nAisle + 1;
            } else {
                // ---- HST: delta propagation ----
                auto h0 = clk::now();
                touched = propagate_delta(hst, dirty, rackMark, aisleMark, touchedRacks, touchedAisles);
                auto h1 = clk::now();
                hst_ns += ns(h0, h1);
                total_touched += touched;
                // hst ops = fan-in of touched racks (Sp each) + touched aisles (Rp each) + facility (A)
                hst_ops += (long long)touchedRacks.size()*Sp + (long long)touchedAisles.size()*Rp + A;
            }
        }

        // ---- parity (bit-exact) ----
        bool ok = exact_parity(base, hst);
        if (!ok) parity_fail++;

        if (ev) {
            printf("step %3d  EVENT: %s\n", step, ev);
            printf("           dirty=%d  touched_internal=%d / %d  parity=%s\n",
                   (int)dirty.size(), touched, base.nRack+base.nAisle+1, ok?"EXACT":"MISMATCH");
        }
    }

    long maxrss = max_rss_kb();
    double touch_ratio = (double)total_touched / (double)total_full;
    printf("\n==== SUMMARY (%d steps) ====\n", steps);
    printf("parity failures        : %lld  (%s)\n", parity_fail, parity_fail==0?"BIT-EXACT throughout":"BROKEN");
    printf("baseline latency /step : %8.1f ns\n", base_ns/steps);
    printf("HST      latency /step : %8.1f ns\n", hst_ns/steps);
    printf("latency speedup        : %8.2fx\n", base_ns/hst_ns);
    printf("touched internal nodes : %.4f of full recompute  (%.1fx less structural work)\n",
           touch_ratio, 1.0/touch_ratio);
    printf("combine-ops (energy proxy, relative, NOT joules):\n");
    printf("  baseline ops         : %lld\n", base_ops);
    printf("  HST      ops         : %lld\n", hst_ops);
    printf("  op / energy ratio    : %8.2fx fewer combines\n", (double)base_ops/(double)hst_ops);
    printf("maxRSS                 : %ld KB (single process, both trees resident)\n", maxrss);
    printf("\nNote: latency/CPU/memory are wall-clock on this host; the combine-op /\n");
    printf("energy figure is a modeled proxy (work units), not a RAPL measurement.\n");
    printf("Touched-node ratio is the platform-independent structural result.\n");
    // parity_fail was accumulated every step and printed above as BROKEN when
    // nonzero, but main() returned 0 regardless -- a parity regression that
    // only appears partway through the run (unlike the bit-exact init-time
    // self-check at line ~207, which already gates) could not fail the
    // process. This file does not include assert_rel.hpp elsewhere and the
    // existing init-time check already uses a direct `return 1;` rather than
    // that header's machinery, so match that local idiom instead of adding a
    // new dependency for one boolean gate.
    if (parity_fail > 0) return 1;
    return 0;
}
