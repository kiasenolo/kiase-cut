/* 增益, 高通, 低通. */
#include "kcdsp.h"

/* -- gain -------------------------------------------------------------------------------------- */
typedef struct { double g; } gain_state;
static const char *const gain_params[] = {"gain"};
static const double gain_defaults[] = {0.0};

static void gain_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    gain_state *s = f->state;
    double to = f->p[0] <= -60.0 ? 0.0 : kc_db_lin(f->p[0]);      /* the bottom of the scale is silence */
    if (f->fresh)
        s->g = to;
    double g = s->g, d = n > 0 ? (to - g) / n : 0.0;
    (void)side; (void)pos;
    for (int i = 0; i < n; i++) {
        g += d;
        out[2 * i] = (float)(in[2 * i] * g);
        out[2 * i + 1] = (float)(in[2 * i + 1] * g);
    }
    s->g = to;
}

static void gain_reset(kc_fx *f) { ((gain_state *)f->state)->g = 0.0; }

const kc_type kc_gain_type = {"gain", 1, gain_params, gain_defaults, sizeof(gain_state), 0, gain_reset, gain_process, 0, 0, 0};

/* -- high pass / low pass (12 dB / octave) ------------------------------------------------------ */
typedef struct { kc_bqstate bq; kc_coef c; } filt_state;
static const char *const filt_params[] = {"f", "q"};
static const double highpass_defaults[] = {80.0, 0.7071};
static const double lowpass_defaults[] = {12000.0, 0.7071};

static void filt_run(kc_fx *f, int kind, const float *in, float *out, int n) {
    filt_state *s = f->state;
    kc_coef to = kc_biquad(kind, f->sr, f->p[0], f->p[1], 0.0);
    if (f->fresh)
        s->c = to;
    kc_biquad_run(&s->bq, &s->c, &to, in, out, n);
    s->c = to;
}

static void highpass_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    (void)side; (void)pos;
    filt_run(f, KC_BQ_LOWCUT, in, out, n);
}

static void lowpass_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    (void)side; (void)pos;
    filt_run(f, KC_BQ_HIGHCUT, in, out, n);
}

static void filt_reset(kc_fx *f) { memset(f->state, 0, sizeof(filt_state)); }

/* ringing: the time a resonance takes to fall 90 dB */
static double filt_tail(const kc_fx *f) {
    return kc_clamp(3.3 * f->p[1] / kc_clamp(f->p[0], 10.0, 20000.0), 0.01, 2.0);
}

const kc_type kc_highpass_type = {"highpass", 2, filt_params, highpass_defaults, sizeof(filt_state), 0, filt_reset,
                                  highpass_process, 0, filt_tail, 0};
const kc_type kc_lowpass_type = {"lowpass", 2, filt_params, lowpass_defaults, sizeof(filt_state), 0, filt_reset,
                                 lowpass_process, 0, filt_tail, 0};
