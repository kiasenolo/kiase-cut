/* 合唱, 鑲邊, 相位器, 顫音 / 自動左右, 飽和, 低音增強, 激勵器, 磁帶, 位元壓碎.
 *
 * What moves by itself starts, after a reset, where it would be had it run from the start of
 * the mixed line (pos), and from there on counts its own way, so that a rate can change
 * without a jump. */
#include "kcdsp.h"

#define ML_LEN (1 << 13)            /* 170 ms at 48 kHz */

static inline double frac(double v) { return v - floor(v); }
static inline double wave(double phase) { return 0.5 - 0.5 * cos(2.0 * KC_PI * phase); }     /* 0 ... 1 */
static inline double tap(const float *buf, int64_t w, double back) {
    double at = (double)w - back;
    int64_t i = (int64_t)floor(at);
    double f = at - (double)i;
    return buf[i & (ML_LEN - 1)] * (1 - f) + buf[(i + 1) & (ML_LEN - 1)] * f;
}

/* a value on its way to its target across a block */
typedef struct { double v, d; } ramp;
static inline void aim(ramp *r, double to, int n, int fresh) {
    if (fresh)
        r->v = to;
    r->d = (to - r->v) / n;
}

/* -- chorus and flanger: delay lines swept by an LFO --------------------------------------------- */
typedef struct {
    float buf[2][ML_LEN];
    int64_t w;
    double phase;
    ramp depth, base, mix, fb;
} mod_state;

static void mod_reset(kc_fx *f) {
    memset(f->state, 0, sizeof(mod_state));
    ((mod_state *)f->state)->w = ML_LEN;
}

static const char *const chorus_p[] = {"rate", "depth", "delay", "mix"};
static const double chorus_d[] = {0.8, 5, 8, 50};

static void chorus_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    mod_state *s = f->state;
    double rate = kc_clamp(f->p[0], 0.01, 20), ms = f->sr / 1000.0;
    (void)side;
    if (f->fresh)
        s->phase = frac((double)pos * rate / f->sr);
    aim(&s->depth, kc_clamp(f->p[1], 0.1, 20) * ms, n, f->fresh);
    aim(&s->base, kc_clamp(f->p[2], 0.1, 20) * ms, n, f->fresh);
    aim(&s->mix, kc_clamp(f->p[3], 0, 100) / 100.0, n, f->fresh);
    for (int i = 0; i < n; i++) {
        s->depth.v += s->depth.d;
        s->base.v += s->base.d;
        s->mix.v += s->mix.d;
        for (int c = 0; c < 2; c++) {
            double x = in[2 * i + c];
            s->buf[c][s->w & (ML_LEN - 1)] = (float)x;
            /* two voices a quarter of a turn apart, the second 8 ms further back; the sides apart too */
            double a = tap(s->buf[c], s->w, 1 + s->base.v + s->depth.v * wave(s->phase + 0.25 * c));
            double b = tap(s->buf[c], s->w, 1 + s->base.v + 8 * ms + s->depth.v * wave(s->phase + 0.25 * c + 0.5));
            out[2 * i + c] = (float)(x * (1 - s->mix.v) + (a + b) * 0.5 * s->mix.v);
        }
        s->w++;
        s->phase = frac(s->phase + rate / f->sr);
    }
}

static double chorus_tail(const kc_fx *f) { return (f->p[1] + f->p[2] + 10.0) / 1000.0; }

const kc_type kc_chorus_type = {"chorus", 4, chorus_p, chorus_d, sizeof(mod_state), 0, mod_reset, chorus_process,
                                0, chorus_tail, 0, 0};

static const char *const flanger_p[] = {"rate", "depth", "fb", "mix"};
static const double flanger_d[] = {0.25, 2, 50, 50};

static void flanger_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    mod_state *s = f->state;
    double rate = kc_clamp(f->p[0], 0.01, 20), ms = f->sr / 1000.0;
    (void)side;
    if (f->fresh)
        s->phase = frac((double)pos * rate / f->sr);
    aim(&s->depth, kc_clamp(f->p[1], 0.1, 20) * ms, n, f->fresh);
    aim(&s->fb, kc_clamp(f->p[2], 0, 89) / 100.0, n, f->fresh);
    aim(&s->mix, kc_clamp(f->p[3], 0, 100) / 100.0, n, f->fresh);
    for (int i = 0; i < n; i++) {
        s->depth.v += s->depth.d;
        s->fb.v += s->fb.d;
        s->mix.v += s->mix.d;
        for (int c = 0; c < 2; c++) {
            double x = in[2 * i + c];
            double back = 0.1 * ms + s->depth.v * wave(s->phase + 0.25 * c);
            double y = tap(s->buf[c], s->w, back < 1 ? 1 : back);
            s->buf[c][s->w & (ML_LEN - 1)] = (float)kc_flush(x + y * s->fb.v);
            /* the swept copy added to the sound itself: that is the comb */
            out[2 * i + c] = (float)(x * (1 - s->mix.v) + (x + y) * 0.7071 * s->mix.v);
        }
        s->w++;
        s->phase = frac(s->phase + rate / f->sr);
    }
}

static double flanger_tail(const kc_fx *f) { return kc_clamp(0.05 + f->p[2] / 100.0 * 0.5, 0.05, 0.6); }

const kc_type kc_flanger_type = {"flanger", 4, flanger_p, flanger_d, sizeof(mod_state), 0, mod_reset,
                                 flanger_process, 0, flanger_tail, 0, 0};

/* -- phaser: six all-passes swept between two frequencies, mixed with the dry sound ---------------- */
#define PH_STAGES 6
#define PH_STEP 32
typedef struct { kc_bqstate bq[2][PH_STAGES]; kc_coef c[2]; double phase; ramp mix; int started; } phaser_state;
static const char *const phaser_p[] = {"rate", "depth", "q", "lo", "hi", "mix"};
static const double phaser_d[] = {0.25, 100, 1, 200, 5000, 50};

static void phaser_reset(kc_fx *f) { memset(f->state, 0, sizeof(phaser_state)); }

static void phaser_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    phaser_state *s = f->state;
    double rate = kc_clamp(f->p[0], 0.01, 20), depth = kc_clamp(f->p[1], 0, 100) / 100.0;
    double lo = kc_clamp(f->p[3], 50, 20000), hi = kc_clamp(f->p[4], 50, 20000);
    (void)side;
    if (f->fresh)
        s->phase = frac((double)pos * rate / f->sr);
    aim(&s->mix, kc_clamp(f->p[5], 0, 100) / 100.0, n, f->fresh);
    float wet[2 * PH_STEP];
    for (int at = 0; at < n; at += PH_STEP) {
        int m = n - at < PH_STEP ? n - at : PH_STEP;
        s->phase = frac(s->phase + rate * m / f->sr);
        memcpy(wet, in + 2 * at, sizeof(float) * 2 * m);
        for (int c = 0; c < 2; c++) {
            double sweep = 0.5 + (wave(s->phase + 0.2 * c) - 0.5) * depth;
            kc_coef to = kc_biquad(KC_BQ_ALLPASS, f->sr, lo * pow(hi / lo, sweep), f->p[2], 0);
            if (!s->started)
                s->c[c] = to;
            /* one side at a time through the stereo filter: the other side is thrown away */
            float one[2 * PH_STEP];
            memcpy(one, wet, sizeof(float) * 2 * m);
            for (int k = 0; k < PH_STAGES; k++)
                kc_biquad_run(&s->bq[c][k], &s->c[c], &to, one, one, m);
            for (int i = 0; i < m; i++)
                wet[2 * i + c] = one[2 * i + c];
            s->c[c] = to;
        }
        s->started = 1;
        for (int i = 0; i < m; i++) {
            s->mix.v += s->mix.d;
            for (int c = 0; c < 2; c++) {
                double x = in[2 * (at + i) + c];
                out[2 * (at + i) + c] = (float)(x * (1 - s->mix.v) + wet[2 * i + c] * s->mix.v);
            }
        }
    }
}

static double phaser_tail(const kc_fx *f) { (void)f; return 0.3; }

const kc_type kc_phaser_type = {"phaser", 6, phaser_p, phaser_d, sizeof(phaser_state), 0, phaser_reset, phaser_process,
                                0, phaser_tail, 0, 0};

/* -- tremolo / auto pan -------------------------------------------------------------------------- */
typedef struct { double phase; ramp amount, off; } trem_state;
static const char *const pulsator_p[] = {"hz", "amount", "off"};
static const double pulsator_d[] = {4, 100, 50};

static void trem_reset(kc_fx *f) { memset(f->state, 0, sizeof(trem_state)); }

static void pulsator_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    trem_state *s = f->state;
    double rate = kc_clamp(f->p[0], 0.01, 40);
    (void)side;
    if (f->fresh)
        s->phase = frac((double)pos * rate / f->sr);
    aim(&s->amount, kc_clamp(f->p[1], 0, 100) / 100.0, n, f->fresh);
    aim(&s->off, kc_clamp(f->p[2], 0, 100) / 100.0, n, f->fresh);
    for (int i = 0; i < n; i++) {
        s->amount.v += s->amount.d;
        s->off.v += s->off.d;
        for (int c = 0; c < 2; c++)
            out[2 * i + c] = (float)(in[2 * i + c] * (1.0 - s->amount.v * wave(s->phase + c * s->off.v)));
        s->phase = frac(s->phase + rate / f->sr);
    }
}

const kc_type kc_pulsator_type = {"pulsator", 3, pulsator_p, pulsator_d, sizeof(trem_state), 0, trem_reset,
                                  pulsator_process, 0, 0, 0, 0};

/* -- saturation ----------------------------------------------------------------------------------- */
typedef struct { ramp gain, drive, bias, mix; double x1[2], y1[2]; } sat_state;
static const char *const sat_p[] = {"in", "drive", "blend", "mix"};
static const double sat_d[] = {0, 5, 10, 100};

static void sat_reset(kc_fx *f) { memset(f->state, 0, sizeof(sat_state)); }

static void sat_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    sat_state *s = f->state;
    (void)side; (void)pos;
    aim(&s->gain, kc_db_lin(f->p[0]), n, f->fresh);
    aim(&s->drive, kc_clamp(f->p[1], 0.1, 10), n, f->fresh);
    /* blend 10: the curve is the same up and down (odd harmonics); lower: pushed off centre, which adds even ones */
    aim(&s->bias, (10.0 - kc_clamp(f->p[2], -10, 10)) / 40.0, n, f->fresh);
    aim(&s->mix, kc_clamp(f->p[3], 0, 100) / 100.0, n, f->fresh);
    double keep = exp(-2.0 * KC_PI * 5.0 / f->sr);        /* takes the offset the bias makes away */
    for (int i = 0; i < n; i++) {
        s->gain.v += s->gain.d;
        s->drive.v += s->drive.d;
        s->bias.v += s->bias.d;
        s->mix.v += s->mix.d;
        double d = s->drive.v, b = s->bias.v, rest = tanh(d * b), norm = 1.0 / tanh(d);
        for (int c = 0; c < 2; c++) {
            double x = in[2 * i + c], v = (tanh(d * (x * s->gain.v + b)) - rest) * norm;
            double y = v - s->x1[c] + keep * s->y1[c];
            s->x1[c] = v;
            s->y1[c] = kc_flush(y);
            out[2 * i + c] = (float)(x * (1 - s->mix.v) + y * s->mix.v);
        }
    }
}

static double short_tail(const kc_fx *f) { (void)f; return 0.2; }

const kc_type kc_saturator_type = {"saturator", 4, sat_p, sat_d, sizeof(sat_state), 0, sat_reset, sat_process,
                                   0, short_tail, 0, 0};

/* -- bass enhancer and exciter: harmonics made from one end of the spectrum and added to the whole -- */
typedef struct { kc_bqstate split[2], keep; kc_coef sc, kc; ramp gain, amount, drive, post; } harm_state;
static const char *const harm_p[] = {"in", "freq", "drive", "out"};
static const double bass_d[] = {0, 100, 6, 0};
static const double exciter_d[] = {0, 7500, 6, 0};

static void harm_reset(kc_fx *f) { memset(f->state, 0, sizeof(harm_state)); }

static void harm_run(kc_fx *f, int bass, const float *in, float *out, int n) {
    harm_state *s = f->state;
    double freq = f->p[1], drive = kc_clamp(f->p[2], 0.1, 10);
    /* bass: what is below freq makes harmonics, of which those above half of it are added; exciter: above freq, both times */
    kc_coef sc = kc_biquad(bass ? KC_BQ_HIGHCUT : KC_BQ_LOWCUT, f->sr, freq, 0.7071, 0);
    kc_coef kc = kc_biquad(KC_BQ_LOWCUT, f->sr, bass ? freq * 0.7 : freq, 0.7071, 0);
    if (f->fresh) {
        s->sc = sc;
        s->kc = kc;
    }
    aim(&s->gain, kc_db_lin(f->p[0]), n, f->fresh);
    aim(&s->drive, drive, n, f->fresh);
    aim(&s->amount, drive / 10.0, n, f->fresh);
    aim(&s->post, kc_db_lin(f->p[3]), n, f->fresh);
    float dry[2 * 256], part[2 * 256];
    for (int at = 0; at < n; at += 256) {
        int m = n - at < 256 ? n - at : 256;
        for (int i = 0; i < m; i++) {
            s->gain.v += s->gain.d;
            for (int c = 0; c < 2; c++)
                dry[2 * i + c] = (float)(in[2 * (at + i) + c] * s->gain.v);
        }
        kc_coef from = s->sc;
        kc_biquad_run(&s->split[0], &from, &sc, dry, part, m);
        kc_biquad_run(&s->split[1], &from, &sc, part, part, m);
        for (int i = 0; i < m; i++) {
            s->drive.v += s->drive.d;
            for (int c = 0; c < 2; c++) {
                double v = part[2 * i + c] * (1.0 + s->drive.v);
                part[2 * i + c] = (float)(tanh(v + 0.35 * v * v / (1.0 + fabs(v))) - tanh(part[2 * i + c]));
            }
        }
        from = s->kc;
        kc_biquad_run(&s->keep, &from, &kc, part, part, m);
        s->sc = sc;
        s->kc = kc;
        for (int i = 0; i < m; i++) {
            s->amount.v += s->amount.d;
            s->post.v += s->post.d;
            for (int c = 0; c < 2; c++)
                out[2 * (at + i) + c] = (float)((dry[2 * i + c] + part[2 * i + c] * s->amount.v) * s->post.v);
        }
    }
}

static void bass_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    (void)side; (void)pos;
    harm_run(f, 1, in, out, n);
}

static void exciter_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    (void)side; (void)pos;
    harm_run(f, 0, in, out, n);
}

const kc_type kc_bass_type = {"bass", 4, harm_p, bass_d, sizeof(harm_state), 0, harm_reset, bass_process,
                              0, short_tail, 0, 0};
const kc_type kc_exciter_type = {"exciter", 4, harm_p, exciter_d, sizeof(harm_state), 0, harm_reset, exciter_process,
                                 0, short_tail, 0, 0};

/* -- tape: soft saturation, the highs lost, hiss, and a speed that wavers --------------------------- */
#define TAPE_BASE_MS 5.0            /* where the wavering read head rests: the effect is this late */
typedef struct {
    float wet[2][ML_LEN], dry[2][ML_LEN];
    int64_t w;
    kc_bqstate lp;
    kc_coef c;
    ramp gain, noise, mech, mix;
    double wow, flutter;
} tape_state;
static const char *const tape_p[] = {"in", "lp", "noise", "mech", "mix"};
static const double tape_d[] = {-6, 12500, 10, 20, 100};

static void tape_reset(kc_fx *f) {
    memset(f->state, 0, sizeof(tape_state));
    ((tape_state *)f->state)->w = ML_LEN;
}

/* the same number for the same sample of the line, whatever was played before */
static inline double hiss(int64_t pos, int c) {
    uint64_t v = (uint64_t)pos * 2 + (uint64_t)c;
    v = (v ^ (v >> 30)) * 0xbf58476d1ce4e5b9ULL;
    v = (v ^ (v >> 27)) * 0x94d049bb133111ebULL;
    v ^= v >> 31;
    return (double)(v >> 11) / 9007199254740992.0 * 2.0 - 1.0;
}

static int tape_latency(const kc_fx *f) { return (int)(TAPE_BASE_MS * f->sr / 1000.0); }

static void tape_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    tape_state *s = f->state;
    double ms = f->sr / 1000.0;
    int late = tape_latency(f);
    (void)side;
    if (f->fresh) {
        s->wow = frac((double)pos * 0.7 / f->sr);
        s->flutter = frac((double)pos * 7.3 / f->sr);
    }
    kc_coef to = kc_biquad(KC_BQ_HIGHCUT, f->sr, f->p[1], 0.7071, 0);
    if (f->fresh)
        s->c = to;
    aim(&s->gain, kc_db_lin(f->p[0]), n, f->fresh);
    aim(&s->noise, kc_clamp(f->p[2], 0, 100) / 100.0 * 0.006, n, f->fresh);
    aim(&s->mech, kc_clamp(f->p[3], 0, 100) / 100.0, n, f->fresh);
    aim(&s->mix, kc_clamp(f->p[4], 0, 100) / 100.0, n, f->fresh);
    float stage[2 * 256];
    for (int at = 0; at < n; at += 256) {
        int m = n - at < 256 ? n - at : 256;
        for (int i = 0; i < m; i++) {
            s->gain.v += s->gain.d;
            s->noise.v += s->noise.d;
            for (int c = 0; c < 2; c++) {
                double x = in[2 * (at + i) + c];
                stage[2 * i + c] = (float)(tanh(x * s->gain.v * 1.5) / 1.5 + hiss(pos + at + i, c) * s->noise.v);
            }
        }
        kc_coef from = s->c;
        kc_biquad_run(&s->lp, &from, &to, stage, stage, m);
        s->c = to;
        for (int i = 0; i < m; i++) {
            s->mech.v += s->mech.d;
            s->mix.v += s->mix.d;
            double back = late + s->mech.v * ms * (1.6 * sin(2 * KC_PI * s->wow) + 0.12 * sin(2 * KC_PI * s->flutter));
            for (int c = 0; c < 2; c++) {
                s->dry[c][s->w & (ML_LEN - 1)] = in[2 * (at + i) + c];
                s->wet[c][s->w & (ML_LEN - 1)] = stage[2 * i + c];
                double wet = tap(s->wet[c], s->w, back), dry = tap(s->dry[c], s->w, late);
                out[2 * (at + i) + c] = (float)(dry * (1 - s->mix.v) + wet * s->mix.v);
            }
            s->w++;
            s->wow = frac(s->wow + 0.7 / f->sr);
            s->flutter = frac(s->flutter + 7.3 / f->sr);
        }
    }
}

const kc_type kc_tape_type = {"tape", 5, tape_p, tape_d, sizeof(tape_state), 0, tape_reset, tape_process,
                              tape_latency, short_tail, 0, 0};

/* -- bit crusher: fewer levels, and fewer samples (each held) --------------------------------------- */
typedef struct { double held[2]; double count; ramp gain; int started; } crush_state;
static const char *const crush_p[] = {"in", "bits", "samples", "morph"};
static const double crush_d[] = {0, 8, 1, 0.5};

static void crush_reset(kc_fx *f) { memset(f->state, 0, sizeof(crush_state)); }

static void crush_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    crush_state *s = f->state;
    double bits = kc_clamp(f->p[1], 1, 16), every = kc_clamp(f->p[2], 1, 250), morph = kc_clamp(f->p[3], 0, 1);
    double steps = pow(2.0, bits - 1);
    (void)side;
    if (f->fresh) {
        s->count = fmod((double)pos, every);        /* the holds fall where they would from the start */
        s->started = 0;
    }
    aim(&s->gain, kc_db_lin(f->p[0]), n, f->fresh);
    for (int i = 0; i < n; i++) {
        s->gain.v += s->gain.d;
        int take = !s->started || s->count < 1.0;
        for (int c = 0; c < 2; c++) {
            if (take) {
                double x = kc_clamp(in[2 * i + c] * s->gain.v, -1.0, 1.0);
                double straight = floor(x * steps + 0.5) / steps;
                /* morph: toward levels spaced as the ear hears them (fine near silence, coarse when loud) */
                double bent = copysign(log1p(255.0 * fabs(x)) / log(256.0), x);
                bent = floor(bent * steps + 0.5) / steps;
                bent = copysign(expm1(fabs(bent) * log(256.0)) / 255.0, bent);
                s->held[c] = straight + (bent - straight) * morph;
            }
            out[2 * i + c] = (float)s->held[c];
        }
        s->started = 1;
        s->count += 1.0;
        if (s->count >= every)
            s->count -= every;
    }
}

const kc_type kc_crusher_type = {"crusher", 4, crush_p, crush_d, sizeof(crush_state), 0, crush_reset, crush_process,
                                 0, 0, 0, 0};
