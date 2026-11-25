/* KiaseCut's sound effects (聲音效果), loaded by kiasecut/dsp/__init__.py with ctypes.
 *
 * Sound is float32 stereo, interleaved (frames * 2 numbers), 1.0 = full scale. An effect is a
 * kc_type (its parameters by name, and what it does) and any number of instances (kc_fx).
 * The host hands over blocks; parameters set between two blocks are reached smoothly over the
 * next one, except on the first block after a reset, which starts at them.
 * Anything that runs on its own (an LFO, noise) takes its place from pos, the block's first
 * sample on the mixed timeline, so a render does not depend on where it began.
 */
#ifndef KCDSP_H
#define KCDSP_H

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define KC_API __declspec(dllexport)
#else
#define KC_API __attribute__((visibility("default")))
#endif

#define KC_ABI 1
#define KC_MAXP 64
#define KC_METERS 8
#define KC_MAXBLOCK 8192
#define KC_PI 3.14159265358979323846

typedef struct kc_fx kc_fx;

typedef struct {
    const char *name;
    int nparams;
    const char *const *params;      /* their names, in the order of kc_fx.p */
    const double *defaults;
    size_t state_size;
    int (*init)(kc_fx *);           /* optional: allocate buffers; 0 when out of memory */
    void (*reset)(kc_fx *);         /* forget the sound heard so far */
    /* in, side (the side-chain, or NULL) and out hold n frames; out may be in */
    void (*process)(kc_fx *, const float *in, const float *side, float *out, int n, int64_t pos);
    int (*latency)(const kc_fx *);  /* optional: samples the output is late by */
    double (*tail)(const kc_fx *);  /* optional: seconds it keeps sounding after its input stops */
    void (*destroy)(kc_fx *);       /* optional: free what init allocated */
} kc_type;

struct kc_fx {
    const kc_type *type;
    double sr;
    double p[KC_MAXP];
    int fresh;                      /* the next block is the first since a reset */
    float meters[KC_METERS];        /* what the last block showed (gain reduction, levels...) */
    void *state;
};

static inline double kc_db_lin(double db) { return pow(10.0, db / 20.0); }
static inline double kc_lin_db(double v) { return v > 1e-9 ? 20.0 * log10(v) : -180.0; }
static inline double kc_clamp(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }
/* a recursive value that has all but died out is zeroed: denormals are very slow to work with */
static inline double kc_flush(double v) { return fabs(v) < 1e-20 ? 0.0 : v; }

/* -- biquads (RBJ cookbook), transposed direct form II, stereo -------------------------------- */
typedef struct { double b0, b1, b2, a1, a2; } kc_coef;
typedef struct { double z1[2], z2[2]; } kc_bqstate;

enum { KC_BQ_BELL, KC_BQ_LOWSHELF, KC_BQ_HIGHSHELF, KC_BQ_LOWCUT, KC_BQ_HIGHCUT, KC_BQ_NOTCH,
       KC_BQ_BANDPASS, KC_BQ_ALLPASS, KC_BQ_OFF };

kc_coef kc_biquad(int kind, double sr, double freq, double q, double gain_db);
/* n frames through the filter, its coefficients going from *from to *to across them */
void kc_biquad_run(kc_bqstate *s, const kc_coef *from, const kc_coef *to, const float *in, float *out, int n);

extern const kc_type kc_gain_type, kc_highpass_type, kc_lowpass_type;

#endif
