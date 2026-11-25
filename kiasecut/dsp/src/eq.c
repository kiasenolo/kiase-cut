/* 8 段參數 EQ, 多模式濾波器, 頻譜分析器. */
#include "kcdsp.h"


/* -- the equaliser ------------------------------------------------------------------------------ */
#define BANDS 8
#define STAGES 4                    /* a cut's steepest slope: 48 dB / octave */
#define PER_BAND 6                  /* o on, t type, s slope, f, g, q */

/* the same order as the KC_BQ_* kinds: bell, low shelf, high shelf, low cut, high cut, notch */
typedef struct { kc_bqstate bq[BANDS][STAGES]; kc_coef c[BANDS][STAGES]; double out; } eq_state;

#define BAND(n) "o" #n, "t" #n, "s" #n, "f" #n, "g" #n, "q" #n
static const char *const eq_params[] = {BAND(1), BAND(2), BAND(3), BAND(4), BAND(5), BAND(6), BAND(7), BAND(8), "out"};
#define DEF(on, t, f, q) on, t, 1, f, 0, q
static const double eq_defaults[] = {DEF(1, 1, 80, 0.7), DEF(1, 0, 250, 1), DEF(1, 0, 1000, 1), DEF(1, 0, 4000, 1),
                                     DEF(1, 2, 10000, 0.7), DEF(0, 0, 500, 1), DEF(0, 0, 2000, 1), DEF(0, 0, 8000, 1), 0};

/* the stages of band b as the parameters ask; the unused ones do nothing */
static void eq_band(const kc_fx *f, int b, kc_coef *out) {
    const double *p = f->p + b * PER_BAND;
    int on = p[0] > 0.5, type = (int)(p[1] + 0.5), n = 0;
    if (on) {
        if (type < KC_BQ_BELL || type > KC_BQ_NOTCH)
            type = KC_BQ_BELL;
        int cut = type == KC_BQ_LOWCUT || type == KC_BQ_HIGHCUT;
        n = cut ? 1 + (int)kc_clamp(p[2] + 0.5, 0, STAGES - 1) : 1;
        for (int k = 0; k < n; k++)
            out[k] = kc_biquad(type, f->sr, p[3], cut ? kc_butter_q(k, n) : p[5], p[4]);
    }
    for (int k = n; k < STAGES; k++)
        out[k] = kc_biquad(KC_BQ_OFF, f->sr, 1000, 1, 0);
}

static int identity(const kc_coef *c) { return c->b0 == 1.0 && c->b1 == 0.0 && c->b2 == 0.0 && c->a1 == 0.0 && c->a2 == 0.0; }
static int silent(const kc_bqstate *s) { return !s->z1[0] && !s->z1[1] && !s->z2[0] && !s->z2[1]; }

static void eq_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    eq_state *s = f->state;
    (void)side; (void)pos;
    if (out != in)
        memcpy(out, in, sizeof(float) * 2 * n);
    for (int b = 0; b < BANDS; b++) {
        kc_coef to[STAGES];
        eq_band(f, b, to);
        for (int k = 0; k < STAGES; k++) {
            if (f->fresh)
                s->c[b][k] = to[k];
            if (!(identity(&to[k]) && identity(&s->c[b][k]) && silent(&s->bq[b][k])))
                kc_biquad_run(&s->bq[b][k], &s->c[b][k], &to[k], out, out, n);
            s->c[b][k] = to[k];
        }
    }
    double g = kc_db_lin(f->p[BANDS * PER_BAND]);
    if (f->fresh)
        s->out = g;
    double step = (g - s->out) / (n > 0 ? n : 1), now = s->out;
    for (int i = 0; i < n; i++) {
        now += step;
        out[2 * i] = (float)(out[2 * i] * now);
        out[2 * i + 1] = (float)(out[2 * i + 1] * now);
    }
    s->out = g;
}

static double eq_response(const kc_fx *f, int part, double hz) {
    double gain = 1.0;
    for (int b = 0; b < BANDS; b++) {
        if (part >= 0 && b != part)
            continue;
        kc_coef c[STAGES];
        eq_band(f, b, c);
        for (int k = 0; k < STAGES; k++)
            if (!identity(&c[k]))
                gain *= kc_biquad_gain(&c[k], f->sr, hz);
    }
    return kc_lin_db(gain) + (part < 0 ? f->p[BANDS * PER_BAND] : 0.0);
}

static void eq_reset(kc_fx *f) { memset(f->state, 0, sizeof(eq_state)); }

/* how long its sharpest low band rings */
static double eq_tail(const kc_fx *f) {
    double longest = 0.01;
    for (int b = 0; b < BANDS; b++) {
        const double *p = f->p + b * PER_BAND;
        if (p[0] > 0.5) {
            double t = 3.3 * kc_clamp(p[5], 0.7, 18.0) / kc_clamp(p[3], 20.0, 20000.0);
            if (t > longest)
                longest = t;
        }
    }
    return longest > 2.0 ? 2.0 : longest;
}

const kc_type kc_eq_type = {"eq", BANDS * PER_BAND + 1, eq_params, eq_defaults, sizeof(eq_state), 0, eq_reset, eq_process,
                            0, eq_tail, 0, eq_response};

/* -- the multimode filter ----------------------------------------------------------------------- */
/* mode: low pass 12 / 24 / 36, high pass 12 / 24 / 36, band pass 6 / 12 / 18, band stop 6 / 12 / 18, all pass */
typedef struct { kc_bqstate bq[3]; kc_coef c[3]; } multi_state;
static const char *const multi_params[] = {"mode", "freq", "res"};
static const double multi_defaults[] = {1, 2000, 0.7071};

static void multi_stages(const kc_fx *f, kc_coef *out) {
    int mode = (int)kc_clamp(f->p[0] + 0.5, 0, 12), group = mode / 3, n = mode == 12 ? 1 : mode % 3 + 1;
    static const int kinds[] = {KC_BQ_HIGHCUT, KC_BQ_LOWCUT, KC_BQ_BANDPASS, KC_BQ_NOTCH, KC_BQ_ALLPASS};
    double res = kc_clamp(f->p[2], 0.5, 32.0);
    for (int k = 0; k < 3; k++) {
        if (k >= n) {
            out[k] = kc_biquad(KC_BQ_OFF, f->sr, 1000, 1, 0);
            continue;
        }
        double q = res;
        if (group < 2)              /* a flat pass band at the lowest 共振: the resonance is the sharpest stage's */
            q = k == n - 1 ? kc_butter_q(k, n) * res / 0.7071 : kc_butter_q(k, n);
        out[k] = kc_biquad(kinds[group], f->sr, f->p[1], q, 0.0);
    }
}

static void multi_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    multi_state *s = f->state;
    kc_coef to[3];
    (void)side; (void)pos;
    multi_stages(f, to);
    if (out != in)
        memcpy(out, in, sizeof(float) * 2 * n);
    for (int k = 0; k < 3; k++) {
        if (f->fresh)
            s->c[k] = to[k];
        if (!(identity(&to[k]) && identity(&s->c[k]) && silent(&s->bq[k])))
            kc_biquad_run(&s->bq[k], &s->c[k], &to[k], out, out, n);
        s->c[k] = to[k];
    }
}

static double multi_response(const kc_fx *f, int part, double hz) {
    kc_coef c[3];
    double gain = 1.0;
    (void)part;
    multi_stages(f, c);
    for (int k = 0; k < 3; k++)
        gain *= kc_biquad_gain(&c[k], f->sr, hz);
    return kc_lin_db(gain);
}

static void multi_reset(kc_fx *f) { memset(f->state, 0, sizeof(multi_state)); }
static double multi_tail(const kc_fx *f) {
    return kc_clamp(3.3 * f->p[2] / kc_clamp(f->p[1], 10.0, 20000.0), 0.01, 3.0);
}

const kc_type kc_filter_type = {"filter", 3, multi_params, multi_defaults, sizeof(multi_state), 0, multi_reset,
                                multi_process, 0, multi_tail, 0, multi_response};

/* -- the analyser: the sound goes through as it is (what is drawn is taken by the host) ---------- */
static const double no_defaults[] = {0};
static const char *const no_params[] = {""};

static void analyzer_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    float peak[2] = {0, 0};
    (void)side; (void)pos;
    for (int i = 0; i < n; i++)
        for (int c = 0; c < 2; c++) {
            float v = fabsf(in[2 * i + c]);
            if (v > peak[c])
                peak[c] = v;
        }
    f->meters[0] = peak[0];
    f->meters[1] = peak[1];
    if (out != in)
        memcpy(out, in, sizeof(float) * 2 * n);
}

const kc_type kc_analyzer_type = {"analyzer", 0, no_params, no_defaults, 0, 0, 0, analyzer_process, 0, 0, 0, 0};
