/* Reference sparse mat-vec and delta-apply, plain CSC. Public domain (CC0 1.0).
 *
 * An independent C implementation of the same spec as reference_spmv.py. It
 * exists so the golden vectors are not checked only by the program that wrote
 * them: two languages, two compilers, one stated summation order, and the
 * shipped `y` must come out bit-identical from both.
 *
 * THE SUMMATION ORDER IS PART OF THE SPEC. Both kernels accumulate in CSC
 * order -- columns ascending, rows within a column ascending. Change the order
 * and the f64 GRADE-A cases will differ in the last bits. That is expected.
 * The integer-exact cases will NOT differ, under any order, which is the point
 * of them.
 *
 * Build:  cc -O2 -std=c99 -o reference_spmv reference_spmv.c -lm
 * Run:    ./reference_spmv <matrix.mtx> <case_dir>
 *
 * No dependencies. Reads the .mtx and the case's dx.bin, regenerates y0 and
 * every step's y, and compares against the shipped y0.f64.bin / y.f64.bin.
 * Exit code 0 iff every comparison passes at the case's stated grade.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>

/* ---- THE KERNELS. Everything else in this file is plumbing. ------------- */

static void spmv(const int *indptr, const int *indices, const double *values,
                 int n_cols, const double *x, double *y, int n_rows, int B) {
    for (long t = 0; t < (long)n_rows * B; ++t) y[t] = 0.0;
    for (int j = 0; j < n_cols; ++j)                    /* columns ascending  */
        for (int k = indptr[j]; k < indptr[j + 1]; ++k) /* rows ascending     */
            for (int b = 0; b < B; ++b)
                y[(long)indices[k] * B + b] += values[k] * x[(long)j * B + b];
}

static void spmv_delta(const int *indptr, const int *indices, const double *values,
                       const uint32_t *dirty, int nd, const double *dvals,
                       double *y, int B) {
    for (int t = 0; t < nd; ++t) {                      /* dirty cols ascending */
        int j = (int)dirty[t];
        for (int k = indptr[j]; k < indptr[j + 1]; ++k) /* rows ascending       */
            for (int b = 0; b < B; ++b)
                y[(long)indices[k] * B + b] += values[k] * dvals[(long)t * B + b];
    }
}

/* ---- SplitMix64, specified so C and Python agree bit for bit ------------- */

static uint64_t sm_state;
static uint64_t sm_next(void) {
    uint64_t z = (sm_state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}
static double sm_unit(void) { return (double)(sm_next() >> 11) * 0x1.0p-53; }

/* ---- Matrix Market -> CSC under a named preprocessing rule --------------- */

typedef struct { int i, j; double v; } Ent;
static int cmp_ent(const void *a, const void *b) {
    const Ent *x = a, *y = b;
    if (x->j != y->j) return x->j < y->j ? -1 : 1;
    return x->i < y->i ? -1 : (x->i > y->i);
}

/* rule: 0 = pattern_int_v1 (values discarded, A[i,j] = 1 + ((i+3j) mod 5))
 *       1 = values_f64_v1  (stored value; a `pattern` file gives 1.0)
 * Symmetric files store one triangle: off-diagonal entries are mirrored.
 * (The Python reference additionally asserts there are no duplicate
 * coordinates; that is a property of the input file, checked once there.) */
static int load_csc(const char *path, int rule, int **pptr, int **pidx,
                    double **pval, int *pN, int *pM) {
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); return -1; }
    char line[4096], obj[64], fmt[64], field[64], sym[64];
    if (!fgets(line, sizeof line, f)) return -1;
    sscanf(line, "%%%%MatrixMarket %63s %63s %63s %63s", obj, fmt, field, sym);
    int is_pattern = !strcmp(field, "pattern"), is_sym = !strcmp(sym, "symmetric");
    int N = 0, M = 0; long nnz = 0;
    while (fgets(line, sizeof line, f))
        if (line[0] != '%') { sscanf(line, "%d %d %ld", &N, &M, &nnz); break; }
    Ent *e = malloc(sizeof(Ent) * (size_t)nnz * 2);
    long n = 0;
    for (long t = 0; t < nnz; ++t) {
        if (!fgets(line, sizeof line, f)) break;
        int i, j; double v = 1.0;
        if (is_pattern) sscanf(line, "%d %d", &i, &j);
        else            sscanf(line, "%d %d %lf", &i, &j, &v);
        --i; --j;
        e[n].i = i; e[n].j = j; e[n].v = v; ++n;
        if (is_sym && i != j) { e[n].i = j; e[n].j = i; e[n].v = v; ++n; }
    }
    fclose(f);
    if (rule == 0) for (long t = 0; t < n; ++t) e[t].v = 1.0 + (double)((e[t].i + 3 * e[t].j) % 5);
    qsort(e, (size_t)n, sizeof(Ent), cmp_ent);          /* col-major, rows ascending */
    int *ptr = calloc((size_t)M + 1, sizeof(int));
    int *idx = malloc(sizeof(int) * (size_t)n);
    double *val = malloc(sizeof(double) * (size_t)n);
    for (long t = 0; t < n; ++t) { idx[t] = e[t].i; val[t] = e[t].v; ptr[e[t].j + 1]++; }
    for (int j = 0; j < M; ++j) ptr[j + 1] += ptr[j];
    free(e);
    *pptr = ptr; *pidx = idx; *pval = val; *pN = N; *pM = M;
    return 0;
}

static double *gen_x0(const char *rule, uint64_t seed, int M, int B) {
    double *x = malloc(sizeof(double) * (size_t)M * B);
    if (!strcmp(rule, "x0_int_v1")) {
        for (int j = 0; j < M; ++j) for (int b = 0; b < B; ++b)
            x[(long)j * B + b] = (double)(1 + ((j + 7 * b) % 9));
    } else {
        sm_state = seed;
        for (long t = 0; t < (long)M * B; ++t) x[t] = 2.0 * sm_unit() - 1.0;
    }
    return x;
}

/* ---- case files --------------------------------------------------------- */

static void *slurp(const char *path, long *len) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END); *len = ftell(f); fseek(f, 0, SEEK_SET);
    void *p = malloc((size_t)*len);
    if (fread(p, 1, (size_t)*len, f) != (size_t)*len) { perror(path); exit(2); }
    fclose(f);
    return p;
}

/* Reads one string field out of the flat case manifest. Deliberately dumb:
 * the manifest is machine-written with one `"key": value` per line. */
static int manifest_str(const char *blob, const char *key, char *out, size_t n) {
    char pat[128]; snprintf(pat, sizeof pat, "\"%s\":", key);
    const char *p = strstr(blob, pat);
    if (!p) return -1;
    p = strchr(p + strlen(pat), '"');
    if (!p) return -1;
    const char *q = strchr(++p, '"');
    if (!q || (size_t)(q - p) >= n) return -1;
    memcpy(out, p, (size_t)(q - p)); out[q - p] = 0;
    return 0;
}
static long manifest_num(const char *blob, const char *key, long dflt) {
    char pat[128]; snprintf(pat, sizeof pat, "\"%s\":", key);
    const char *p = strstr(blob, pat);
    return p ? strtol(p + strlen(pat), NULL, 10) : dflt;
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s <matrix.mtx> <case_dir>\n", argv[0]); return 2; }
    const char *mtx = argv[1], *dir = argv[2];
    char path[4096]; long mlen;

    snprintf(path, sizeof path, "%s/manifest.json", dir);
    char *man = slurp(path, &mlen);
    char rule_s[64] = "", x0_s[64] = "", grade[16] = "";
    manifest_str(man, "value_rule", rule_s, sizeof rule_s);
    manifest_str(man, "x0_generator", x0_s, sizeof x0_s);
    manifest_str(man, "grade", grade, sizeof grade);
    long seed = manifest_num(man, "x0_seed", 0);
    int B = (int)manifest_num(man, "batch", 1);
    double bound = 0.0;
    { const char *p = strstr(man, "\"rel_l2_bound\":");
      if (p) bound = strtod(p + strlen("\"rel_l2_bound\":"), NULL); }

    int *ptr, *idx, N, M; double *val;
    if (load_csc(mtx, strcmp(rule_s, "pattern_int_v1") ? 1 : 0, &ptr, &idx, &val, &N, &M)) return 2;

    double *x0 = gen_x0(x0_s, (uint64_t)seed, M, B);
    double *y = malloc(sizeof(double) * (size_t)N * B);
    spmv(ptr, idx, val, M, x0, y, N, B);

    long l0; double *y0_ref = slurp((snprintf(path, sizeof path, "%s/y0.f64.bin", dir), path), &l0);
    long ly; double *y_ref  = slurp((snprintf(path, sizeof path, "%s/y.f64.bin",  dir), path), &ly);
    long dlen; unsigned char *dx = slurp((snprintf(path, sizeof path, "%s/dx.bin", dir), path), &dlen);
    if (memcmp(dx, "GVDX0001", 8)) { fprintf(stderr, "bad dx magic\n"); return 2; }
    uint32_t hdr[6]; memcpy(hdr, dx + 8, sizeof hdr);
    uint32_t steps = hdr[1];

    long n0 = (long)N * B;
    long bad0 = 0; double num0 = 0.0, den0 = 0.0;
    for (long t = 0; t < n0; ++t) {
        if (memcmp(&y[t], &y0_ref[t], 8)) bad0++;
        double d = y[t] - y0_ref[t];
        num0 += d * d; den0 += y0_ref[t] * y0_ref[t];
    }
    double rel0 = den0 > 0 ? sqrt(num0 / den0) : sqrt(num0);
    printf("  y0 bit-differing   : %ld / %ld  (rel_l2 %.3e)\n", bad0, n0, rel0);

    /* y0 is judged at the case's own grade, exactly like the steps are. */
    int fail = !strcmp(grade, "GRADE-A") ? (bad0 != 0) : !(rel0 <= bound);
    long off = 32;
    double worst = 0.0; long nbitdiff = 0;
    for (uint32_t s = 0; s < steps; ++s) {
        uint32_t k; memcpy(&k, dx + off, 4); off += 4;
        uint32_t *dirty = (uint32_t *)(dx + off); off += 4 * (long)k;
        double *dvals = (double *)(dx + off); off += 8 * (long)k * B;
        spmv_delta(ptr, idx, val, dirty, (int)k, dvals, y, B);
        const double *ref = y_ref + (long)s * n0;
        double num = 0.0, den = 0.0;
        for (long t = 0; t < n0; ++t) {
            if (memcmp(&y[t], &ref[t], 8)) nbitdiff++;
            double d = y[t] - ref[t];
            num += d * d; den += ref[t] * ref[t];
        }
        double rel = den > 0 ? sqrt(num / den) : sqrt(num);
        if (rel > worst) worst = rel;
    }
    printf("  steps replayed     : %u\n", steps);
    printf("  bit-differing f64s : %ld / %ld\n", nbitdiff, (long)steps * n0);
    printf("  worst rel_l2       : %.3e   (bound %.3e, grade %s)\n", worst, bound, grade);
    if (!strcmp(grade, "GRADE-A")) fail |= (nbitdiff != 0);
    else                           fail |= !(worst <= bound);
    printf("  RESULT             : %s\n", fail ? "FAIL" : "PASS");
    (void)l0; (void)ly; (void)mlen;
    return fail;
}
